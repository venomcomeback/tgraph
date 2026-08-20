"""
TGraph - Üye Tarama Sayfası
"""
import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QLineEdit, QComboBox, QLabel, QGroupBox, QCheckBox, QProgressBar,
    QFileDialog, QMessageBox, QAbstractItemView, QFormLayout,
)
from PySide6.QtCore import Qt

from ..database import Database
from ..config import LAST_SEEN_OPTIONS
from .. import cgraph_compat
from ..workers.scraper_worker import ScraperWorker
from .widgets import text_item, make_title


class ScraperPage(QWidget):
    def __init__(self, db: Database, main_window=None):
        super().__init__()
        self.db = db
        self.main_window = main_window
        self.worker = None
        self.results = []
        self._build()
        self.refresh_accounts()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)
        root.addWidget(make_title("🔍 Üye Tarama"))

        body = QHBoxLayout()
        root.addLayout(body)

        # ----- Sol panel: Ayarlar -----
        left = QVBoxLayout()
        settings_box = QGroupBox("Tarama Ayarları")
        sform = QFormLayout(settings_box)
        self.group_input = QLineEdit()
        self.group_input.setPlaceholderText("@grupadi veya https://t.me/...")
        self.account_combo = QComboBox()
        self.source_combo = QComboBox()
        self.source_combo.addItem("Grupta görünen üyeler", "participants")
        self.source_combo.addItem("Son 30 günde sohbet eden üyeler", "active_chatters")
        sform.addRow("Hedef Grup:", self.group_input)
        sform.addRow("Hesap:", self.account_combo)
        sform.addRow("Kaynak:", self.source_combo)
        left.addWidget(settings_box)

        filter_box = QGroupBox("Filtreler")
        fl = QVBoxLayout(filter_box)
        self.exclude_bots = QCheckBox("Botları hariç tut")
        self.exclude_bots.setChecked(True)
        self.require_phone = QCheckBox("Sadece telefon numarası olanlar")
        fl.addWidget(self.exclude_bots)
        fl.addWidget(self.require_phone)
        ls_row = QHBoxLayout()
        ls_row.addWidget(QLabel("Son görülme:"))
        self.last_seen_combo = QComboBox()
        for label in LAST_SEEN_OPTIONS:
            self.last_seen_combo.addItem(label, LAST_SEEN_OPTIONS[label])
        ls_row.addWidget(self.last_seen_combo)
        fl.addLayout(ls_row)
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Dil:"))
        self.lang_input = QLineEdit()
        self.lang_input.setPlaceholderText("boş = hepsi, tr = Türkçe")
        lang_row.addWidget(self.lang_input)
        fl.addLayout(lang_row)
        left.addWidget(filter_box)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("▶ Taramayı Başlat")
        self.start_btn.clicked.connect(self.start_scrape)
        self.stop_btn = QPushButton("⏹ Durdur")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_scrape)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        left.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        left.addWidget(self.progress)
        self.progress_label = QLabel("0 / 0 üye tarandı")
        self.progress_label.setObjectName("SecondaryText")
        left.addWidget(self.progress_label)
        left.addStretch()

        left_wrap = QWidget()
        left_wrap.setLayout(left)
        left_wrap.setFixedWidth(340)
        body.addWidget(left_wrap)

        # ----- Sağ panel: Sonuçlar -----
        right = QVBoxLayout()
        right.addWidget(QLabel("Sonuçlar"))
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(
            ["Seç", "#", "Kullanıcı adı", "Ad", "Soyad", "User ID", "Son Görülme", "Dil", "Bot"]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        right.addWidget(self.table)

        res_btns = QHBoxLayout()
        save_btn = QPushButton("Veritabanına Kaydet")
        save_btn.setObjectName("Success")
        save_btn.clicked.connect(self.save_to_db)
        export_btn = QPushButton("CSV Olarak Dışa Aktar")
        export_btn.setObjectName("Secondary")
        export_btn.clicked.connect(lambda: self.export_csv(only_selected=False))
        export_sel_btn = QPushButton("Seçilenleri Dışa Aktar")
        export_sel_btn.setObjectName("Secondary")
        export_sel_btn.clicked.connect(lambda: self.export_csv(only_selected=True))
        export_cu_btn = QPushButton("Cgraph (.cumemberdata) Dışa Aktar")
        export_cu_btn.setObjectName("Secondary")
        export_cu_btn.clicked.connect(self.export_cumemberdata)
        import_cg_btn = QPushButton("Cgraph Data İçe Aktar")
        import_cg_btn.setObjectName("Secondary")
        import_cg_btn.clicked.connect(self.import_cgraph_data)
        res_btns.addWidget(save_btn)
        res_btns.addWidget(export_btn)
        res_btns.addWidget(export_sel_btn)
        res_btns.addWidget(export_cu_btn)
        res_btns.addWidget(import_cg_btn)
        res_btns.addStretch()
        right.addLayout(res_btns)
        body.addLayout(right)

    def refresh_accounts(self):
        self.account_combo.clear()
        accounts = self.db.get_active_accounts()
        for acc in accounts:
            label = f"{acc.get('name') or acc['session_name']} ({acc.get('phone','')})"
            self.account_combo.addItem(label, acc["id"])
        if not accounts:
            self.account_combo.addItem(
                "Bağlantısı başarılı hesap yok — Hesap Yönetimi'nden doğrulayın", None
            )

    def _get_filters(self):
        return {
            "exclude_bots": self.exclude_bots.isChecked(),
            "require_phone": self.require_phone.isChecked(),
            "last_seen_days": self.last_seen_combo.currentData(),
            "lang": self.lang_input.text().strip(),
            "source": self.source_combo.currentData(),
            "chatter_days": 30,
        }

    def start_scrape(self):
        group = self.group_input.text().strip()
        if not group:
            QMessageBox.warning(self, "Eksik", "Hedef grup girin.")
            return
        acc_id = self.account_combo.currentData()
        if not acc_id:
            QMessageBox.warning(
                self, "Hesap Yok",
                "Bağlantısı başarılı hesap yok. Hesap Yönetimi'nden 'Tümünü Bağla' ile "
                "hesapları doğrulayın."
            )
            return
        account = self.db.get_account(acc_id)
        proxy = self.db.get_proxy(account["proxy_id"]) if account.get("proxy_id") else None

        self.table.setRowCount(0)
        self.results = []
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setValue(0)

        self.worker = ScraperWorker(account, group, self._get_filters(), proxy)
        self.worker.progress.connect(self.on_progress)
        self.worker.member_found.connect(self.on_member)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.log.connect(self.on_log)
        self.worker.start()

    def stop_scrape(self):
        if self.worker:
            self.worker.stop()
        self.stop_btn.setEnabled(False)

    def on_progress(self, done, total):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        self.progress_label.setText(f"{done} / {total} üye tarandı")

    def on_member(self, m):
        self.results.append(m)
        self.on_member_display(m)

    def on_member_display(self, m):
        """Bir üyeyi yalnızca tabloya ekler (self.results'a dokunmaz)."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        chk = QCheckBox()
        chk.setChecked(True)
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.addWidget(chk)
        wl.setAlignment(Qt.AlignCenter)
        wl.setContentsMargins(0, 0, 0, 0)
        self.table.setCellWidget(row, 0, wrap)
        self.table.setItem(row, 1, text_item(row + 1, center=True))
        self.table.setItem(row, 2, text_item(m.get("username", "")))
        self.table.setItem(row, 3, text_item(m.get("first_name", "")))
        self.table.setItem(row, 4, text_item(m.get("last_name", "")))
        self.table.setItem(row, 5, text_item(m.get("user_id", "")))
        self.table.setItem(row, 6, text_item(m.get("last_seen", "")))
        self.table.setItem(row, 7, text_item(m.get("lang_code", "")))
        self.table.setItem(row, 8, text_item("Evet" if m.get("is_bot") else "Hayır", center=True))

    def on_finished(self, members):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_label.setText(f"Tamamlandı: {len(members)} üye")
        if self.main_window:
            self.main_window.set_status(f"Tarama bitti: {len(members)} üye")

    def on_error(self, msg):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        QMessageBox.critical(self, "Tarama Hatası", msg)

    def on_log(self, msg, level):
        if self.main_window:
            self.main_window.set_status(msg)

    def save_to_db(self):
        if not self.results:
            QMessageBox.information(self, "Bilgi", "Kaydedilecek üye yok.")
            return
        count = self.db.add_members_bulk(self.results)
        group = self.group_input.text().strip()
        self.db.save_group(0, group, group, len(self.results))
        QMessageBox.information(self, "Kaydedildi",
                               f"{count} yeni üye veritabanına kaydedildi.")

    def _selected_results(self):
        selected = []
        for row in range(self.table.rowCount()):
            wrap = self.table.cellWidget(row, 0)
            if wrap:
                chk = wrap.findChild(QCheckBox)
                if chk and chk.isChecked() and row < len(self.results):
                    selected.append(self.results[row])
        return selected

    def export_csv(self, only_selected=False):
        data = self._selected_results() if only_selected else self.results
        if not data:
            QMessageBox.information(self, "Bilgi", "Dışa aktarılacak üye yok.")
            return
        default = f"uyeler_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "CSV Kaydet", default, "CSV (*.csv)")
        if not path:
            return
        n = self.db.export_members_csv(path, data)
        QMessageBox.information(self, "Dışa Aktarıldı", f"{n} üye CSV'ye aktarıldı:\n{path}")

    def export_cumemberdata(self):
        """Sonuçları Cgraph .cumemberdata formatında dışa aktarır."""
        if not self.results:
            QMessageBox.information(self, "Bilgi", "Dışa aktarılacak üye yok.")
            return
        default = f"uyeler_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.cumemberdata"
        path, _ = QFileDialog.getSaveFileName(
            self, "Cgraph Data Kaydet", default, "Cgraph Üye Datası (*.cumemberdata)"
        )
        if not path:
            return
        n = cgraph_compat.export_cumemberdata(path, self.results)
        QMessageBox.information(self, "Dışa Aktarıldı",
                               f"{n} üye Cgraph formatında aktarıldı:\n{path}")

    def import_cgraph_data(self):
        """Cgraph .cumemberdata veya Data (.db) dosyasını okuyup tabloya + DB'ye aktarır."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Cgraph Data Seç", "",
            "Cgraph Data (*.cumemberdata *.db);;"
            "Cgraph Üye Datası (*.cumemberdata);;Cgraph Veri Tabanı (*.db);;Tüm Dosyalar (*)"
        )
        if not path:
            return
        try:
            if path.lower().endswith(".cumemberdata"):
                members = cgraph_compat.import_cumemberdata(path)
            elif cgraph_compat.is_cgraph_data_db(path):
                datasets = cgraph_compat.list_cgraph_datasets(path)
                if not datasets:
                    QMessageBox.warning(self, "Boş", "Cgraph veritabanında veri seti yok.")
                    return
                if len(datasets) == 1:
                    chosen_id = datasets[0]["DatasetId"]
                else:
                    from PySide6.QtWidgets import QInputDialog
                    items = [f"{d['DatasetId']}: {d['SourceGroup']} ({d['MemberCount']} üye)"
                             for d in datasets]
                    items.append("Tümü")
                    choice, ok = QInputDialog.getItem(
                        self, "Veri Seti Seç",
                        "İçe aktarılacak Cgraph veri setini seçin:", items, 0, False
                    )
                    if not ok:
                        return
                    chosen_id = None if choice == "Tümü" else int(choice.split(":")[0])
                members = cgraph_compat.import_cgraph_data_db(path, chosen_id)
            else:
                QMessageBox.warning(self, "Desteklenmeyen", "Bu dosya türü desteklenmiyor.")
                return
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Dosya okunamadı:\n{e}")
            return

        if not members:
            QMessageBox.information(self, "Bilgi", "Dosyada üye bulunamadı.")
            return

        # Tabloyu temizle ve doldur (çok büyük listelerde tablo gösterimi ilk N ile sınırlı)
        MAX_DISPLAY = 2000
        self.results = list(members)
        self.table.setRowCount(0)
        for m in members[:MAX_DISPLAY]:
            self.on_member_display(m)
        note = ""
        if len(members) > MAX_DISPLAY:
            note = f" (tabloda ilk {MAX_DISPLAY} gösteriliyor)"
        self.progress_label.setText(f"İçe aktarıldı: {len(members)} üye{note}")

        # Otomatik veritabanına kaydet
        count = self.db.add_members_bulk(members)
        QMessageBox.information(
            self, "İçe Aktarıldı",
            f"{len(members)} üye Cgraph'tan yüklendi{note}.\n"
            f"{count} yeni üye veritabanına kaydedildi.\n"
            "Üye Ekleme sayfasından 'Veritabanı' kaynağı ile kullanabilirsiniz."
        )
