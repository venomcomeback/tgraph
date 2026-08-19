"""
TGraph - Üye Tarama Worker (QThread + asyncio)
"""
import asyncio
from typing import Dict, Any, List

from PySide6.QtCore import QThread, Signal

from ..telegram_client import TGClient
from telethon.errors import FloodWaitError


class ScraperWorker(QThread):
    progress = Signal(int, int)          # taranan, toplam
    member_found = Signal(dict)          # bulunan üye
    finished_ok = Signal(list)           # tüm üyeler
    error = Signal(str)                  # hata mesajı
    log = Signal(str, str)               # (mesaj, seviye)

    def __init__(self, account: Dict[str, Any], group_link: str,
                 filters: Dict[str, Any], proxy: Dict[str, Any] = None):
        super().__init__()
        self.account = account
        self.group_link = group_link
        self.filters = filters
        self.proxy = proxy
        self._stop = False
        self._results: List[Dict[str, Any]] = []

    def stop(self):
        self._stop = True

    def should_stop(self) -> bool:
        return self._stop

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._scrape())
        except FloodWaitError as e:
            self.error.emit(f"FloodWait: {e.seconds} saniye beklemeniz gerekiyor.")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _scrape(self):
        client = TGClient(
            self.account["session_name"],
            self.account["api_id"],
            self.account["api_hash"],
            self.proxy,
        )
        self.log.emit(f"'{self.account.get('name') or self.account['session_name']}' ile bağlanılıyor...", "info")
        authorized = await client.connect()
        if not authorized:
            self.error.emit("Hesap yetkili değil. Lütfen önce giriş yapın.")
            await client.disconnect()
            return
        self.log.emit(f"Grup taranıyor: {self.group_link}", "info")

        def prog(done, total):
            self.progress.emit(done, total)

        try:
            results = await client.scrape_members(
                self.group_link,
                progress_cb=prog,
                should_stop=self.should_stop,
                filters=self.filters,
            )
            self._results = results
            for m in results:
                self.member_found.emit(m)
            self.log.emit(f"Tarama tamamlandı. {len(results)} üye bulundu.", "success")
            self.finished_ok.emit(results)
        except FloodWaitError as e:
            self.error.emit(f"FloodWait: {e.seconds} saniye beklemeniz gerekiyor.")
        finally:
            await client.disconnect()
