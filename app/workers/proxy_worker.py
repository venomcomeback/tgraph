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
import json
import time
import urllib.request
from typing import List, Dict, Any, Set

from PySide6.QtCore import QThread, Signal


# ProxyScrape v3 — ülke filtreli (yalnızca Türkiye / TR) kaynaklar.
# Bu kaynaklardan gelen proxy'ler zaten TR olduğundan GeoIP doğrulaması gerekmez.
PROXYSCRAPE_TR: Dict[str, str] = {
    "socks5": ("https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies"
               "&protocol=socks5&country=tr&proxy_format=ipport&format=text"),
    "socks4": ("https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies"
               "&protocol=socks4&country=tr&proxy_format=ipport&format=text"),
    "http": ("https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies"
             "&protocol=http&country=tr&proxy_format=ipport&format=text"),
}

# Geonode — ülke filtreli yedek kaynak (JSON döner). country=TR
GEONODE_TR: Dict[str, str] = {
    "socks5": ("https://proxylist.geonode.com/api/proxy-list?limit=500&page=1"
               "&sort_by=lastChecked&sort_type=desc&country=TR&protocols=socks5"),
    "socks4": ("https://proxylist.geonode.com/api/proxy-list?limit=500&page=1"
               "&sort_by=lastChecked&sort_type=desc&country=TR&protocols=socks4"),
    "http": ("https://proxylist.geonode.com/api/proxy-list?limit=500&page=1"
             "&sort_by=lastChecked&sort_type=desc&country=TR&protocols=http,https"),
}

# Topluluk tarafından bakımı yapılan ücretsiz genel proxy kaynakları (ham metin: host:port)
# Bu kaynaklar ülke filtresiz olduğundan indirilen IP'ler GeoIP ile TR olup olmadığı doğrulanır.
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


# ip-api.com toplu (batch) GeoIP uç noktası: tek istekte en fazla 100 IP,
# ücretsiz limit ~15 istek/dakika. Batch'ler arasında beklenerek limite uyulur.
_GEO_BATCH_URL = "http://ip-api.com/batch?fields=countryCode,query,status"
_GEO_BATCH_SIZE = 100
_GEO_BATCH_SLEEP = 5.0   # saniye — 12 istek/dk (15 limitinin güvenli altında)
# GeoIP ile doğrulanacak azami IP sayısı (askıda kalmayı önlemek için üst sınır)
GEO_MAX_CHECK = 1000


