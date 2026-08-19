"""
TGraph - Toplu İşlem Yardımcıları
=================================

TXT tabanlı kimlik bilgisi (numara + API) ayrıştırma. Hem "Toplu Session Yükle"
hem de "TXT'den Numaralarla Giriş" özellikleri tarafından kullanılır.

Desteklenen satır biçimleri (satır başına, ayraç otomatik algılanır):
    * telefon
    * telefon<ayraç>api_id<ayraç>api_hash
    * api_id<ayraç>api_hash<ayraç>telefon

Ayraçlar: ':'  '|'  ','  ';'  boşluk / sekme
Boş satırlar ve '#' ile başlayan satırlar yok sayılır.
"""
import os
import re
from typing import Dict, Any, List, Optional

# 32 karakterlik onaltılık (API Hash)
_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")
# Satır ayırıcılar
_SPLIT = re.compile(r"[\s:|,;]+")


def _digits(token: str) -> str:
    """Baştaki + işaretini atıp yalnızca rakamları döndürür."""
    return token.lstrip("+").strip()


def _is_numeric(token: str) -> bool:
    d = _digits(token)
    return bool(d) and d.isdigit()


def normalize_phone(phone: str) -> str:
    """Telefonu +<rakamlar> biçimine getirir."""
    if not phone:
        return ""
    p = phone.strip()
    d = _digits(p)
    if not d:
        return p
    return "+" + d


def phone_key(phone: str) -> str:
    """Eşleştirme için telefonun sadece rakamlarını verir (+ ve boşluk olmadan)."""
    return _digits(phone or "")


def parse_credentials_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Tek bir satırı ayrıştırır. Geçerliyse {phone, api_id, api_hash} döndürür
    (api_id / api_hash bulunamazsa None olabilir), aksi halde None.
    """
    if line is None:
        return None
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    tokens = [t for t in _SPLIT.split(line) if t]
    if not tokens:
        return None

    api_hash: Optional[str] = None
    others: List[str] = []
    for t in tokens:
        if api_hash is None and _HEX32.match(t):
            api_hash = t
        else:
            others.append(t)

    numeric = [t for t in others if _is_numeric(t)]

    phone: Optional[str] = None
    api_id: Optional[str] = None

    if len(numeric) == 1:
        phone = numeric[0]
    elif len(numeric) >= 2:
        # Artı işaretli olan telefon kabul edilir; yoksa en uzun rakam dizisi telefon,
        # en kısa saf tamsayı ise api_id olur.
        plus = [t for t in numeric if t.strip().startswith("+")]
        if plus:
            phone = plus[0]
            remaining = [t for t in numeric if t is not phone]
            if remaining:
                api_id = min(remaining, key=lambda x: len(_digits(x)))
        else:
            srt = sorted(numeric, key=lambda x: len(_digits(x)))
            api_id = srt[0]
            phone = srt[-1]

    if not phone:
        return None

    return {
        "phone": normalize_phone(phone),
        "api_id": _digits(api_id) if api_id else None,
        "api_hash": api_hash,
    }


def parse_credentials_txt(path: str) -> List[Dict[str, Any]]:
    """
    Bir .txt dosyasını satır satır ayrıştırır.
    Dönüş: [{phone, api_id, api_hash}, ...]  (yalnızca geçerli satırlar)
    Aynı telefon birden fazla geçerse ilki korunur.
    """
    results: List[Dict[str, Any]] = []
    seen = set()
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        for raw in f:
            rec = parse_credentials_line(raw)
            if not rec:
                continue
            key = phone_key(rec["phone"])
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            results.append(rec)
    return results


def build_credentials_index(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Telefon anahtarına (sadece rakamlar) göre kimlik bilgisi haritası."""
    idx: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        key = phone_key(rec.get("phone", ""))
        if key:
            idx[key] = rec
    return idx


def load_folder_credentials(folder: str) -> Dict[str, Dict[str, Any]]:
    """
    Bir klasördeki tüm .txt dosyalarından kimlik bilgilerini toplayıp
    telefon anahtarına göre indeksler (Feature 1'de düz .session eşlemesi için).
    """
    index: Dict[str, Dict[str, Any]] = {}
    try:
        for name in os.listdir(folder):
            if name.lower().endswith(".txt"):
                full = os.path.join(folder, name)
                try:
                    for rec in parse_credentials_txt(full):
                        key = phone_key(rec.get("phone", ""))
                        if key and key not in index:
                            index[key] = rec
                except Exception:
                    continue
    except Exception:
        pass
    return index
