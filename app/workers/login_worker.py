"""
TGraph - Hesap Giriş Worker (QThread + asyncio)
İki aşamalı giriş: (1) kod gönder, (2) kod + 2FA ile giriş.
Ayrıca .session dosyası doğrulama ve toplu session içe aktarma.
"""
import os
import shutil
import asyncio
from typing import Dict, Any, Optional, List

from PySide6.QtCore import QThread, Signal

from ..telegram_client import TGClient, session_path
from ..config import STATUS_UNKNOWN
from .. import cgraph_compat
from ..bulk_utils import load_folder_credentials, phone_key


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


def _is_phone_like(name: str) -> bool:
    """Dosya adı bir telefon numarasına benziyor mu (çoğunlukla rakam)?"""
    d = name.lstrip("+").replace(" ", "")
    return d.isdigit() and len(d) >= 7


class BulkImportSessionsWorker(QThread):
    """
    Bir klasördeki tüm *.cgsession ve *.session dosyalarını (kök + bir alt klasör
    seviyesi) tarar ve TGraph oturumlarına aktarır.

    * .cgsession  -> cgraph_compat.convert_cgsession_to_telethon() ile çevrilir,
                     API bilgileri dosyadan okunur.
    * .session    -> SESSIONS_DIR içine kopyalanır. API bilgileri önce aynı
                     klasördeki .txt dosyalarından (telefon eşlemesiyle), yoksa
                     verilen varsayılan API ID/Hash'ten alınır. Bulunamazsa yine
                     içe aktarılır ancak bilgi eksik olarak not düşülür.
    """
    progress = Signal(str)               # canlı log satırı
    finished_summary = Signal(int, int, int)   # imported, skipped, errors

    def __init__(self, db, folder: str, existing_names: List[str],
                 default_api_id: str = "", default_api_hash: str = ""):
        super().__init__()
        self.db = db
        self.folder = folder
        self.existing = set(existing_names or [])
        self.default_api_id = (default_api_id or "").strip()
        self.default_api_hash = (default_api_hash or "").strip()

    def _scan_files(self):
        """Kök klasör + bir seviye alt klasörlerden oturum dosyalarını toplar."""
        found = []  # (full_path, parent_folder)
        try:
            entries = sorted(os.listdir(self.folder))
        except Exception as e:
            self.progress.emit(f"❌ Klasör okunamadı: {e}")
            return found
        for name in entries:
            full = os.path.join(self.folder, name)
            low = name.lower()
            if os.path.isfile(full) and (low.endswith(".cgsession") or low.endswith(".session")):
                found.append((full, self.folder))
            elif os.path.isdir(full):
                try:
                    for sub in sorted(os.listdir(full)):
                        subfull = os.path.join(full, sub)
                        slow = sub.lower()
                        if os.path.isfile(subfull) and (slow.endswith(".cgsession") or slow.endswith(".session")):
                            found.append((subfull, full))
                except Exception:
                    continue
        return found

    def run(self):
        imported = skipped = errors = 0
        files = self._scan_files()
        if not files:
            self.progress.emit("⚠️ Klasörde .cgsession veya .session dosyası bulunamadı.")
            self.finished_summary.emit(0, 0, 0)
            return

        self.progress.emit(f"🔍 {len(files)} oturum dosyası bulundu. İşleniyor...")

        # Her klasör için .txt kimlik bilgilerini önbelleğe al
        cred_cache: Dict[str, Dict[str, Any]] = {}

        for full, parent in files:
            base = os.path.basename(full)
            name_no_ext = base
            for ext in (".cgsession", ".session"):
                if name_no_ext.lower().endswith(ext):
                    name_no_ext = name_no_ext[: -len(ext)]
                    break
            session_name = name_no_ext

            if session_name in self.existing:
                skipped += 1
                self.progress.emit(f"⏭️ Atlandı (zaten kayıtlı): {session_name}")
                continue

            try:
                dest = session_path(session_name) + ".session"
                is_cg = full.lower().endswith(".cgsession")

                if is_cg:
                    info = cgraph_compat.convert_cgsession_to_telethon(full, dest)
                    api_id = str(info.get("api_id", ""))
                    api_hash = info.get("api_hash", "")
                    phone = "+" + phone_key(session_name) if _is_phone_like(session_name) else ""
                    status = STATUS_UNKNOWN
                    note = "Cgraph oturumu çevrildi"
                else:
                    # Düz .session -> kopyala
                    if os.path.abspath(full) != os.path.abspath(dest):
                        shutil.copy2(full, dest)
                    # Kimlik bilgilerini çöz: aynı klasördeki .txt, sonra varsayılanlar
                    if parent not in cred_cache:
                        cred_cache[parent] = load_folder_credentials(parent)
                    creds = cred_cache[parent]
                    api_id = api_hash = ""
                    phone = ""
                    key = phone_key(session_name) if _is_phone_like(session_name) else ""
                    rec = creds.get(key) if key else None
                    if rec:
                        api_id = rec.get("api_id") or ""
                        api_hash = rec.get("api_hash") or ""
                        phone = rec.get("phone") or ""
                    if not (api_id and api_hash):
                        if self.default_api_id and self.default_api_hash:
                            api_id = api_id or self.default_api_id
                            api_hash = api_hash or self.default_api_hash
                    if not phone and _is_phone_like(session_name):
                        phone = "+" + phone_key(session_name)
                    status = STATUS_UNKNOWN
                    if api_id and api_hash:
                        note = "Telethon oturumu kopyalandı"
                    else:
                        note = "API bilgisi yok (eksik)"

                self.db.add_account(
                    session_name=session_name,
                    phone=phone,
                    name="",
                    api_id=api_id,
                    api_hash=api_hash,
                    proxy_id=None,
                    status=status,
                )
                self.existing.add(session_name)
                imported += 1
                self.progress.emit(f"✅ İçe aktarıldı: {session_name}  ({note})")
            except Exception as e:
                errors += 1
                self.progress.emit(f"❌ Hata ({session_name}): {e}")

        self.progress.emit(
            f"🏁 Tamamlandı — {imported} içe aktarıldı, {skipped} atlandı, {errors} hata."
        )
        self.finished_summary.emit(imported, skipped, errors)
