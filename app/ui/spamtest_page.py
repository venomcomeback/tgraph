"""
TGraph - Spam Testi Sayfası
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QHeaderView,
    QListWidget, QListWidgetItem, QMessageBox, QAbstractItemView, QLabel,
)
from PySide6.QtGui import QColor, QBrush
from PySide6.QtCore import Qt

from ..database import Database
from ..config import COLORS, STATUS_OK, STATUS_SPAM, STATUS_BANNED
from ..workers.spamtest_worker import SpamTestWorker
from .widgets import text_item, make_title


class SpamTestPage(QWidget):
    def __init__(self, db: Database, main_window=None):
        super().__init__()
        self.db = db
        self.main_window = main_window
        self.worker = None
        self._build()
        self.refresh_accounts()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        layout.addWidget(make_title("🛡️ Spam Testi"))

        info = QLabel("Seçili hesaplar @SpamBot ile test edilir. "
                      "Sonuç: Aktif (yeşil), Spam (turuncu), Yasaklı (kırmızı).")
        info.setObjectName("SecondaryText")
        layout.addWidget(info)

        body = QHBoxLayout()
        layout.addLayout(body)

        left = QVBoxLayout()
        left.addWidget(QLabel("Hesaplar:"))
        self.account_list = QListWidget()
        self.account_list.setSelectionMode(QAbstractItemView.MultiSelection)
        left.addWidget(self.account_list)
        btn_row = QHBoxLayout()
        test_sel = QPushButton("▶ Seçilenleri Test Et")
        test_sel.clicked.connect(self.test_selected)
        test_all = QPushButton("Hepsini Test Et")
        test_all.setObjectName("Success")
        test_all.clicked.connect(self.test_all)
        btn_row.addWidget(test_sel)
        btn_row.addWidget(test_all)
        left.addLayout(btn_row)
        left_wrap = QWidget()
        left_wrap.setLayout(left)
        left_wrap.setFixedWidth(330)
        body.addWidget(left_wrap)

        right = QVBoxLayout()
        right.addWidget(QLabel("Sonuçlar:"))
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Hesap", "Telefon", "Durum", "Detay", "Test Zamanı"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        right.addWidget(self.table)
        body.addLayout(right)

    def refresh_accounts(self):
        self.account_list.clear()
        active_accounts = self.db.get_active_accounts()
        for acc in active_accounts:
            item = QListWidgetItem(f"{acc.get('name') or acc['session_name']} ({acc.get('phone','')})")
            item.setData(Qt.UserRole, acc["id"])
            self.account_list.addItem(item)
        if not active_accounts:
            hint = QListWidgetItem(
                "Bağlantısı başarılı hesap yok. Hesap Yönetimi'nden 'Tümünü Bağla' ile doğrulayın."
            )
            hint.setData(Qt.UserRole, None)
            hint.setFlags(Qt.NoItemFlags)
            self.account_list.addItem(hint)

    def _accounts_from_ids(self, ids):
        return [self.db.get_account(i) for i in ids]

    def test_selected(self):
        ids = [self.account_list.item(i).data(Qt.UserRole)
               for i in range(self.account_list.count())
               if self.account_list.item(i).isSelected()]
        if not ids:
            QMessageBox.information(self, "Bilgi", "Test için hesap seçin.")
            return
        self._start(self._accounts_from_ids(ids))

    def test_all(self):
        accounts = self.db.get_active_accounts()
        if not accounts:
            QMessageBox.information(
                self, "Hesap Yok",
                "Bağlantısı başarılı hesap yok. Hesap Yönetimi'nden 'Tümünü Bağla' ile "
                "hesapları doğrulayın."
            )
            return
        self._start(accounts)

    def _start(self, accounts):
        self.table.setRowCount(0)
        proxies_by_id = {p["id"]: p for p in self.db.get_proxies()}
        if self.main_window:
            self.main_window.set_status("Spam testi başladı...")
        self.worker = SpamTestWorker(accounts, proxies_by_id)
        self.worker.result.connect(self.on_result)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.error.connect(lambda m: QMessageBox.critical(self, "Hata", m))
        self.worker.start()

    def on_result(self, res):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, text_item(res["name"]))
        self.table.setItem(row, 1, text_item(res["phone"]))
        status_map = {
            STATUS_OK: ("Aktif", COLORS["success"]),
            STATUS_SPAM: ("Spam", COLORS["warning"]),
            STATUS_BANNED: ("Yasaklı", COLORS["error"]),
        }
        label, color = status_map.get(res["status"], ("Bilinmiyor", COLORS["text_secondary"]))
        st_item = text_item(label, center=True)
        st_item.setForeground(QBrush(QColor(color)))
        self.table.setItem(row, 2, st_item)
        self.table.setItem(row, 3, text_item(res["detail"]))
        self.table.setItem(row, 4, text_item(res["time"]))

        # DB durumunu güncelle
        if res.get("account_id"):
            self.db.update_account(res["account_id"], status=res["status"])

    def on_finished(self):
        if self.main_window:
            self.main_window.set_status("Spam testi tamamlandı.")
