"""
TGraph - Proxy Worker'ları (QThread + asyncio)
==============================================

* ProxyFetchWorker: İnternetteki ücretsiz genel proxy listelerini indirir,
  ayrıştırır, isteğe bağlı olarak TCP-connect ile test eder ve çalışanları
  (veya test kapalıysa hepsini) veritabanına kaydeder.
* ProxyBulkTestWorker: Kayıtlı tüm proxy'leri asyncio.open_connection ile
  test eder, her sonucu canlı yayınlar.
"""
import asyncio
import urllib.request
from typing import List, Dict, Any

from PySide6.QtCore import QThread, Signal


# Topluluk tarafından bakımı yapılan ücretsiz genel proxy kaynakları (ham metin: host:port)
PROXY_SOURCES: Dict[str, List[str]] = {
    "socks5": [
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
        "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    ],
    "socks4": [
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt",
    ],
    "http": [
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    ],
}

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# Test edilecek azami proxy sayısı (askıda kalmayı önlemek için)
MAX_TEST = 500


def _parse_host_port_line(line: str):
    """'host:port' (bazen 'type://host:port') satırını (host, port) olarak ayrıştırır."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    # şema ön ekini at
    if "://" in line:
        line = line.split("://", 1)[1]
    # olası kullanıcı bilgisi at
    if "@" in line:
        line = line.split("@", 1)[1]
    parts = line.split(":")
    if len(parts) < 2:
        return None
    host = parts[0].strip()
    port_raw = parts[1].strip()
    if not host or not port_raw.isdigit():
        return None
    port = int(port_raw)
    if not (0 < port < 65536):
        return None
    if "." not in host:
        return None
    return host, port


def _download(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return data.decode("latin-1", errors="ignore")


class ProxyFetchWorker(QThread):
    """Ücretsiz proxy indir + (isteğe bağlı) test + kaydet."""
    log = Signal(str)
    progress = Signal(int, int, int)      # tested, total, working
    finished_summary = Signal(int, int, int)  # downloaded, tested, saved

    def __init__(self, db, proxy_types: List[str], max_count: int = 200,
                 do_test: bool = True):
        super().__init__()
        self.db = db
        self.proxy_types = proxy_types
        self.max_count = max_count
        self.do_test = do_test
        self._stop = False

    def stop(self):
        self._stop = True

    # ------------------------------------------------------------------ #
    def _fetch_all(self) -> List[Dict[str, Any]]:
        """Seçilen tiplerdeki tüm kaynaklardan proxy'leri indirir (dedup)."""
        seen = set()
        collected: List[Dict[str, Any]] = []
        for ptype in self.proxy_types:
            sources = PROXY_SOURCES.get(ptype, [])
            for url in sources:
                if self._stop:
                    return collected
                try:
                    self.log.emit(f"⬇️ İndiriliyor: {url}")
                    text = _download(url)
                except Exception as e:
                    self.log.emit(f"⚠️ Kaynak atlandı ({url}): {e}")
                    continue
                added = 0
                for line in text.splitlines():
                    hp = _parse_host_port_line(line)
                    if not hp:
                        continue
                    key = (ptype, hp[0], hp[1])
                    if key in seen:
                        continue
                    seen.add(key)
                    collected.append({"proxy_type": ptype, "host": hp[0], "port": hp[1]})
                    added += 1
                    if len(collected) >= self.max_count:
                        self.log.emit(f"   ↳ {added} yeni proxy (üst sınıra ulaşıldı)")
                        return collected
                self.log.emit(f"   ↳ {added} yeni proxy")
        return collected

    async def _test_batch(self, proxies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Bounded-concurrency TCP-connect testi. Çalışanları döndürür."""
        working: List[Dict[str, Any]] = []
        sem = asyncio.Semaphore(50)
        total = len(proxies)
        counter = {"done": 0, "ok": 0}

        async def _test_one(p):
            if self._stop:
                return
            async with sem:
                if self._stop:
                    return
                ok = False
                try:
                    fut = asyncio.open_connection(p["host"], p["port"])
                    _, w = await asyncio.wait_for(fut, timeout=5)
                    w.close()
                    try:
                        await w.wait_closed()
                    except Exception:
                        pass
                    ok = True
                except Exception:
                    ok = False
                counter["done"] += 1
                if ok:
                    counter["ok"] += 1
                    working.append(p)
                if counter["done"] % 10 == 0 or counter["done"] == total:
                    self.progress.emit(counter["done"], total, counter["ok"])

        await asyncio.gather(*[_test_one(p) for p in proxies])
        return working

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        downloaded = tested = saved = 0
        try:
            fetched = self._fetch_all()
            downloaded = len(fetched)
            self.log.emit(f"📦 Toplam {downloaded} benzersiz proxy indirildi.")

            if self._stop:
                self.log.emit("⏹️ İşlem durduruldu.")
                self.finished_summary.emit(downloaded, tested, saved)
                return

            if self.do_test and fetched:
                to_test = fetched[:MAX_TEST]
                tested = len(to_test)
                self.log.emit(f"🧪 {tested} proxy test ediliyor (aynı anda 50)...")
                working = loop.run_until_complete(self._test_batch(to_test))
                self.log.emit(f"✅ {len(working)} çalışan proxy bulundu.")
                to_save = working
            else:
                to_save = fetched
                if not self.do_test:
                    self.log.emit("ℹ️ Test atlandı, tüm indirilenler kaydedilecek.")

            for p in to_save:
                if self._stop:
                    break
                try:
                    rid = self.db.add_proxy_unique(
                        p["proxy_type"], p["host"], p["port"], "", ""
                    )
                    if rid is not None:
                        saved += 1
                except Exception as e:
                    self.log.emit(f"⚠️ Kaydedilemedi {p['host']}:{p['port']}: {e}")

            self.log.emit(
                f"🏁 Tamamlandı — {downloaded} indirildi, {tested} test edildi, "
                f"{saved} kaydedildi."
            )
            self.finished_summary.emit(downloaded, tested, saved)
        except Exception as e:
            self.log.emit(f"❌ Hata: {e}")
            self.finished_summary.emit(downloaded, tested, saved)
        finally:
            try:
                loop.close()
            except Exception:
                pass


class ProxyBulkTestWorker(QThread):
    """Kayıtlı tüm proxy'leri asyncio TCP-connect ile test eder."""
    result = Signal(int, bool)            # proxy_id, working
    progress = Signal(int, int, int)      # tested, total, working
    log = Signal(str)
    finished_ok = Signal(int, int)        # tested, working

    def __init__(self, proxies: List[Dict[str, Any]]):
        super().__init__()
        self.proxies = proxies
        self._stop = False

    def stop(self):
        self._stop = True

    async def _run_tests(self):
        sem = asyncio.Semaphore(50)
        total = len(self.proxies)
        counter = {"done": 0, "ok": 0}

        async def _test_one(p):
            if self._stop:
                return
            async with sem:
                if self._stop:
                    return
                ok = False
                try:
                    fut = asyncio.open_connection(p["host"], int(p["port"]))
                    _, w = await asyncio.wait_for(fut, timeout=5)
                    w.close()
                    try:
                        await w.wait_closed()
                    except Exception:
                        pass
                    ok = True
                except Exception:
                    ok = False
                counter["done"] += 1
                if ok:
                    counter["ok"] += 1
                self.result.emit(p["id"], ok)
                self.progress.emit(counter["done"], total, counter["ok"])

        await asyncio.gather(*[_test_one(p) for p in self.proxies])
        return counter

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            self.log.emit(f"🧪 {len(self.proxies)} proxy test ediliyor...")
            counter = loop.run_until_complete(self._run_tests())
            self.log.emit(
                f"🏁 Test bitti — {counter['done']} test edildi, {counter['ok']} çalışıyor."
            )
            self.finished_ok.emit(counter["done"], counter["ok"])
        except Exception as e:
            self.log.emit(f"❌ Hata: {e}")
            self.finished_ok.emit(0, 0)
        finally:
            try:
                loop.close()
            except Exception:
                pass
