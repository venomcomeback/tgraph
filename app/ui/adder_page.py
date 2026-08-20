"""
TGraph - Üye Ekleme Sayfası
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QHeaderView,
    QLineEdit, QComboBox, QLabel, QGroupBox, QRadioButton, QProgressBar, QTextEdit,
    QListWidget, QListWidgetItem, QSpinBox, QFileDialog, QMessageBox, QAbstractItemView,
    QFormLayout, QButtonGroup,
)
from PySide6.QtCore import Qt

from ..database import Database
from ..config import COLORS
from .. import cgraph_compat
from ..workers.adder_worker import AdderWorker
from ..workers.scraper_worker import ScraperWorker
from .widgets import text_item, make_title


class AdderPage(QWidget):
    def __init__(self, db: Database, main_window=None):
        super().__init__()
        self.db = db
        self.main_window = main_window
        self.worker = None
        self.scrape_worker = None
        self.csv_members = []
        self.scraped_members = []
        self._build()
        self.refresh_data()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)
        root.addWidget(make_title("➕ Üye Ekleme"))

        body = QHBoxLayout()
        root.addLayout(body)

        # ----- Sol panel -----
        left = QVBoxLayout()

        src_box = QGroupBox("Kaynak && Hedef")
        sl = QVBoxLayout(src_box)
        src_row = QHBoxLayout()
        self.src_db = QRadioButton("Veritabanı")
        self.src_db.setChecked(True)
        self.src_csv = QRadioButton("Dosya (CSV / Cgraph)")
        self.src_scrape = QRadioButton("Direkt Grup Tarama")
        self.src_group = QButtonGroup(self)
        for b in (self.src_db, self.src_csv, self.src_scrape):
            self.src_group.addButton(b)
            src_row.addWidget(b)
        sl.addLayout(src_row)
        self.src_db.toggled.connect(self._update_source_ui)
        self.src_csv.toggled.connect(self._update_source_ui)
        self.src_scrape.toggled.connect(self._update_source_ui)

        form = QFormLayout()
        self.data_combo = QComboBox()
        form.addRow("Grup Datası:", self.data_combo)
        self.csv_btn = QPushButton("Dosya Seç (CSV / .cumemberdata / .db)")
        self.csv_btn.setObjectName("Secondary")
        self.csv_btn.clicked.connect(self.pick_csv)
        self.csv_label = QLabel("Dosya seçilmedi")
        self.csv_label.setObjectName("SecondaryText")
        form.addRow(self.csv_btn, self.csv_label)
        self.scrape_group_input = QLineEdit()
        self.scrape_group_input.setPlaceholderText("@grup veya link (taranacak)")
        form.addRow("Kaynak Grup:", self.scrape_group_input)
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("Hedef grup @kullaniciadi veya link")
        form.addRow("Hedef Grup:", self.target_input)
        self.method_combo = QComboBox()
        self.method_combo.addItem("User ID ile", False)
        self.method_combo.addItem("Username ile", True)
        form.addRow("Ekleme Yöntemi:", self.method_combo)
        sl.addLayout(form)
        left.addWidget(src_box)

        # Hesap & Zamanlama
        sched_box = QGroupBox("Hesap && Zamanlama")
        schl = QVBoxLayout(sched_box)
        schl.addWidget(QLabel("Aktif Hesaplar (çoklu seçim):"))
        self.account_list = QListWidget()
        self.account_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.account_list.setMaximumHeight(120)
        schl.addWidget(self.account_list)

        delay_form = QFormLayout()
        delay_row = QHBoxLayout()
        self.min_delay = QSpinBox()
        self.min_delay.setRange(1, 3600)
        self.min_delay.setValue(int(self.db.get_setting("min_delay", "30")))
        self.max_delay = QSpinBox()
        self.max_delay.setRange(1, 7200)
        self.max_delay.setValue(int(self.db.get_setting("max_delay", "60")))
        delay_row.addWidget(QLabel("Min"))
        delay_row.addWidget(self.min_delay)
        delay_row.addWidget(QLabel("Max"))
        delay_row.addWidget(self.max_delay)
        delay_row.addWidget(QLabel("sn"))
        delay_form.addRow("Ekleme arası bekleme:", self._wrap(delay_row))

        big_row = QHBoxLayout()
        self.big_every = QSpinBox()
        self.big_every.setRange(0, 1000)
        self.big_every.setValue(int(self.db.get_setting("big_break_every", "10")))
        self.big_minutes = QSpinBox()
        self.big_minutes.setRange(0, 1440)
        self.big_minutes.setValue(int(self.db.get_setting("big_break_minutes", "15")))
        big_row.addWidget(QLabel("Her"))
        big_row.addWidget(self.big_every)
        big_row.addWidget(QLabel("eklemede"))
        big_row.addWidget(self.big_minutes)
        big_row.addWidget(QLabel("dk mola"))
        delay_form.addRow("Büyük mola:", self._wrap(big_row))

        self.daily_limit = QSpinBox()
        self.daily_limit.setRange(1, 10000)
        self.daily_limit.setValue(int(self.db.get_setting("daily_add_limit", "40")))
        delay_form.addRow("Günlük limit/hesap:", self.daily_limit)
        schl.addLayout(delay_form)
        left.addWidget(sched_box)

        ctrl_row = QHBoxLayout()
        self.start_btn = QPushButton("▶ Eklemeyi Başlat")
        self.start_btn.clicked.connect(self.start_add)
        self.pause_btn = QPushButton("⏸ Duraklat")
        self.pause_btn.setObjectName("Secondary")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.stop_btn = QPushButton("⏹ Durdur")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_add)
        ctrl_row.addWidget(self.start_btn)
        ctrl_row.addWidget(self.pause_btn)
        ctrl_row.addWidget(self.stop_btn)
        left.addLayout(ctrl_row)
        left.addStretch()

        left_wrap = QWidget()
        left_wrap.setLayout(left)
        left_wrap.setFixedWidth(400)
        body.addWidget(left_wrap)

        # ----- Sağ panel -----
        right = QVBoxLayout()
        self.progress = QProgressBar()
        right.addWidget(self.progress)
        self.progress_label = QLabel("0 / 0 eklendi")
        self.progress_label.setObjectName("PageTitle")
        right.addWidget(self.progress_label)

        right.addWidget(QLabel("İşlem Günlüğü:"))
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        right.addWidget(self.log_console, 3)

        right.addWidget(QLabel("Hesap Durumu:"))
        self.stat_table = QTableWidget()
        self.stat_table.setColumnCount(3)
        self.stat_table.setHorizontalHeaderLabels(["Hesap", "Eklenen", "Durum"])
        self.stat_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.stat_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stat_table.setMaximumHeight(160)
        right.addWidget(self.stat_table, 1)
        body.addLayout(right)

        self._update_source_ui()

    def _wrap(self, layout):
        w = QWidget()
        w.setLayout(layout)
        return w

    def _update_source_ui(self):
        self.data_combo.setEnabled(self.src_db.isChecked())
        self.csv_btn.setEnabled(self.src_csv.isChecked())
        self.scrape_group_input.setEnabled(self.src_scrape.isChecked())

    def refresh_data(self):
        # Grup datalarını doldur
        self.data_combo.clear()
        for g in self.db.get_member_groups():
            members = self.db.get_members(group_source=g)
            self.data_combo.addItem(f"{g} ({len(members)})", g)
        # Hesapları doldur — yalnızca bağlantısı başarılı (aktif) hesaplar
        self.account_list.clear()
        active_accounts = self.db.get_active_accounts()
        for acc in active_accounts:
            item = QListWidgetItem(f"{acc.get('name') or acc['session_name']} ({acc.get('phone','')}) [{acc.get('status')}]")
            item.setData(Qt.UserRole, acc["id"])
            self.account_list.addItem(item)
            item.setSelected(True)
        if not active_accounts:
            hint = QListWidgetItem(
                "Bağlantısı başarılı hesap yok. Hesap Yönetimi'nden 'Tümünü Bağla' ile doğrulayın."
            )
            hint.setData(Qt.UserRole, None)
            hint.setFlags(Qt.NoItemFlags)
            self.account_list.addItem(hint)

    def pick_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Veri Dosyası Seç", "",
            "Tüm Desteklenenler (*.csv *.cumemberdata *.db);;"
            "CSV (*.csv);;Cgraph Üye Datası (*.cumemberdata);;"
            "Cgraph Veri Tabanı (*.db);;Tüm Dosyalar (*)"
        )
        if not path:
            return
        low = path.lower()
        try:
            if low.endswith(".cumemberdata"):
                # Cgraph düz metin üye datası (Username!UserId!Category)
                self.csv_members = cgraph_compat.import_cumemberdata(path)
                src = "Cgraph .cumemberdata"
            elif cgraph_compat.is_cgraph_data_db(path):
                # Cgraph Data veritabanı (Datasets/Members) - veri seti seçtir
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
                self.csv_members = cgraph_compat.import_cgraph_data_db(path, chosen_id)
                src = "Cgraph .db"
            else:
                # Düz CSV (Cgraph uyumlu kolonlar)
                self.csv_members = self.db.import_members_csv(path)
                src = "CSV"
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Dosya okunamadı:\n{e}")
            return
        self.csv_label.setText(f"{path.split('/')[-1]} ({len(self.csv_members)} üye)")
        self.log(f"{src} yüklendi: {len(self.csv_members)} üye", "info")

    def _selected_accounts(self):
        ids = [self.account_list.item(i).data(Qt.UserRole)
               for i in range(self.account_list.count())
               if self.account_list.item(i).isSelected()]
        return [self.db.get_account(i) for i in ids]

    def _get_members(self, callback):
        """Kaynağa göre üye listesini hazırlar; scrape ise async çeker."""
        if self.src_db.isChecked():
            g = self.data_combo.currentData()
            if not g:
                QMessageBox.warning(self, "Eksik", "Veritabanında grup datası yok.")
                return None
            return self.db.get_members(group_source=g, only_not_added=False)
        elif self.src_csv.isChecked():
            if not self.csv_members:
                QMessageBox.warning(self, "Eksik", "Önce CSV dosyası seçin.")
                return None
            return self.csv_members
        else:
            # Direkt tarama: önce tara sonra callback ile devam et
            return "SCRAPE"

    def start_add(self):
        target = self.target_input.text().strip()
        if not target:
            QMessageBox.warning(self, "Eksik", "Hedef grup girin.")
            return
        accounts = self._selected_accounts()
        if not accounts:
            QMessageBox.warning(self, "Eksik", "En az bir hesap seçin.")
            return

        members = self._get_members(None)
        if members is None:
            return

        if members == "SCRAPE":
            src_group = self.scrape_group_input.text().strip()
            if not src_group:
                QMessageBox.warning(self, "Eksik", "Taranacak kaynak grup girin.")
                return
            self.log("Kaynak grup taranıyor, lütfen bekleyin...", "info")
            filters = {"exclude_bots": True}
            self.scrape_worker = ScraperWorker(accounts[0], src_group, filters,
                                               self.db.get_proxy(accounts[0]["proxy_id"]) if accounts[0].get("proxy_id") else None)
            self.scrape_worker.finished_ok.connect(lambda m: self._launch_add(accounts, target, m))
            self.scrape_worker.error.connect(self.on_error)
            self.scrape_worker.log.connect(self.log)
            self._set_running(True)
            self.scrape_worker.start()
            return

        self._launch_add(accounts, target, members)

    def _launch_add(self, accounts, target, members):
        if not members:
            QMessageBox.information(self, "Bilgi", "Eklenecek üye bulunamadı.")
            self._set_running(False)
            return
        settings = {
            "min_delay": self.min_delay.value(),
            "max_delay": self.max_delay.value(),
            "big_break_every": self.big_every.value(),
            "big_break_minutes": self.big_minutes.value(),
            "daily_add_limit": self.daily_limit.value(),
            "by_username": self.method_combo.currentData(),
        }
        proxies_by_id = {p["id"]: p for p in self.db.get_proxies()}
        self.progress.setMaximum(len(members))
        self.progress.setValue(0)
        self._set_running(True)
        self._init_stat_table(accounts)

        self.worker = AdderWorker(accounts, target, members, settings, proxies_by_id)
        self.worker.progress.connect(self.on_progress)
        self.worker.log.connect(self.log)
        self.worker.account_stat.connect(self.on_account_stat)
        self.worker.flood_wait.connect(self.on_flood)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def _set_running(self, running):
        self.start_btn.setEnabled(not running)
        self.pause_btn.setEnabled(running)
        self.stop_btn.setEnabled(running)

    def _init_stat_table(self, accounts):
        self.stat_table.setRowCount(len(accounts))
        self._stat_rows = {}
        for i, acc in enumerate(accounts):
            name = acc.get("name") or acc["session_name"]
            self.stat_table.setItem(i, 0, text_item(name))
            self.stat_table.setItem(i, 1, text_item("0", center=True))
            self.stat_table.setItem(i, 2, text_item("Bekliyor"))
            self._stat_rows[name] = i

    def toggle_pause(self):
        if not self.worker:
            return
        if self.pause_btn.text().startswith("⏸"):
            self.worker.pause()
            self.pause_btn.setText("▶ Devam")
            self.log("İşlem duraklatıldı.", "warning")
        else:
            self.worker.resume()
            self.pause_btn.setText("⏸ Duraklat")
            self.log("İşlem devam ediyor.", "info")

    def stop_add(self):
        if self.worker:
            self.worker.stop()
        if self.scrape_worker:
            self.scrape_worker.stop()
        self._set_running(False)

    def on_progress(self, added, total):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(added)
        self.progress_label.setText(f"{added} / {total} eklendi")

    def on_account_stat(self, name, count, status):
        if hasattr(self, "_stat_rows") and name in self._stat_rows:
            row = self._stat_rows[name]
            self.stat_table.setItem(row, 1, text_item(str(count), center=True))
            self.stat_table.setItem(row, 2, text_item(status))

    def on_flood(self, secs):
        self.log(f"⚠ FloodWait: {secs} saniye bekleniyor.", "warning")
        if self.main_window:
            self.main_window.set_status(f"FloodWait: {secs}s")

    def on_finished(self, summary):
        self._set_running(False)
        self.pause_btn.setText("⏸ Duraklat")
        self.log(f"Tamamlandı: {summary['added']}/{summary['total']} eklendi.", "success")
        self.refresh_data()
        if self.main_window:
            self.main_window.set_status(f"Ekleme bitti: {summary['added']} üye")

    def on_error(self, msg):
        self._set_running(False)
        self.log(f"HATA: {msg}", "error")
        QMessageBox.critical(self, "Hata", msg)

    def log(self, msg, level="info"):
        color = {
            "info": COLORS["text_secondary"],
            "success": COLORS["success"],
            "error": COLORS["error"],
            "warning": COLORS["warning"],
        }.get(level, COLORS["text"])
        self.log_console.append(f'<span style="color:{color}">{msg}</span>')
        sb = self.log_console.verticalScrollBar()
        sb.setValue(sb.maximum())
