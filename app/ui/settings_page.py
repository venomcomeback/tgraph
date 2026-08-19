"""
TGraph - Ayarlar Sayfası
"""
import os
import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QGroupBox, QFormLayout,
    QComboBox, QCheckBox, QSpinBox, QLineEdit, QLabel, QFileDialog, QMessageBox,
)

from ..database import Database
from ..config import DB_PATH, SESSIONS_DIR
from .widgets import make_title


class SettingsPage(QWidget):
    def __init__(self, db: Database, main_window=None):
        super().__init__()
        self.db = db
        self.main_window = main_window
        self._build()
        self.load_settings()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        layout.addWidget(make_title("⚙️ Ayarlar"))

        # Genel
        gen = QGroupBox("Genel")
        gf = QFormLayout(gen)
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Türkçe", "tr")
        self.lang_combo.addItem("English", "en")
        self.auto_connect = QCheckBox("Başlangıçta hesapları otomatik bağla")
        gf.addRow("Uygulama Dili:", self.lang_combo)
        gf.addRow("", self.auto_connect)
        layout.addWidget(gen)

        # Ekleme Limitleri
        lim = QGroupBox("Ekleme Limitleri")
        lf = QFormLayout(lim)
        self.daily_limit = QSpinBox()
        self.daily_limit.setRange(1, 10000)
        self.hourly_limit = QSpinBox()
        self.hourly_limit.setRange(1, 10000)
        lf.addRow("Günlük max ekleme/hesap:", self.daily_limit)
        lf.addRow("Saatlik max ekleme/hesap:", self.hourly_limit)
        layout.addWidget(lim)

        # Gecikme Ayarları
        delay = QGroupBox("Gecikme Ayarları")
        df = QFormLayout(delay)
        self.min_delay = QSpinBox()
        self.min_delay.setRange(1, 7200)
        self.max_delay = QSpinBox()
        self.max_delay.setRange(1, 7200)
        self.big_every = QSpinBox()
        self.big_every.setRange(0, 1000)
        self.big_minutes = QSpinBox()
        self.big_minutes.setRange(0, 1440)
        df.addRow("Min bekleme (sn):", self.min_delay)
        df.addRow("Max bekleme (sn):", self.max_delay)
        df.addRow("Büyük mola tetikleyici (her X ekleme):", self.big_every)
        df.addRow("Büyük mola süresi (dk):", self.big_minutes)
        layout.addWidget(delay)

        # Session klasörü
        sess = QGroupBox("Session Klasörü")
        sfl = QHBoxLayout(sess)
        self.sess_input = QLineEdit()
        sess_btn = QPushButton("Klasör Seç")
        sess_btn.setObjectName("Secondary")
        sess_btn.clicked.connect(self.pick_session_dir)
        sfl.addWidget(self.sess_input)
        sfl.addWidget(sess_btn)
        layout.addWidget(sess)

        # Yedekleme
        backup = QGroupBox("Veri Yedekleme")
        bl = QHBoxLayout(backup)
        self.db_label = QLabel(f"DB: {DB_PATH}")
        self.db_label.setObjectName("SecondaryText")
        backup_btn = QPushButton("Yedek Al")
        backup_btn.setObjectName("Success")
        backup_btn.clicked.connect(self.backup)
        bl.addWidget(self.db_label)
        bl.addStretch()
        bl.addWidget(backup_btn)
        layout.addWidget(backup)

        save_btn = QPushButton("💾 Ayarları Kaydet")
        save_btn.clicked.connect(self.save_settings)
        layout.addWidget(save_btn)
        layout.addStretch()

    def load_settings(self):
        s = self.db.get_all_settings()
        idx = self.lang_combo.findData(s.get("language", "tr"))
        self.lang_combo.setCurrentIndex(max(0, idx))
        self.auto_connect.setChecked(s.get("auto_connect", "0") == "1")
        self.daily_limit.setValue(int(s.get("daily_add_limit", "40")))
        self.hourly_limit.setValue(int(s.get("hourly_add_limit", "20")))
        self.min_delay.setValue(int(s.get("min_delay", "30")))
        self.max_delay.setValue(int(s.get("max_delay", "60")))
        self.big_every.setValue(int(s.get("big_break_every", "10")))
        self.big_minutes.setValue(int(s.get("big_break_minutes", "15")))
        self.sess_input.setText(s.get("sessions_dir", SESSIONS_DIR))

    def pick_session_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Session Klasörü Seç", self.sess_input.text())
        if d:
            self.sess_input.setText(d)

    def save_settings(self):
        self.db.set_setting("language", self.lang_combo.currentData())
        self.db.set_setting("auto_connect", "1" if self.auto_connect.isChecked() else "0")
        self.db.set_setting("daily_add_limit", self.daily_limit.value())
        self.db.set_setting("hourly_add_limit", self.hourly_limit.value())
        self.db.set_setting("min_delay", self.min_delay.value())
        self.db.set_setting("max_delay", self.max_delay.value())
        self.db.set_setting("big_break_every", self.big_every.value())
        self.db.set_setting("big_break_minutes", self.big_minutes.value())
        self.db.set_setting("sessions_dir", self.sess_input.text().strip())
        QMessageBox.information(self, "Kaydedildi", "Ayarlar başarıyla kaydedildi.")

    def backup(self):
        default = f"tgraph_yedek_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        path, _ = QFileDialog.getSaveFileName(self, "Yedek Kaydet", default, "SQLite DB (*.db)")
        if not path:
            return
        try:
            self.db.backup_db(path)
            QMessageBox.information(self, "Yedeklendi", f"Veritabanı yedeği alındı:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Yedekleme başarısız:\n{e}")
