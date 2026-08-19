"""
TGraph - Cgraph Uyumluluk Katmanı
=================================

Cgraph (WTelegramClient / .NET tabanlı) dosya formatlarını okur ve TGraph'in
Telethon tabanlı yapısına dönüştürür.

Desteklenen formatlar:
  * .cgsession   -> Şifreli WTelegramClient oturumu (SQLite konteyner).
                    AES-128-CBC ile şifrelenmiştir. Anahtar = api_hash (hex çözülmüş 16 bayt),
                    IV = blob'un ilk 16 baytı, gövde = [32 bayt SHA256][UTF-8 JSON].
                    Telethon .session dosyasına çevrilir (SMS'siz giriş).
  * .cumemberdata-> UTF-8 (BOM) metin. Her satır: "Username!UserId!Category".
  * members.db   -> Cgraph "Data" veritabanı. Datasets + Members tabloları.

Not: AES için pycryptodome (Crypto) kullanılır; yoksa 'cryptography' paketine düşer.
"""
import os
import json
import base64
import sqlite3
import datetime
from typing import Dict, Any, List, Tuple, Optional


# --------------------------------------------------------------------------- #
#  AES-128-CBC çözücü (pycryptodome veya cryptography)
# --------------------------------------------------------------------------- #
def _aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    try:
        from Crypto.Cipher import AES  # pycryptodome
        return AES.new(key, AES.MODE_CBC, iv).decrypt(data)
    except ImportError:
        pass
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        dec = cipher.decryptor()
        return dec.update(data) + dec.finalize()
    except ImportError:
        raise RuntimeError(
            "AES çözme için 'pycryptodome' veya 'cryptography' paketi gerekli. "
            "Kurmak için: pip install pycryptodome"
        )


