# TGraph — Telegram Grup Yöneticisi

Cgraph tarzı, karanlık temalı, tamamen Türkçe bir Telegram üye yönetim masaüstü uygulaması.
**Python + PySide6 + Telethon** ile geliştirilmiştir.

## Özellikler

- **👤 Hesap Yönetimi** — Çoklu Telegram hesabı (API ID/Hash + telefon ile OTP/2FA giriş), `.session` dosyası içe aktarma (Cgraph uyumlu), bağlan/kes.
- **🔍 Üye Tarama** — Hedef gruptan üye çekme; bot hariç tutma, telefonu olanlar, son görülme (1 gün/hafta/ay/6 ay) ve dil filtreleri; veritabanına kaydetme + CSV dışa aktarma.
- **➕ Üye Ekleme** — Veritabanı / CSV / direkt grup tarama kaynağından hedef gruba ekleme; çoklu hesap rotasyonu, min-max bekleme, büyük mola, günlük limit, FloodWait yönetimi, canlı log ve hesap durum tablosu.
- **🌐 Proxy Yönetimi** — SOCKS5/HTTP proxy ekleme, `proxy.txt`'den toplu yükleme, bağlantı testi.
- **🛡️ Spam Testi** — Seçili hesapları `@SpamBot` ile test etme (Aktif/Spam/Yasaklı).
- **⚙️ Ayarlar** — Dil, ekleme limitleri, gecikme ayarları, session klasörü, DB yedekleme.

## Kurulum

```bash
pip install -r requirements.txt
python main.py
```

## Windows EXE Derleme

```bat
build.bat
```
Çıktı: `dist\TGraph.exe`

## Cgraph Uyumluluğu

- **Session dosyaları:** Telethon `.session` formatı (Cgraph ile aynı) — `sessions/` klasörüne kopyalanır.
- **CSV formatı:** `username,user_id,access_hash,first_name,last_name,phone`

## Dizin Yapısı

- `sessions/` — Telegram session dosyaları
- `data/tgraph.db` — SQLite veritabanı (hesaplar, üyeler, gruplar, proxyler, ayarlar)

## Notlar

- API ID/Hash almak için: https://my.telegram.org
- Telegram limitlerini aşmamak için makul gecikme ve günlük limit değerleri kullanın.
