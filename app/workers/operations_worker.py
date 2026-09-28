"""
TGraph - Hesap İşlemleri Worker'ları (QThread + asyncio)
========================================================

Aktif hesaplar üzerinde çalışan toplu işlem worker'ları:

* LoginCodeMonitorWorker  - Giriş kodu izleme (777000 servis hesabı)
* ReactionsViewsWorker    - Toplu emoji tepkisi + görüntülenme
* GiveawayJoinWorker      - Randy çekilişlerine katılma
* BulkDMWorker            - Toplu özel mesaj
* JoinChannelsWorker      - Toplu kanal/grup katılımı
* LeaveChannelsWorker     - Toplu gruptan çıkma
* ProfileUpdateWorker     - Toplu profil güncelleme

Tüm worker'lar TGClient'ı hesabın atanmış TR proxy'siyle (varsa) açar;
tüm günlük mesajları Türkçedir.
"""
import asyncio
import datetime
from typing import List, Dict, Any, Optional

from PySide6.QtCore import QThread, Signal

from ..telegram_client import TGClient


def _acc_label(acc: Dict[str, Any]) -> str:
    return acc.get("name") or acc.get("phone") or acc.get("session_name") or "?"


def _make_client(db, acc: Dict[str, Any]) -> TGClient:
    """Hesap için TGClient oluşturur (atanmış TR proxy varsa onu kullanır)."""
    proxy = None
    try:
        proxy = db.get_account_proxy(acc)
    except Exception:
        proxy = None
    return TGClient(acc["session_name"], acc["api_id"], acc["api_hash"], proxy)


# ====================================================================== #
#  1) Giriş Kodu İzleme
# ====================================================================== #
class LoginCodeMonitorWorker(QThread):
    """Seçili hesaplar için Telegram servis hesabından (777000) gelen giriş
    kodlarını periyodik olarak izler."""
    code_found = Signal(str, str, str)   # hesap, kod, zaman
    log = Signal(str)

    def __init__(self, db, accounts: List[Dict[str, Any]], interval: int = 5):
        super().__init__()
        self.db = db
        self.accounts = accounts
        self.interval = max(3, int(interval))
        self._stop = False

    def stop(self):
        self._stop = True

    async def _monitor(self):
        clients: Dict[int, TGClient] = {}
        last_seen: Dict[int, int] = {}   # account_id -> son işlenen msg_id

        # Bağlan
        for acc in self.accounts:
            if self._stop:
                break
            label = _acc_label(acc)
            tg = _make_client(self.db, acc)
            try:
                ok = await tg.connect()
                if not ok:
                    self.log.emit(f"⚠️ '{label}' oturumu geçersiz, atlanıyor.")
                    await tg.disconnect()
                    continue
                clients[acc["id"]] = tg
                self.log.emit(f"👁️ '{label}' izleniyor...")
            except Exception as e:
                self.log.emit(f"❌ '{label}' bağlanamadı: {e}")

        if not clients:
            self.log.emit("⚠️ İzlenecek bağlı hesap yok.")
            return

        self.log.emit(f"✅ {len(clients)} hesap izleniyor. Yeni giriş kodları burada görünecek.")

        # İzleme döngüsü
        while not self._stop:
            for acc in self.accounts:
                if self._stop:
                    break
                tg = clients.get(acc["id"])
                if not tg:
                    continue
                label = _acc_label(acc)
                try:
                    codes = await tg.fetch_login_codes(limit=3)
                except Exception as e:
                    self.log.emit(f"⚠️ '{label}' okunamadı: {e}")
                    continue
                for c in codes:
                    mid = c.get("msg_id", 0)
                    if mid and mid <= last_seen.get(acc["id"], 0):
                        continue
                    last_seen[acc["id"]] = max(last_seen.get(acc["id"], 0), mid)
                    dt = c.get("date")
                    tstr = dt.strftime("%Y-%m-%d %H:%M:%S") if dt else \
                        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self.code_found.emit(label, c["code"], tstr)
                    self.log.emit(f"🔑 '{label}' için giriş kodu: {c['code']}")
            # Bekleme (durdurmaya duyarlı)
            for _ in range(self.interval * 2):
                if self._stop:
                    break
                await asyncio.sleep(0.5)

        # Kapat
        for tg in clients.values():
            try:
                await tg.disconnect()
            except Exception:
                pass
        self.log.emit("⏹️ İzleme durduruldu.")

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._monitor())
        except Exception as e:
            self.log.emit(f"❌ Hata: {e}")
        finally:
            try:
                loop.close()
            except Exception:
                pass