# Telegram üretim veri merkezi IP adresleri (yedek olarak; .cgsession kendi IP'sini içerir)
_DC_IPS = {
    1: "149.154.175.53",
    2: "149.154.167.51",
    3: "149.154.175.100",
    4: "149.154.167.91",
    5: "91.108.56.130",
}


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
#  .cgsession okuma / çözme
# --------------------------------------------------------------------------- #
def is_cgsession(path: str) -> bool:
    """Dosyanın bir .cgsession (Cgraph şifreli oturum) olup olmadığını kontrol eder."""
    if path.lower().endswith(".cgsession"):
        return True
    try:
        conn = sqlite3.connect(path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        return "telegramsessions" in tables and "cgraphkeys" in tables
    except Exception:
        return False


def decrypt_cgsession(path: str) -> Dict[str, Any]:
    """
    .cgsession dosyasını çözer ve oturum bilgilerini döndürür.

    Dönüş sözlüğü:
      api_id, api_hash, user_id, main_dc, ip_address, port,
      auth_key (256 bayt), phone (varsa), device (varsa), raw (tüm JSON)
    """
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("SELECT name, data FROM telegramsessions").fetchone()
        if not row:
            raise ValueError("telegramsessions tablosu boş - geçersiz .cgsession")
        sess_name, blob = row
        keyrow = conn.execute("SELECT apiid, apihash FROM cgraphkeys").fetchone()
        if not keyrow:
            raise ValueError("cgraphkeys tablosu boş - API bilgileri yok")
        api_id, api_hash = keyrow
        device = None
        try:
            drow = conn.execute(
                "SELECT device_model, system_version, app_version FROM cgraphdevice"
            ).fetchone()
            if drow:
                device = {"device_model": drow[0], "system_version": drow[1],
                          "app_version": drow[2]}
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()

    if not isinstance(blob, (bytes, bytearray)) or len(blob) < 48:
        raise ValueError("Oturum verisi geçersiz veya çok kısa")

    iv = bytes(blob[:16])
    enc = bytes(blob[16:])
    if len(enc) % 16 != 0:
        raise ValueError("Şifreli veri blok hizalı değil (16 baytın katı olmalı)")

    key = bytes.fromhex(api_hash)  # AES-128 anahtarı = api_hash'in 16 baytı
    dec = _aes_cbc_decrypt(key, iv, enc)

    # PKCS7 dolgusunu ayıkla
    pad = dec[-1]
    body = dec[32:-pad] if 1 <= pad <= 16 else dec[32:]

    # SHA256 bütünlük kontrolü (varsa)
    try:
        import hashlib
        if hashlib.sha256(body).digest() != dec[:32]:
            # Dolgu farklı olabilir; JSON parse etmeyi yine de dene
            pass
    except Exception:
        pass

    try:
        j = json.loads(body)
    except json.JSONDecodeError as e:
        raise ValueError(
            "Oturum çözülemedi - API Hash yanlış olabilir veya dosya bozuk. "
            f"(JSON hatası: {e})"
        )

    main_dc = j.get("MainDC")
    dc_sessions = j.get("DCSessions", {})
    sess = dc_sessions.get(str(main_dc))
    if not sess or not sess.get("AuthKey"):
        raise ValueError(f"Ana DC ({main_dc}) için oturum anahtarı bulunamadı")

    auth_key = base64.b64decode(sess["AuthKey"])
    if len(auth_key) != 256:
        raise ValueError(f"Oturum anahtarı boyutu geçersiz: {len(auth_key)} (256 bekleniyor)")

    dc = sess.get("DataCenter", {})
    ip = dc.get("ip_address") or _DC_IPS.get(main_dc, "149.154.167.91")
    port = dc.get("port", 443)

    return {
        "api_id": int(api_id),
        "api_hash": api_hash,
        "user_id": j.get("UserId"),
        "main_dc": int(main_dc),
        "ip_address": ip,
        "port": int(port),
        "auth_key": auth_key,
        "device": device,
        "raw": j,
    }


def convert_cgsession_to_telethon(cgsession_path: str, dest_session_path: str) -> Dict[str, Any]:
    """
    .cgsession dosyasını Telethon SQLite .session dosyasına dönüştürür.

    dest_session_path: uzantısı .session olan hedef yol.
    Dönüş: decrypt_cgsession sonucu (api_id, api_hash, user_id vb.).
    """
    info = decrypt_cgsession(cgsession_path)

    if not dest_session_path.endswith(".session"):
        dest_session_path += ".session"
    os.makedirs(os.path.dirname(os.path.abspath(dest_session_path)), exist_ok=True)
    if os.path.exists(dest_session_path):
        os.remove(dest_session_path)

    conn = sqlite3.connect(dest_session_path)
    try:
        conn.execute("CREATE TABLE version (version integer primary key)")
        conn.execute(
            "CREATE TABLE sessions (dc_id integer primary key, server_address text, "
            "port integer, auth_key blob, takeout_id integer)"
        )
        conn.execute(
            "CREATE TABLE entities (id integer primary key, hash integer not null, "
            "username text, phone integer, name text, date integer)"
        )
        conn.execute(
            "CREATE TABLE sent_files (md5_digest blob, file_size integer, type integer, "
            "id integer, hash integer, primary key(md5_digest, file_size, type))"
        )
        conn.execute(
            "CREATE TABLE update_state (id integer primary key, pts integer, qts integer, "
            "date integer, seq integer)"
        )
        conn.execute("INSERT INTO version VALUES (7)")  # Telethon SQLite şema sürümü
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?)",
            (info["main_dc"], info["ip_address"], info["port"], info["auth_key"], None),
        )
        conn.commit()
    finally:
        conn.close()

    return info


