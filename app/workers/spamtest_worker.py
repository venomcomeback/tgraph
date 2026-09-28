"""
TGraph - Spam Testi Worker (QThread + asyncio)
Her hesap için @SpamBot ile durum kontrolü.
"""
import asyncio
import datetime
from typing import Dict, Any, List

from PySide6.QtCore import QThread, Signal

from ..telegram_client import TGClient


class SpamTestWorker(QThread):
    result = Signal(dict)      # {account_id, name, phone, status, detail, time}
    log = Signal(str, str)
    finished_ok = Signal()
    error = Signal(str)

    def __init__(self, accounts: List[Dict[str, Any]], proxies_by_id: Dict[int, Any] = None):
        super().__init__()
        self.accounts = accounts
        self.proxies_by_id = proxies_by_id or {}
        self._stop = False

    def stop(self):
        self._stop = True

    def _proxy_for(self, account):
        # Öncelik: atanmış TR proxy (assigned_proxy_id) > manuel proxy (proxy_id)
        pid = account.get("assigned_proxy_id") or account.get("proxy_id")
        if pid and pid in self.proxies_by_id:
            return self.proxies_by_id[pid]
        return None

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._test_all())
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _test_all(self):
        for acc in self.accounts:
            if self._stop:
                break
            name = acc.get("name") or acc["session_name"]
            phone = acc.get("phone", "")
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.log.emit(f"'{name}' test ediliyor...", "info")
            client = TGClient(acc["session_name"], acc["api_id"], acc["api_hash"], self._proxy_for(acc))
            try:
                ok = await client.connect()
                if not ok:
                    self.result.emit({
                        "account_id": acc.get("id"),
                        "name": name, "phone": phone,
                        "status": "banned", "detail": "Yetkili değil / Yasaklı",
                        "time": ts,
                    })
                    self.log.emit(f"'{name}' yetkili değil.", "error")
                    await client.disconnect()
                    continue
                status = await client.check_spam_status()
                self.result.emit({
                    "account_id": acc.get("id"),
                    "name": name, "phone": phone,
                    "status": status["status"], "detail": status["detail"],
                    "time": ts,
                })
                self.log.emit(f"'{name}' → {status['status'].upper()}", 
                              "success" if status["status"] == "ok" else "warning")
            except Exception as e:
                self.result.emit({
                    "account_id": acc.get("id"),
                    "name": name, "phone": phone,
                    "status": "banned", "detail": f"Hata: {e}",
                    "time": ts,
                })
                self.log.emit(f"'{name}' hata: {e}", "error")
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass
        self.finished_ok.emit()