# ====================================================================== #
#  2) Toplu Emoji ve Görüntülenme
# ====================================================================== #
class ReactionsViewsWorker(QThread):
    """Seçili hesaplarla gönderilere emoji tepkisi ve/veya görüntülenme gönderir."""
    log = Signal(str)
    progress = Signal(int, int)          # yapılan, toplam
    finished_ok = Signal(int, int)       # başarı, hata

    def __init__(self, db, accounts, links: List[str], emojis: List[str],
                 do_react: bool, do_view: bool, delay: int = 3):
        super().__init__()
        self.db = db
        self.accounts = accounts
        self.links = links
        self.emojis = emojis or ["👍"]
        self.do_react = do_react
        self.do_view = do_view
        self.delay = max(0, int(delay))
        self._stop = False

    def stop(self):
        self._stop = True

    async def _run(self):
        total = len(self.accounts) * len(self.links)
        done = ok = err = 0
        for ai, acc in enumerate(self.accounts):
            if self._stop:
                break
            label = _acc_label(acc)
            tg = _make_client(self.db, acc)
            try:
                connected = await tg.connect()
                if not connected:
                    self.log.emit(f"⚠️ '{label}' oturumu geçersiz, atlanıyor.")
                    await tg.disconnect()
                    done += len(self.links)
                    self.progress.emit(done, total)
                    continue
            except Exception as e:
                self.log.emit(f"❌ '{label}' bağlanamadı: {e}")
                done += len(self.links)
                self.progress.emit(done, total)
                continue

            emoji = self.emojis[ai % len(self.emojis)]
            for link in self.links:
                if self._stop:
                    break
                try:
                    entity, msg_id = await tg.resolve_post(link)
                    acted = []
                    if self.do_react:
                        await tg.send_reaction(entity, msg_id, emoji)
                        acted.append(f"tepki {emoji}")
                    if self.do_view:
                        await tg.increment_view(entity, msg_id)
                        acted.append("görüntülenme")
                    ok += 1
                    self.log.emit(f"✅ '{label}' → {link}: {', '.join(acted) or 'işlem yok'}")
                except Exception as e:
                    from telethon.errors import FloodWaitError
                    if isinstance(e, FloodWaitError):
                        self.log.emit(f"⏳ '{label}' FloodWait: {e.seconds}s bekleniyor...")
                        await asyncio.sleep(min(e.seconds, 60))
                    else:
                        err += 1
                        self.log.emit(f"❌ '{label}' → {link}: {e}")
                done += 1
                self.progress.emit(done, total)
                if self.delay and not self._stop:
                    await asyncio.sleep(self.delay)
            try:
                await tg.disconnect()
            except Exception:
                pass
        self.log.emit(f"🏁 Tamamlandı — {ok} başarılı, {err} hata.")
        self.finished_ok.emit(ok, err)

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run())
        except Exception as e:
            self.log.emit(f"❌ Hata: {e}")
            self.finished_ok.emit(0, 0)
        finally:
            try:
                loop.close()
            except Exception:
                pass


# ====================================================================== #
#  3) Randy Çekilişlerine Katılma
# ====================================================================== #
class GiveawayJoinWorker(QThread):
    """Seçili hesaplarla çekiliş mesajlarındaki katılım butonuna tıklar."""
    log = Signal(str)
    progress = Signal(int, int)
    finished_ok = Signal(int, int)

    def __init__(self, db, accounts, links: List[str], delay: int = 3):
        super().__init__()
        self.db = db
        self.accounts = accounts
        self.links = links
        self.delay = max(0, int(delay))
        self._stop = False

    def stop(self):
        self._stop = True

    async def _run(self):
        total = len(self.accounts) * len(self.links)
        done = ok = err = 0
        for acc in self.accounts:
            if self._stop:
                break
            label = _acc_label(acc)
            tg = _make_client(self.db, acc)
            try:
                connected = await tg.connect()
                if not connected:
                    self.log.emit(f"⚠️ '{label}' oturumu geçersiz, atlanıyor.")
                    await tg.disconnect()
                    done += len(self.links)
                    self.progress.emit(done, total)
                    continue
            except Exception as e:
                self.log.emit(f"❌ '{label}' bağlanamadı: {e}")
                done += len(self.links)
                self.progress.emit(done, total)
                continue

            for link in self.links:
                if self._stop:
                    break
                try:
                    success, msg = await tg.join_giveaway(link)
                    if success:
                        ok += 1
                        self.log.emit(f"🎉 '{label}' → {link}: {msg}")
                    else:
                        err += 1
                        self.log.emit(f"⚠️ '{label}' → {link}: {msg}")
                except Exception as e:
                    from telethon.errors import FloodWaitError
                    if isinstance(e, FloodWaitError):
                        self.log.emit(f"⏳ '{label}' FloodWait: {e.seconds}s bekleniyor...")
                        await asyncio.sleep(min(e.seconds, 60))
                    else:
                        err += 1
                        self.log.emit(f"❌ '{label}' → {link}: {e}")
                done += 1
                self.progress.emit(done, total)
                if self.delay and not self._stop:
                    await asyncio.sleep(self.delay)
            try:
                await tg.disconnect()
            except Exception:
                pass
        self.log.emit(f"🏁 Tamamlandı — {ok} katılım, {err} hata.")
        self.finished_ok.emit(ok, err)

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run())
        except Exception as e:
            self.log.emit(f"❌ Hata: {e}")
            self.finished_ok.emit(0, 0)
        finally:
            try:
                loop.close()
            except Exception:
                pass