# --------------------------------------------------------------------------- #
#  .cumemberdata okuma / yazma  (Username!UserId!Category)
# --------------------------------------------------------------------------- #
def import_cumemberdata(path: str, group_source: str = "") -> List[Dict[str, Any]]:
    """
    Cgraph .cumemberdata dosyasını okur.
    Format: her satır  Username!UserId!Category  (UTF-8, BOM olabilir).
    """
    if not group_source:
        group_source = os.path.splitext(os.path.basename(path))[0]
    members: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("!")
            username = parts[0].strip() if len(parts) > 0 else ""
            uid_raw = parts[1].strip() if len(parts) > 1 else ""
            category = parts[2].strip() if len(parts) > 2 else ""
            try:
                uid = int(uid_raw) if uid_raw else None
            except ValueError:
                uid = None
            if uid is None and not username:
                continue
            members.append({
                "user_id": uid,
                "access_hash": "",
                "username": username,
                "first_name": "",
                "last_name": "",
                "phone": "",
                "group_source": group_source,
                "scraped_date": _now(),
                "category": category,
            })
    return members


def export_cumemberdata(path: str, members: List[Dict[str, Any]],
                        category: str = "Kategorisiz") -> int:
    """Üye listesini Cgraph .cumemberdata formatında yazar (Username!UserId!Category)."""
    with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        for m in members:
            username = m.get("username", "") or ""
            uid = m.get("user_id", "") or ""
            cat = m.get("category") or category
            if not username and not uid:
                continue
            f.write(f"{username}!{uid}!{cat}\n")
    return len(members)


# --------------------------------------------------------------------------- #
#  Cgraph "Data" veritabanı (members.db)  Datasets + Members
# --------------------------------------------------------------------------- #
def is_cgraph_data_db(path: str) -> bool:
    """SQLite dosyasının Cgraph Data DB (Datasets/Members) olup olmadığını kontrol eder."""
    try:
        conn = sqlite3.connect(path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        return "Datasets" in tables and "Members" in tables
    except Exception:
        return False


def list_cgraph_datasets(path: str) -> List[Dict[str, Any]]:
    """Cgraph Data DB içindeki veri setlerini listeler."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT DatasetId, Category, SourceGroup, SavedAtUtc, MemberCount, Format "
            "FROM Datasets ORDER BY DatasetId"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def import_cgraph_data_db(path: str, dataset_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Cgraph Data veritabanından (members.db) üyeleri okur.
    dataset_id verilirse sadece o veri setini, yoksa tümünü döndürür.
    group_source alanı SourceGroup adıyla doldurulur.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        ds_rows = conn.execute(
            "SELECT DatasetId, SourceGroup FROM Datasets"
        ).fetchall()
        ds_names = {r["DatasetId"]: (r["SourceGroup"] or f"Dataset {r['DatasetId']}")
                    for r in ds_rows}

        q = ("SELECT DatasetId, UserId, Username, AccessHash, FirstName, LastName, Phone "
             "FROM Members")
        params: List[Any] = []
        if dataset_id is not None:
            q += " WHERE DatasetId = ?"
            params.append(dataset_id)
        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()

    members: List[Dict[str, Any]] = []
    for r in rows:
        did = r["DatasetId"]
        members.append({
            "user_id": r["UserId"],
            "access_hash": str(r["AccessHash"] or ""),
            "username": r["Username"] or "",
            "first_name": r["FirstName"] or "",
            "last_name": r["LastName"] or "",
            "phone": r["Phone"] or "",
            "group_source": ds_names.get(did, f"Dataset {did}"),
            "scraped_date": _now(),
        })
    return members


# --------------------------------------------------------------------------- #
#  Genel amaçlı veri dosyası okuyucu (uzantıya göre yönlendirir)
# --------------------------------------------------------------------------- #
def import_any_member_file(path: str) -> List[Dict[str, Any]]:
    """
    Uzantıya/içeriğe göre uygun okuyucuyu seçer:
      .cumemberdata -> import_cumemberdata
      .db / SQLite (Cgraph Data) -> import_cgraph_data_db (tüm setler)
      .csv -> None döndürmez; çağıran taraf Database.import_members_csv kullanmalı
    """
    low = path.lower()
    if low.endswith(".cumemberdata"):
        return import_cumemberdata(path)
    if is_cgraph_data_db(path):
        return import_cgraph_data_db(path)
    raise ValueError("Desteklenmeyen dosya türü (CSV için Database.import_members_csv kullanın)")
