"""
TGraph - Uygulama Ayarları ve Sabitler
"""
import os

APP_NAME = "TGraph"
APP_VERSION = "1.0.0"
APP_TITLE = "TGraph - Telegram Grup Yöneticisi"

# ----------------------------------------------------------------------------
# Dizin yolları
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "tgraph.db")

for _d in (SESSIONS_DIR, DATA_DIR):
    os.makedirs(_d, exist_ok=True)

# ----------------------------------------------------------------------------
# Renk paleti (Cgraph benzeri karanlık tema)
# ----------------------------------------------------------------------------
COLORS = {
    "bg": "#1a1a2e",
    "panel": "#16213e",
    "panel2": "#0f3460",
    "accent": "#e94560",
    "accent_dark": "#c73652",
    "text": "#eaeaea",
    "text_secondary": "#8892b0",
    "input_bg": "#0d1b2a",
    "hover": "#1a4080",
    "success": "#00d26a",
    "error": "#ff4757",
    "warning": "#ffa502",
}

# ----------------------------------------------------------------------------
# Varsayılan ayarlar
# ----------------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "language": "tr",
    "auto_connect": "0",
    "daily_add_limit": "40",
    "hourly_add_limit": "20",
    "min_delay": "30",
    "max_delay": "60",
    "big_break_every": "10",
    "big_break_minutes": "15",
    "sessions_dir": SESSIONS_DIR,
}

# Son görülme filtre seçenekleri (etiket -> gün sayısı, None = hepsi)
LAST_SEEN_OPTIONS = {
    "Hepsi": None,
    "1 Gün": 1,
    "1 Hafta": 7,
    "1 Ay": 30,
    "6 Ay": 180,
}

# Hesap durumları
STATUS_OK = "ok"
STATUS_SPAM = "spam"
STATUS_BANNED = "banned"
STATUS_UNKNOWN = "unknown"

STATUS_LABELS = {
    STATUS_OK: "Aktif",
    STATUS_SPAM: "Spam",
    STATUS_BANNED: "Yasaklı",
    STATUS_UNKNOWN: "Bilinmiyor",
}
