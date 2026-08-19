"""
TGraph - Proxy Yönetimi Sayfası
"""
import socket
import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QHeaderView,
    QDialog, QLineEdit, QComboBox, QFormLayout, QMessageBox, QFileDialog,
    QAbstractItemView, QCheckBox, QSpinBox,
)
from PySide6.QtCore import Qt, QThread, Signal

from ..database import Database
from ..config import COLORS
from .widgets import text_item, make_title


class ProxyTestWorker(QThread):
    result = Signal(int, bool)  # proxy_id, working

    def __init__(self, proxies):
        super().__init__()
        self.proxies = proxies

    def run(self):
        for p in self.proxies:
            working = False
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(6)
                sock.connect((p["host"], int(p["port"])))
                sock.close()
                working = True
            except Exception:
                working = False
            self.result.emit(p["id"], working)


class AddProxyDialog(QDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Proxy Ekle")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.type_combo = QComboBox()
        self.type_combo.addItems(["socks5", "http"])
        self.host_input = QLineEdit()
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(1080)
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Opsiyonel")
        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("Opsiyonel")
        form.addRow("Tip:", self.type_combo)
        form.addRow("Host:", self.host_input)
        form.addRow("Port:", self.port_input)
        form.addRow("Kullanıcı:", self.user_input)
        form.addRow("Şifre:", self.pass_input)
        layout.addLayout(form)
        btns = QHBoxLayout()
        ok = QPushButton("Ekle")
        ok.clicked.connect(self.save)
        cancel = QPushButton("İptal")
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        layout.addLayout(btns)

    def save(self):
        host = self.host_input.text().strip()
        if not host:
            QMessageBox.warning(self, "Eksik", "Host zorunludur.")
            return
        self.db.add_proxy(
            self.type_combo.currentText(), host, self.port_input.value(),
            self.user_input.text().strip(), self.pass_input.text().strip(),
        )
        self.accept()


class ProxyPage(QWidget):
    def __init__(self, db: Database, main_window=None):
        super().__init__()
        self.db = db
        self.main_window = main_window
        self.test_worker = None
        self._build()
        self.refresh()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        layout.addWidget(make_title("🌐 Proxy Yönetimi"))

        btn_row = QHBoxLayout()
        add_btn = QPushButton("＋ Proxy Ekle")
        add_btn.clicked.connect(self.add_proxy)
        load_btn = QPushButton("Dosyadan Yükle")
        load_btn.setObjectName("Secondary")
        load_btn.clicked.connect(self.load_file)
        del_btn = QPushButton("Seçileni Sil")
        del_btn.setObjectName("Danger")
        del_btn.clicked.connect(self.delete_selected)
        test_btn = QPushButton("Hepsini Test Et")
        test_btn.setObjectName("Success")
        test_btn.clicked.connect(self.test_all)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(test_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Seç", "Tip", "Host", "Port", "Kullanıcı", "Durum", "Son Kontrol"]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table)

    def refresh(self):
        from PySide6.QtGui import QColor, QBrush
        proxies = self.db.get_proxies()
        self.table.setRowCount(len(proxies))
        for row, p in enumerate(proxies):
            chk = QCheckBox()
            wrap = QWidget()
            wl = QHBoxLayout(wrap)
            wl.addWidget(chk)
            wl.setAlignment(Qt.AlignCenter)
            wl.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, 0, wrap)
            chk.setProperty("proxy_id", p["id"])
            self.table.setItem(row, 1, text_item(p["proxy_type"], center=True))
            self.table.setItem(row, 2, text_item(p["host"]))
            self.table.setItem(row, 3, text_item(p["port"], center=True))
            self.table.setItem(row, 4, text_item(p.get("username") or "-"))
            if p.get("last_check"):
                status = "Çalışıyor" if p.get("is_working") else "Çalışmıyor"
                color = COLORS["success"] if p.get("is_working") else COLORS["error"]
            else:
                status = "Test edilmedi"
                color = COLORS["text_secondary"]
            item = text_item(status, center=True)
            item.setForeground(QBrush(QColor(color)))
            self.table.setItem(row, 5, item)
            self.table.setItem(row, 6, text_item(p.get("last_check") or "-"))

    def selected_ids(self):
        ids = []
        for row in range(self.table.rowCount()):
            wrap = self.table.cellWidget(row, 0)
            if wrap:
                chk = wrap.findChild(QCheckBox)
                if chk and chk.isChecked():
                    ids.append(chk.property("proxy_id"))
        return ids

    def add_proxy(self):
        dlg = AddProxyDialog(self.db, self)
        if dlg.exec():
            self.refresh()

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Proxy Dosyası", "", "Metin (*.txt);;Tümü (*)")
        if not path:
            return
        count = 0
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(":")
                # formatlar: type:host:port:user:pass  veya host:port
                if len(parts) >= 3 and parts[0].lower() in ("socks5", "http", "https"):
                    ptype = "socks5" if parts[0].lower() == "socks5" else "http"
                    host, port = parts[1], parts[2]
                    user = parts[3] if len(parts) > 3 else ""
                    pw = parts[4] if len(parts) > 4 else ""
                elif len(parts) >= 2:
                    ptype = "socks5"
                    host, port = parts[0], parts[1]
                    user = parts[2] if len(parts) > 2 else ""
                    pw = parts[3] if len(parts) > 3 else ""
                else:
                    continue
                try:
                    self.db.add_proxy(ptype, host, int(port), user, pw)
                    count += 1
                except Exception:
                    continue
        self.refresh()
        QMessageBox.information(self, "Yüklendi", f"{count} proxy eklendi.")

    def delete_selected(self):
        ids = self.selected_ids()
        if not ids:
            QMessageBox.information(self, "Bilgi", "Silmek için proxy seçin.")
            return
        for pid in ids:
            self.db.delete_proxy(pid)
        self.refresh()

    def test_all(self):
        proxies = self.db.get_proxies()
        if not proxies:
            QMessageBox.information(self, "Bilgi", "Test edilecek proxy yok.")
            return
        if self.main_window:
            self.main_window.set_status("Proxyler test ediliyor...")
        self.test_worker = ProxyTestWorker(proxies)
        self.test_worker.result.connect(self.on_test_result)
        self.test_worker.finished.connect(self.refresh)
        self.test_worker.start()

    def on_test_result(self, proxy_id, working):
        self.db.update_proxy(
            proxy_id,
            is_working=1 if working else 0,
            last_check=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
        self.refresh()
