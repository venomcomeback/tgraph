"""
TGraph - Proxy Yönetimi Sayfası
"""
import os
import socket
import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QHeaderView,
    QDialog, QLineEdit, QComboBox, QFormLayout, QMessageBox, QFileDialog,
    QAbstractItemView, QCheckBox, QSpinBox, QPlainTextEdit, QLabel, QProgressBar,
)
from PySide6.QtCore import Qt, QThread, Signal

from ..database import Database
from ..config import COLORS
from .. import cgraph_compat
from ..workers.proxy_worker import ProxyFetchWorker, ProxyBulkTestWorker
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


class AutoFetchDialog(QDialog):
    """İnternetten ücretsiz proxy indirir, test eder ve kaydeder."""

    TYPE_OPTIONS = [
        ("SOCKS5", ["socks5"]),
        ("SOCKS4", ["socks4"]),
        ("HTTP", ["http"]),
        ("Hepsi", ["socks5", "socks4", "http"]),
    ]

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Otomatik TR Proxy Yükle")
        self.setMinimumWidth(560)
        self.setMinimumHeight(460)
        self.worker = None
        self.saved = 0

        layout = QVBoxLayout(self)
        info = QLabel(
            "İnternetteki ücretsiz kaynaklardan yalnızca Türkiye (TR) proxy'leri "
            "indirilir. Ülke filtreli kaynaklar (ProxyScrape/Geonode) doğrudan TR verir; "
            "genel kaynaklardan gelen IP'ler GeoIP ile TR olup olmadığı doğrulanır. "
            "Ücretsiz proxy'ler kararsız olabilir; 'test et' seçeneği yalnızca "
            "çalışanları kaydeder."
        )
        info.setObjectName("SecondaryText")
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.type_combo = QComboBox()
        for label, _ in self.TYPE_OPTIONS:
            self.type_combo.addItem(label)
        self.type_combo.setCurrentIndex(0)  # SOCKS5 varsayılan
        self.count_spin = QSpinBox()
        self.count_spin.setRange(10, 5000)
        self.count_spin.setValue(200)
        self.test_check = QCheckBox("İndirildikten sonra test et ve sadece çalışanları kaydet")
        self.test_check.setChecked(True)
        form.addRow("Proxy Tipi:", self.type_combo)
        form.addRow("Azami Sayı:", self.count_spin)
        form.addRow("", self.test_check)
        layout.addLayout(form)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("İşlem günlüğü burada görünecek...")
        layout.addWidget(self.log)

        btns = QHBoxLayout()
        self.start_btn = QPushButton("İndir")
        self.start_btn.setToolTip("Seçilen tipte ücretsiz proxy'leri indirip kaydeder")
        self.start_btn.clicked.connect(self.start)
        self.close_btn = QPushButton("Kapat")
        self.close_btn.setObjectName("Secondary")
        self.close_btn.clicked.connect(self.reject)
        btns.addWidget(self.close_btn)
        btns.addWidget(self.start_btn)
        layout.addLayout(btns)

    def _log(self, line):
        self.log.appendPlainText(line)

    def start(self):
        types = self.TYPE_OPTIONS[self.type_combo.currentIndex()][1]
        self.start_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)  # belirsiz (indirme aşaması)
        self.worker = ProxyFetchWorker(
            self.db, types, self.count_spin.value(), self.test_check.isChecked()
        )
        self.worker.log.connect(self._log)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_summary.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, tested, total, working):
        self.progress.setRange(0, total)
        self.progress.setValue(tested)
        self.progress.setFormat(f"Test: {tested}/{total} — çalışan: {working}")

    def on_finished(self, downloaded, tested, saved):
        self.saved = saved
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.setFormat("Tamamlandı")
        self.start_btn.setEnabled(True)
        self.close_btn.setEnabled(True)
        self.close_btn.setText("Kapat ve Yenile")
        QMessageBox.information(
            self, "Otomatik Proxy Yükleme",
            f"{downloaded} proxy indirildi, {tested} test edildi, {saved} çalışan kaydedildi."
        )

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        super().reject()