# ====================================================================== #
#  4) Toplu Özel Mesaj
# ====================================================================== #
class BulkDMWorker(QThread):
    """Seçili hesaplarla hedef kullanıcılara toplu özel mesaj gönderir.

    Hedefler: grup linkleri (üyeleri taranır) ve/veya username/id listesi.
    Hesaplar hedefleri round-robin bölüşür.
    """
    log = Signal(str)
    progress = Signal(int, int)
    finished_ok = Signal(int, int)

    def __init__(self, db, accounts, group_links: List[str], user_targets: List[str],
                 message: str, delay: int = 30, max_per_account: int = 0):
        super().__init__()
        self.db = db
        self.accounts = accounts
        self.group_links = group_links
        self.user_targets = user_targets
        self.message = message
        self.delay = max(1, int(delay))
        self.max_per_account = int(max_per_account)
        self._stop = False

    def stop(self):
        self._stop = True

    async def _collect_targets(self, tg: TGClient) -> List[Dict[str, Any]]:
        """Grup linklerinden üyeleri tarar + doğrudan username/id hedeflerini ekler."""
        targets: List[Dict[str, Any]] = []
        seen = set()
        # Grup üyeleri
        for link in self.group_links:
            if self._stop:
                break
            try:
                self.log.emit(f"🔍 Grup üyeleri taranıyor: {link}")
                members = await tg.scrape_members(link)
                for m in members:
                    uid = m.get("user_id")
                    if uid and uid not in seen:
                        seen.add(uid)
                        targets.append(m)
                self.log.emit(f"   ↳ {len(members)} üye bulundu.")
            except Exception as e:
                self.log.emit(f"⚠️ Grup taranamadı ({link}): {e}")
        # Doğrudan username/id hedefleri
        for t in self.user_targets:
            t = t.strip().lstrip("@")
            if not t or t in seen:
                continue
            seen.add(t)
            if t.isdigit():
                targets.append({"user_id": int(t), "username": ""})
            else:
                targets.append({"user_id": None, "username": t})
        return targets

    async def _run(self):
        if not self.accounts:
            self.log.emit("⚠️ Aktif hesap seçilmedi.")
            self.finished_ok.emit(0, 0)
            return
        if not self.message.strip():
            self.log.emit("⚠️ Gönderilecek mesaj boş.")
            self.finished_ok.emit(0, 0)
            return

        # İlk bağlı hesapla hedefleri topla
        first = self.accounts[0]
        tg0 = _make_client(self.db, first)
        targets: List[Dict[str, Any]] = []
        try:
            if await tg0.connect():
                targets = await self._collect_targets(tg0)
            else:
                self.log.emit(f"⚠️ '{_acc_label(first)}' oturumu geçersiz.")
        except Exception as e:
            self.log.emit(f"❌ Hedef toplama hatası: {e}")
        finally:
            try:
                await tg0.disconnect()
            except Exception:
                pass

        if not targets:
            self.log.emit("⚠️ Mesaj gönderilecek hedef bulunamadı.")
            self.finished_ok.emit(0, 0)
            return

        self.log.emit(f"📨 Toplam {len(targets)} hedefe mesaj gönderilecek.")

        # Hedefleri hesaplara round-robin böl
        n = len(self.accounts)
        buckets: Dict[int, List[Dict[str, Any]]] = {i: [] for i in range(n)}
        for idx, t in enumerate(targets):
            buckets[idx % n].append(t)

        total = len(targets)
        done = ok = err = 0
        for ai, acc in enumerate(self.accounts):
            if self._stop:
                break
            label = _acc_label(acc)
            my_targets = buckets[ai]
            if self.max_per_account > 0:
                my_targets = my_targets[:self.max_per_account]
            if not my_targets:
                continue
            tg = _make_client(self.db, acc)
            try:
                if not await tg.connect():
                    self.log.emit(f"⚠️ '{label}' oturumu geçersiz, atlanıyor.")
                    await tg.disconnect()
                    done += len(my_targets)
                    self.progress.emit(done, total)
                    continue
            except Exception as e:
                self.log.emit(f"❌ '{label}' bağlanamadı: {e}")
                done += len(my_targets)
                self.progress.emit(done, total)
                continue

            self.log.emit(f"📤 '{label}' → {len(my_targets)} hedefe gönderiyor...")
            for t in my_targets:
                if self._stop:
                    break
                target = t.get("username") or t.get("user_id")
                if not target:
                    done += 1
                    self.progress.emit(done, total)
                    continue
                try:
                    success, msg = await tg.send_dm(target, self.message)
                    if success:
                        ok += 1
                        self.log.emit(f"✅ '{label}' → {target}: gönderildi")
                    else:
                        err += 1
                        self.log.emit(f"⚠️ '{label}' → {target}: {msg}")
                except Exception as e:
                    from telethon.errors import FloodWaitError
                    if isinstance(e, FloodWaitError):
                        wait = min(e.seconds, 120)
                        self.log.emit(f"⏳ '{label}' FloodWait: {e.seconds}s → {wait}s bekleniyor...")
                        await asyncio.sleep(wait)
                    else:
                        err += 1
                        self.log.emit(f"❌ '{label}' → {target}: {e}")
                done += 1
                self.progress.emit(done, total)
                if not self._stop:
                    await asyncio.sleep(self.delay)
            try:
                await tg.disconnect()
            except Exception:
                pass
        self.log.emit(f"🏁 Tamamlandı — {ok} gönderildi, {err} hata.")
        self.finished_ok.emit(ok, err)

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run())
        except Exception as e:
            self.log.emit(f"❌ Hata: {e}")
            self.finished_ok.emit(0, 0)
        finally:
            try:
                loop.close()
            except Exception:
                pass


