"""
TGraph - Ana Pencere + Sidebar Navigasyon
"""
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QStackedWidget, QFrame, QStatusBar, QButtonGroup,
)
from PySide6.QtCore import Qt

from ..database import Database
from ..config import APP_TITLE, APP_VERSION, COLORS
from .accounts_page import AccountsPage
from .scraper_page import ScraperPage
from .adder_page import AdderPage
from .proxy_page import ProxyPage
from .spamtest_page import SpamTestPage
from .settings_page import SettingsPage


class MainWindow(QMainWindow):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.setWindowTitle(APP_TITLE)
        self.resize(1200, 750)
        self.setMinimumSize(900, 600)
        self._build()

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------------- Sidebar ----------------
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(14, 20, 14, 16)
        sl.setSpacing(6)

        logo = QLabel("TGraph")
        logo.setObjectName("Logo")
        sl.addWidget(logo)
        ver = QLabel(f"v{APP_VERSION}")
        ver.setObjectName("SecondaryText")
        sl.addWidget(ver)
        sl.addSpacing(16)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.stack = QStackedWidget()

        nav_items = [
            ("👤  Hesap Yönetimi", AccountsPage),
            ("🔍  Üye Tarama", ScraperPage),
            ("➕  Üye Ekleme", AdderPage),
            ("🌐  Proxy Yönetimi", ProxyPage),
            ("🛡️  Spam Testi", SpamTestPage),
            ("⚙️  Ayarlar", SettingsPage),
        ]

        self.pages = []
        for i, (label, PageCls) in enumerate(nav_items):
            page = PageCls(self.db, self)
            self.pages.append(page)
            self.stack.addWidget(page)
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, idx=i: self.switch_page(idx))
            self.nav_group.addButton(btn, i)
            sl.addWidget(btn)
            if i == 0:
                btn.setChecked(True)

        sl.addStretch()

        # Aktif hesap göstergesi
        self.account_indicator = QLabel("Aktif hesap: 0")
        self.account_indicator.setObjectName("SecondaryText")
        self.account_indicator.setStyleSheet(
            f"background:{COLORS['panel2']}; border-radius:8px; padding:10px;"
        )
        self.account_indicator.setAlignment(Qt.AlignCenter)
        sl.addWidget(self.account_indicator)

        root.addWidget(sidebar)

        # ---------------- İçerik ----------------
        content = QFrame()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.stack)
        root.addWidget(content, 1)

        # ---------------- Status bar ----------------
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.conn_label = QLabel("Bağlı hesap: 0")
        self.last_action = QLabel("Hazır")
        self.status.addWidget(self.conn_label)
        self.status.addPermanentWidget(self.last_action)

        self.update_account_count()

    def switch_page(self, idx):
        self.stack.setCurrentIndex(idx)
        page = self.pages[idx]
        # Sayfaya girişte ilgili verileri yenile
        for meth in ("refresh", "refresh_accounts", "refresh_data"):
            if hasattr(page, meth):
                try:
                    getattr(page, meth)()
                except Exception:
                    pass

    def update_account_count(self):
        if not hasattr(self, "account_indicator") or not hasattr(self, "conn_label"):
            return
        accounts = self.db.get_accounts()
        active = sum(1 for a in accounts if a.get("is_active"))
        self.account_indicator.setText(f"Aktif hesap: {active} / {len(accounts)}")
        self.conn_label.setText(f"Bağlı hesap: {active}")

    def set_status(self, text: str):
        self.last_action.setText(text)