class ProxyPage(QWidget):
    def __init__(self, db: Database, main_window=None):
        super().__init__()
        self.db = db
        self.main_window = main_window
        self.test_worker = None
        self.bulk_test_worker = None
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
        cg_btn = QPushButton("Cgraph'tan İçe Aktar (.api)")
        cg_btn.setObjectName("Secondary")
        cg_btn.setToolTip("Cgraph ProxySettings.api / ApiSettings.api dosyalarından "
                          "proxy ve API bilgilerini içe aktarır")
        cg_btn.clicked.connect(self.import_cgraph_api)
        auto_btn = QPushButton("Otomatik TR Proxy Yükle")
        auto_btn.setObjectName("Secondary")
        auto_btn.setToolTip("İnternetteki ücretsiz kaynaklardan yalnızca Türkiye (TR) "
                            "proxy'lerini indirir, test eder ve çalışanları kaydeder")
        auto_btn.clicked.connect(self.auto_fetch)
        assign_btn = QPushButton("TR Proxyleri Hesaplara Ata")
        assign_btn.setObjectName("Success")
        assign_btn.setToolTip("Çalışan TR proxy havuzunu aktif hesaplara round-robin dağıtır")
        assign_btn.clicked.connect(self.assign_to_accounts)
        del_btn = QPushButton("Seçileni Sil")
        del_btn.setObjectName("Danger")
        del_btn.clicked.connect(self.delete_selected)
        test_btn = QPushButton("Hepsini Test Et")
        test_btn.setObjectName("Success")
        test_btn.clicked.connect(self.test_all)
        test_btn.setToolTip("Kayıtlı tüm proxy'leri hızlı TCP-connect ile test eder")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(cg_btn)
        btn_row.addWidget(auto_btn)
        btn_row.addWidget(assign_btn)
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

    def import_cgraph_api(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Cgraph Ayar Dosyası Seç", "",
            "Cgraph Ayar Dosyası (*.api);;Tüm Dosyalar (*)"
        )
        if not path:
            return
        tables = cgraph_compat.api_file_tables(path)
        if not tables:
            QMessageBox.critical(
                self, "Hata",
                "Dosya okunamadı veya geçerli bir Cgraph .api (SQLite) dosyası değil."
            )
            return

        summary_lines = []

        # --- Proxy tablosu ---
        if "CGraphProxyInfos" in tables:
            try:
                proxies = cgraph_compat.read_cgraph_proxy_api(path)
            except Exception as e:
                proxies = []
                summary_lines.append(f"Proxy okuma hatası: {e}")
            imported = skipped_dup = 0
            skipped_mtproto = 0
            # Toplam satır sayısını da göstermek için ham sayıya bakalım
            for p in proxies:
                if p["proxy_type"] == "mtproto":
                    # MTProto PySocks tuple'ına çevrilemez; yine de kaydet ama not düş
                    pass
                rid = self.db.add_proxy_unique(
                    p["proxy_type"], p["host"], p["port"],
                    p.get("username", ""), p.get("password", ""),
                )
                if rid is None:
                    skipped_dup += 1
                else:
                    imported += 1
                    if p["proxy_type"] == "mtproto":
                        skipped_mtproto += 1
            # Geçersiz (çöp) satır sayısı = toplam ham - geçerli
            invalid = self._count_invalid_proxy_rows(path, len(proxies))
            line = f"🌐 Proxy: {imported} içe aktarıldı, {invalid} atlandı (geçersiz)"
            if skipped_dup:
                line += f", {skipped_dup} zaten kayıtlı"
            if skipped_mtproto:
                line += f"  (⚠️ {skipped_mtproto} MTProto — Telethon PySocks ile kullanılamaz)"
            summary_lines.append(line)

        # --- API havuzu tablosu ---
        if "CGraphApiInfos" in tables:
            try:
                pool = cgraph_compat.read_cgraph_api_pool(path)
            except Exception as e:
                pool = []
                summary_lines.append(f"API okuma hatası: {e}")
            api_imported = api_dup = 0
            for a in pool:
                rid = self.db.add_api_credential(a["api_id"], a["api_hash"], a.get("extra", ""))
                if rid is None:
                    api_dup += 1
                else:
                    api_imported += 1
            line = f"🔑 API: {api_imported} çift içe aktarıldı"
            if api_dup:
                line += f", {api_dup} zaten kayıtlı"
            summary_lines.append(line)

        if not summary_lines:
            summary_lines.append(
                "Bu .api dosyasında tanınan tablo (CGraphProxyInfos / CGraphApiInfos) bulunamadı."
            )

        self.refresh()
        QMessageBox.information(
            self, "Cgraph İçe Aktarma Özeti", "\n".join(summary_lines)
        )

    def _count_invalid_proxy_rows(self, path, valid_count):
        """Toplam ham satır - geçerli = geçersiz (çöp) satır sayısı."""
        import sqlite3
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            total = conn.execute("SELECT COUNT(*) FROM CGraphProxyInfos").fetchone()[0]
            conn.close()
            return max(0, total - valid_count)
        except Exception:
            return 0

    def auto_fetch(self):
        dlg = AutoFetchDialog(self.db, self)
        dlg.exec()
        self.refresh()

    def assign_to_accounts(self):
        """Çalışan TR proxy havuzunu aktif hesaplara round-robin dağıtır."""
        accounts = self.db.get_active_accounts()
        if not accounts:
            QMessageBox.information(
                self, "Bilgi", "Proxy atanacak aktif hesap bulunamadı."
            )
            return
        proxies = self.db.get_proxies()
        if not proxies:
            QMessageBox.information(
                self, "Bilgi",
                "Atanacak proxy yok. Önce 'Otomatik TR Proxy Yükle' ile proxy ekleyin."
            )
            return
        working = [p for p in proxies if p.get("is_working")]
        if not working:
            resp = QMessageBox.question(
                self, "Çalışan proxy yok",
                "Test edilmiş çalışan proxy bulunamadı. Tüm proxy havuzu dağıtılsın mı?\n"
                "(Önce 'Hepsini Test Et' önerilir.)",
                QMessageBox.Yes | QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                return
        res = self.db.assign_proxies_to_accounts(only_working=True)
        if self.main_window:
            self.main_window.set_status(
                f"TR proxy ataması: {res['assigned']} hesaba atandı."
            )
        QMessageBox.information(
            self, "TR Proxy Ataması",
            f"{res['assigned']} aktif hesaba, {res['proxies']} proxy'lik havuzdan "
            f"round-robin proxy atandı."
        )

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
        self.bulk_test_worker = ProxyBulkTestWorker(proxies)
        self.bulk_test_worker.result.connect(self.on_test_result)
        if self.main_window:
            self.bulk_test_worker.progress.connect(
                lambda done, total, ok: self.main_window.set_status(
                    f"Proxy test ediliyor: {done}/{total} ({ok} çalışıyor)"
                )
            )
        self.bulk_test_worker.finished_ok.connect(self.on_bulk_test_finished)
        self.bulk_test_worker.start()

    def on_test_result(self, proxy_id, working):
        # Sonucu veritabanına yaz; UI'yi burada yenileme (test bitince toplu yenilenir)
        self.db.update_proxy(
            proxy_id,
            is_working=1 if working else 0,
            last_check=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

    def on_bulk_test_finished(self, tested, working):
        self.refresh()
        if self.main_window:
            self.main_window.set_status(
                f"Test tamamlandı — {tested} test edildi, {working} çalışıyor."
            )