def _geo_batch_tr(ips: List[str]) -> Set[str]:
    """Verilen IP listesini ip-api.com batch ile sorgular; TR olanların kümesini döndürür."""
    tr: Set[str] = set()
    req = urllib.request.Request(
        _GEO_BATCH_URL,
        data=json.dumps(ips).encode("utf-8"),
        headers={"User-Agent": _UA, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    arr = json.loads(raw)
    for item in arr:
        if isinstance(item, dict) and item.get("status") == "success" \
                and (item.get("countryCode") or "").upper() == "TR":
            q = item.get("query")
            if q:
                tr.add(q)
    return tr


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
        """Yalnızca Türkiye (TR) proxy'lerini toplar.

        1) Ülke filtreli kaynaklar (ProxyScrape + Geonode) doğrudan TR verir.
        2) Ülke filtresiz genel kaynaklardan (GitHub) aday IP'ler toplanır ve
           ip-api.com toplu GeoIP sorgusuyla yalnızca TR olanlar tutulur.
        Tümünde (tip, host, port) üçlüsüne göre tekilleştirme yapılır.
        """
        seen = set()
        collected: List[Dict[str, Any]] = []

        # ---- 1) Ülke filtreli kaynaklar (doğrudan TR) ----
        self.log.emit("🇹🇷 Türkiye (TR) proxy'leri toplanıyor...")
        for ptype in self.proxy_types:
            if self._stop:
                return collected
            # ProxyScrape (ham metin)
            ps_url = PROXYSCRAPE_TR.get(ptype)
            if ps_url:
                try:
                    self.log.emit(f"⬇️ TR kaynağı (ProxyScrape): {ptype}")
                    text = _download(ps_url)
                    added = self._ingest_text(text, ptype, seen, collected)
                    self.log.emit(f"   ↳ {added} TR proxy")
                    if len(collected) >= self.max_count:
                        return collected
                except Exception as e:
                    self.log.emit(f"⚠️ ProxyScrape TR atlandı ({ptype}): {e}")
            # Geonode (JSON)
            gn_url = GEONODE_TR.get(ptype)
            if gn_url:
                try:
                    self.log.emit(f"⬇️ TR kaynağı (Geonode): {ptype}")
                    added = self._ingest_geonode(gn_url, ptype, seen, collected)
                    self.log.emit(f"   ↳ {added} TR proxy")
                    if len(collected) >= self.max_count:
                        return collected
                except Exception as e:
                    self.log.emit(f"⚠️ Geonode TR atlandı ({ptype}): {e}")

        if len(collected) >= self.max_count:
            return collected

        # ---- 2) Genel kaynaklar + GeoIP TR doğrulaması ----
        # Aday (host, port, ptype) topla, sonra host'ları GeoIP ile TR filtrele.
        candidates: List[Dict[str, Any]] = []
        cand_seen = set()
        for ptype in self.proxy_types:
            for url in PROXY_SOURCES.get(ptype, []):
                if self._stop:
                    break
                try:
                    self.log.emit(f"⬇️ Genel kaynak: {url}")
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
                    if key in seen or key in cand_seen:
                        continue
                    cand_seen.add(key)
                    candidates.append({"proxy_type": ptype, "host": hp[0], "port": hp[1]})
                    added += 1
                self.log.emit(f"   ↳ {added} aday")

        if not candidates or self._stop:
            return collected

        # Benzersiz host'ları GeoIP ile TR filtrele (batch, throttle).
        unique_hosts = list({c["host"] for c in candidates})
        if len(unique_hosts) > GEO_MAX_CHECK:
            self.log.emit(
                f"ℹ️ {len(unique_hosts)} aday host bulundu, GeoIP için ilk {GEO_MAX_CHECK} tanesi doğrulanacak."
            )
            unique_hosts = unique_hosts[:GEO_MAX_CHECK]
        self.log.emit(f"🌍 {len(unique_hosts)} host GeoIP ile Türkiye kontrolü yapılıyor...")
        tr_hosts: Set[str] = set()
        total_batches = (len(unique_hosts) + _GEO_BATCH_SIZE - 1) // _GEO_BATCH_SIZE
        for bi in range(total_batches):
            if self._stop:
                break
            chunk = unique_hosts[bi * _GEO_BATCH_SIZE:(bi + 1) * _GEO_BATCH_SIZE]
            try:
                tr_hosts |= _geo_batch_tr(chunk)
            except Exception as e:
                self.log.emit(f"⚠️ GeoIP sorgusu başarısız (batch {bi + 1}): {e}")
            self.log.emit(
                f"   ↳ GeoIP {bi + 1}/{total_batches} — şu ana kadar {len(tr_hosts)} TR host"
            )
            if bi < total_batches - 1 and not self._stop:
                time.sleep(_GEO_BATCH_SLEEP)  # ip-api.com dakika limitine uy

        # TR host'lara ait adayları ekle
        tr_added = 0
        for c in candidates:
            if c["host"] not in tr_hosts:
                continue
            key = (c["proxy_type"], c["host"], c["port"])
            if key in seen:
                continue
            seen.add(key)
            collected.append(c)
            tr_added += 1
            if len(collected) >= self.max_count:
                break
        self.log.emit(f"🇹🇷 Genel kaynaklardan {tr_added} doğrulanmış TR proxy eklendi.")
        return collected

    def _ingest_text(self, text: str, ptype: str, seen: set,
                     collected: List[Dict[str, Any]]) -> int:
        """Ham 'host:port' metnini ayrıştırıp (dedup) collected'a ekler."""
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
                break
        return added

    def _ingest_geonode(self, url: str, ptype: str, seen: set,
                        collected: List[Dict[str, Any]]) -> int:
        """Geonode JSON yanıtını ayrıştırıp (dedup) collected'a ekler."""
        raw = _download(url)
        data = json.loads(raw)
        rows = data.get("data", []) if isinstance(data, dict) else []
        added = 0
        for r in rows:
            host = (r.get("ip") or "").strip()
            port_raw = str(r.get("port") or "").strip()
            if not host or not port_raw.isdigit():
                continue
            port = int(port_raw)
            if not (0 < port < 65536):
                continue
            key = (ptype, host, port)
            if key in seen:
                continue
            seen.add(key)
            collected.append({"proxy_type": ptype, "host": host, "port": port})
            added += 1
            if len(collected) >= self.max_count:
                break
        return added

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
            self.log.emit(f"📦 Toplam {downloaded} benzersiz Türkiye (TR) proxy'si toplandı.")

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
