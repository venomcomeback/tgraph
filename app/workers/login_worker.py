"""
TGraph - Hesap Giriş Worker (QThread + asyncio)
İki aşamalı giriş: (1) kod gönder, (2) kod + 2FA ile giriş.
Ayrıca .session dosyası doğrulama.
"""
import asyncio
from typing import Dict, Any, Optional

from PySide6.QtCore import QThread, Signal

from ..telegram_client import TGClient


class SendCodeWorker(QThread):
    """Telefona OTP kodu gönderir."""
    code_sent = Signal(str)      # phone_code_hash
    error = Signal(str)

    def __init__(self, session_name, api_id, api_hash, phone, proxy=None):
        super().__init__()
        self.session_name = session_name
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.proxy = proxy
        self.client: Optional[TGClient] = None

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            self.client = TGClient(self.session_name, self.api_id, self.api_hash, self.proxy)
            result = loop.run_until_complete(self.client.send_code(self.phone))
            self.code_sent.emit(result.phone_code_hash)
        except Exception as e:
            self.error.emit(str(e))


class SignInWorker(QThread):
    """OTP kodu (+ gerekiyorsa 2FA) ile giriş yapar."""
    need_password = Signal()
    success = Signal(dict)       # get_me sonucu
    error = Signal(str)

    def __init__(self, client: TGClient, phone, code, phone_code_hash, password=""):
        super().__init__()
        self.client = client
        self.phone = phone
        self.code = code
        self.phone_code_hash = phone_code_hash
        self.password = password

    def run(self):
        from telethon.errors import SessionPasswordNeededError
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            try:
                me = loop.run_until_complete(
                    self.client.sign_in(self.phone, self.code, self.phone_code_hash, self.password or None)
                )
                self.success.emit(me or {})
            except SessionPasswordNeededError:
                if self.password:
                    me = loop.run_until_complete(self.client.sign_in_password(self.password))
                    self.success.emit(me or {})
                else:
                    self.need_password.emit()
        except Exception as e:
            self.error.emit(str(e))


class ConnectCheckWorker(QThread):
    """Bir session'ın geçerli olup olmadığını kontrol eder ve hesap bilgisini alır."""
    result = Signal(int, bool, dict, str)   # account_id, ok, me, error

    def __init__(self, account: Dict[str, Any], proxy=None):
        super().__init__()
        self.account = account
        self.proxy = proxy

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        client = TGClient(
            self.account["session_name"], self.account["api_id"],
            self.account["api_hash"], self.proxy,
        )
        try:
            ok = loop.run_until_complete(client.connect())
            me = {}
            if ok:
                me = loop.run_until_complete(client.get_me()) or {}
            loop.run_until_complete(client.disconnect())
            self.result.emit(self.account.get("id", 0), ok, me, "")
        except Exception as e:
            try:
                loop.run_until_complete(client.disconnect())
            except Exception:
                pass
            self.result.emit(self.account.get("id", 0), False, {}, str(e))