# ====================================================================== #
#  5) Toplu Kanal/Grup Katılımı
# ====================================================================== #
class JoinChannelsWorker(QThread):
    """Seçili hesaplarla verilen kanal/gruplara katılır (public + özel davet)."""
    log = Signal(str)
    progress = Signal(int, int)
    finished_ok = Signal(int, int)

    def __init__(self, db, accounts, links: List[str], delay: int = 5):
        super().__init__()
        self.db = db
        self.accounts = accounts
        self.links = links
        self.delay = max(0, int(delay))
        self._stop = False

    def stop(self):
        self._stop = True

    async def _run(self):
        total = len(self.accounts) * len(self.links)
        done = ok = err = 0
        for acc in self.accounts:
            if self._stop:
                break
            label = _acc_label(acc)
            tg = _make_client(self.db, acc)
            try:
                if not await tg.connect():
                    self.log.emit(f"⚠️ '{label}' oturumu geçersiz, atlanıyor.")
                    await tg.disconnect()
                    done += len(self.links)
                    self.progress.emit(done, total)
                    continue
            except Exception as e:
                self.log.emit(f"❌ '{label}' bağlanamadı: {e}")
                done += len(self.links)
                self.progress.emit(done, total)
                continue

            for link in self.links:
                if self._stop:
                    break
                try:
                    await tg.join_group(link)
                    ok += 1
                    self.log.emit(f"✅ '{label}' → {link}: katıldı")
                except Exception as e:
                    from telethon.errors import FloodWaitError
                    if isinstance(e, FloodWaitError):
                        self.log.emit(f"⏳ '{label}' FloodWait: {e.seconds}s bekleniyor...")
                        await asyncio.sleep(min(e.seconds, 60))
                    else:
                        err += 1
                        self.log.emit(f"❌ '{label}' → {link}: {e}")
                done += 1
                self.progress.emit(done, total)
                if self.delay and not self._stop:
                    await asyncio.sleep(self.delay)
            try:
                await tg.disconnect()
            except Exception:
                pass
        self.log.emit(f"🏁 Tamamlandı — {ok} katılım, {err} hata.")
        self.finished_ok.emit(ok, err)

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run())
        except Exception as e:
            self.log.emit(f"❌ Hata: {e}")
            self.finished_ok.emit(0, 0)
        finally:
            try:
                loop.close()
            except Exception:
                pass


