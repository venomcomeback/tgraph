"""
TGraph - Üye Ekleme Worker (QThread + asyncio)
Çoklu hesap, gecikme ayarları, büyük mola, günlük limit, FloodWait yönetimi.
"""
import asyncio
import random
import datetime
from typing import Dict, Any, List

from PySide6.QtCore import QThread, Signal

from ..telegram_client import TGClient
from telethon.errors import FloodWaitError, PeerFloodError


class AdderWorker(QThread):
    progress = Signal(int, int)       # eklenen, toplam
    log = Signal(str, str)            # (mesaj, seviye: info/success/error/warning)
    account_stat = Signal(str, int, str)   # (hesap adı, eklenen sayı, durum)
    flood_wait = Signal(int)          # saniye
    finished_ok = Signal(dict)        # özet
    error = Signal(str)

    def __init__(self, accounts: List[Dict[str, Any]], target_group: str,
                 members: List[Dict[str, Any]], settings: Dict[str, Any],
                 proxies_by_id: Dict[int, Any] = None):
        super().__init__()
        self.accounts = accounts
        self.target_group = target_group
        self.members = members
        self.settings = settings
        self.proxies_by_id = proxies_by_id or {}
        self._stop = False
        self._paused = False

    def stop(self):
        self._stop = True

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._add_all())
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _wait_if_paused(self):
        while self._paused and not self._stop:
            await asyncio.sleep(0.5)

    def _proxy_for(self, account):
        pid = account.get("proxy_id")
        if pid and pid in self.proxies_by_id:
            return self.proxies_by_id[pid]
        return None

    async def _add_all(self):
        min_delay = int(self.settings.get("min_delay", 30))
        max_delay = int(self.settings.get("max_delay", 60))
        big_break_every = int(self.settings.get("big_break_every", 10))
        big_break_minutes = int(self.settings.get("big_break_minutes", 15))
        daily_limit = int(self.settings.get("daily_add_limit", 40))
        by_username = self.settings.get("by_username", False)

        if not self.accounts:
            self.error.emit("Hiç aktif hesap seçilmedi.")
            return
        if not self.members:
            self.error.emit("Eklenecek üye bulunamadı.")
            return

        # Hesap istemcilerini hazırla
        clients: Dict[str, TGClient] = {}
        entities: Dict[str, Any] = {}
        counters: Dict[str, int] = {}
        active_accounts: List[Dict[str, Any]] = []

        for acc in self.accounts:
            name = acc.get("name") or acc["session_name"]
            self.log.emit(f"'{name}' bağlanıyor...", "info")
            client = TGClient(acc["session_name"], acc["api_id"], acc["api_hash"], self._proxy_for(acc))
            try:
                ok = await client.connect()
                if not ok:
                    self.log.emit(f"'{name}' yetkili değil, atlanıyor.", "error")
                    continue
                entity = await client.get_entity(self.target_group)
                clients[acc["session_name"]] = client
                entities[acc["session_name"]] = entity
                counters[acc["session_name"]] = 0
                active_accounts.append(acc)
                self.account_stat.emit(name, 0, "Hazır")
                self.log.emit(f"'{name}' hazır.", "success")
            except Exception as e:
                self.log.emit(f"'{name}' bağlanamadı: {e}", "error")
                try:
                    await client.disconnect()
                except Exception:
                    pass

        if not active_accounts:
            self.error.emit("Hiçbir hesap bağlanamadı.")
            return

        total = len(self.members)
        added = 0
        idx = 0
        acc_rotation = 0

        for member in self.members:
            if self._stop:
                self.log.emit("İşlem kullanıcı tarafından durduruldu.", "warning")
                break
            await self._wait_if_paused()
            if self._stop:
                break

            # Uygun hesabı seç (limit dolmayan)
            available = [a for a in active_accounts
                         if counters[a["session_name"]] < daily_limit]
            if not available:
                self.log.emit("Tüm hesaplar günlük limite ulaştı.", "warning")
                break
            acc = available[acc_rotation % len(available)]
            acc_rotation += 1
            sname = acc["session_name"]
            name = acc.get("name") or sname
            client = clients[sname]
            entity = entities[sname]

            uname = member.get("username") or member.get("user_id")
            try:
                success, msg = await client.add_member(entity, member, by_username=by_username)
                if success:
                    added += 1
                    counters[sname] += 1
                    member["_added_by"] = sname
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    self.log.emit(f"[{ts}] ✔ {name} → {uname} : {msg}", "success")
                    self.account_stat.emit(name, counters[sname], "Ekliyor")
                else:
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    self.log.emit(f"[{ts}] ✘ {name} → {uname} : {msg}", "error")
                    if "PeerFlood" in msg:
                        self.account_stat.emit(name, counters[sname], "Spam!")
                        # Bu hesabı devreden çıkar
                        active_accounts = [a for a in active_accounts if a["session_name"] != sname]
                        self.log.emit(f"'{name}' spam limitine takıldı, devreden çıkarıldı.", "warning")
            except FloodWaitError as e:
                secs = e.seconds
                self.log.emit(f"'{name}' FloodWait: {secs} saniye bekleniyor...", "warning")
                self.flood_wait.emit(secs)
                # Kısa flood ise bekle, uzunsa hesabı atla
                if secs <= 300:
                    waited = 0
                    while waited < secs and not self._stop:
                        await asyncio.sleep(1)
                        waited += 1
                else:
                    active_accounts = [a for a in active_accounts if a["session_name"] != sname]
                    self.log.emit(f"'{name}' uzun FloodWait nedeniyle devreden çıkarıldı.", "warning")
                continue
            except Exception as e:
                self.log.emit(f"'{name}' beklenmeyen hata: {e}", "error")

            idx += 1
            self.progress.emit(added, total)

            if not active_accounts:
                self.log.emit("Kullanılabilir hesap kalmadı.", "warning")
                break

            # Büyük mola kontrolü
            if big_break_every > 0 and idx % big_break_every == 0:
                self.log.emit(f"Büyük mola: {big_break_minutes} dakika bekleniyor...", "info")
                mola = big_break_minutes * 60
                waited = 0
                while waited < mola and not self._stop:
                    await asyncio.sleep(1)
                    waited += 1
            else:
                # Normal gecikme
                delay = random.randint(min_delay, max(min_delay, max_delay))
                self.log.emit(f"{delay} saniye bekleniyor...", "info")
                waited = 0
                while waited < delay and not self._stop:
                    await asyncio.sleep(1)
                    waited += 1

        # Bağlantıları kapat
        for client in clients.values():
            try:
                await client.disconnect()
            except Exception:
                pass

        summary = {
            "added": added,
            "total": total,
            "per_account": {(a.get("name") or a["session_name"]): counters.get(a["session_name"], 0)
                            for a in self.accounts},
        }
        self.log.emit(f"İşlem tamamlandı. Toplam {added}/{total} üye eklendi.", "success")
        self.finished_ok.emit(summary)