# ====================================================================== #
#  6) Toplu Gruptan Çıkma
# ====================================================================== #
class LeaveChannelsWorker(QThread):
    """Seçili hesaplarla verilen kanal/gruplardan çıkar."""
    log = Signal(str)
    progress = Signal(int, int)
    finished_ok = Signal(int, int)

    def __init__(self, db, accounts, links: List[str], delay: int = 3):
        super().__init__()
        self.db = db
        self.accounts = accounts
        self.links = links
        self.delay = max(0, int(delay))
        self._stop = False

    def stop(self):
        self._stop = True

    async def _run(self):
        total = len(self.accounts) * len(self.links)
        done = ok = err = 0
        for acc in self.accounts:
            if self._stop:
                break
            label = _acc_label(acc)
            tg = _make_client(self.db, acc)
            try:
                if not await tg.connect():
                    self.log.emit(f"⚠️ '{label}' oturumu geçersiz, atlanıyor.")
                    await tg.disconnect()
                    done += len(self.links)
                    self.progress.emit(done, total)
                    continue
            except Exception as e:
                self.log.emit(f"❌ '{label}' bağlanamadı: {e}")
                done += len(self.links)
                self.progress.emit(done, total)
                continue

            for link in self.links:
                if self._stop:
                    break
                try:
                    success, msg = await tg.leave_group(link)
                    if success:
                        ok += 1
                        self.log.emit(f"✅ '{label}' → {link}: {msg}")
                    else:
                        err += 1
                        self.log.emit(f"⚠️ '{label}' → {link}: {msg}")
                except Exception as e:
                    err += 1
                    self.log.emit(f"❌ '{label}' → {link}: {e}")
                done += 1
                self.progress.emit(done, total)
                if self.delay and not self._stop:
                    await asyncio.sleep(self.delay)
            try:
                await tg.disconnect()
            except Exception:
                pass
        self.log.emit(f"🏁 Tamamlandı — {ok} çıkış, {err} hata.")
        self.finished_ok.emit(ok, err)

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run())
        except Exception as e:
            self.log.emit(f"❌ Hata: {e}")
            self.finished_ok.emit(0, 0)
        finally:
            try:
                loop.close()
            except Exception:
                pass


# ====================================================================== #
#  7) Toplu Profil Güncelleme
# ====================================================================== #
class ProfileUpdateWorker(QThread):
    """Seçili hesapların isim / soyisim / hakkında (bio) bilgisini günceller."""
    log = Signal(str)
    progress = Signal(int, int)
    finished_ok = Signal(int, int)

    def __init__(self, db, accounts, first_name: Optional[str], last_name: Optional[str],
                 about: Optional[str], photo_path: Optional[str] = None, delay: int = 3):
        super().__init__()
        self.db = db
        self.accounts = accounts
        self.first_name = first_name
        self.last_name = last_name
        self.about = about
        self.photo_path = photo_path
        self.delay = max(0, int(delay))
        self._stop = False

    def stop(self):
        self._stop = True

    async def _run(self):
        total = len(self.accounts)
        done = ok = err = 0
        for acc in self.accounts:
            if self._stop:
                break
            label = _acc_label(acc)
            tg = _make_client(self.db, acc)
            try:
                if not await tg.connect():
                    self.log.emit(f"⚠️ '{label}' oturumu geçersiz, atlanıyor.")
                    await tg.disconnect()
                    done += 1
                    self.progress.emit(done, total)
                    continue
                await tg.update_profile(
                    first_name=self.first_name,
                    last_name=self.last_name,
                    about=self.about,
                    photo_path=self.photo_path,
                )
                ok += 1
                self.log.emit(f"✅ '{label}': profil güncellendi")
            except Exception as e:
                from telethon.errors import FloodWaitError
                if isinstance(e, FloodWaitError):
                    self.log.emit(f"⏳ '{label}' FloodWait: {e.seconds}s bekleniyor...")
                    await asyncio.sleep(min(e.seconds, 60))
                else:
                    err += 1
                    self.log.emit(f"❌ '{label}': {e}")
            finally:
                try:
                    await tg.disconnect()
                except Exception:
                    pass
            done += 1
            self.progress.emit(done, total)
            if self.delay and not self._stop:
                await asyncio.sleep(self.delay)
        self.log.emit(f"🏁 Tamamlandı — {ok} güncellendi, {err} hata.")
        self.finished_ok.emit(ok, err)

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run())
        except Exception as e:
            self.log.emit(f"❌ Hata: {e}")
            self.finished_ok.emit(0, 0)
        finally:
            try:
                loop.close()
            except Exception:
                pass
