"""
TGraph - Hesap İşlemleri Sayfası
================================

Aktif hesaplar üzerinde toplu işlemler:
  * Giriş Kodu İzleme
  * Toplu Emoji ve Görüntülenme
  * Randy Çekilişlerine Katıl
  * Toplu Özel Mesaj
  * Toplu Kanal/Grup Katılımı
  * Toplu Gruptan Çıkma
  * Toplu Profil Güncelleme

Her bölüm kendi giriş alanlarına, ilerleme çubuğuna ve worker'ına sahiptir;
tüm etkileşimler seçili aktif hesaplar üzerinde çalışır.
"""
import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QGroupBox,
    QPlainTextEdit, QLineEdit, QCheckBox, QSpinBox, QProgressBar, QListWidget,
    QListWidgetItem, QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFileDialog, QMessageBox, QGridLayout,
)
from PySide6.QtCore import Qt

from ..database import Database
from ..config import COLORS
from .widgets import make_title, text_item
from ..workers.operations_worker import (
    LoginCodeMonitorWorker, ReactionsViewsWorker, GiveawayJoinWorker,
    BulkDMWorker, JoinChannelsWorker, LeaveChannelsWorker, ProfileUpdateWorker,
)


def _lines(widget: QPlainTextEdit):
    """QPlainTextEdit içeriğini temizlenmiş satır listesine çevirir."""
    return [ln.strip() for ln in widget.toPlainText().splitlines() if ln.strip()]


class OperationsPage(QWidget):
    def __init__(self, db: Database, main_window=None):
        super().__init__()
        self.db = db
        self.main_window = main_window
        # Worker referansları (GC'yi önlemek için)
        self.monitor_worker = None
        self.react_worker = None
        self.giveaway_worker = None
        self.dm_worker = None
        self.join_worker = None
        self.leave_worker = None
        self.profile_worker = None
        self._build()
        self.refresh_accounts()

    # ------------------------------------------------------------------ #
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 12)
        root.setSpacing(12)
        root.addWidget(make_title("🛠️ Hesap İşlemleri"))

        # --- Aktif hesap seçimi ---
        acc_box = QGroupBox("Aktif Hesaplar (işlem yapılacaklar)")
        av = QVBoxLayout(acc_box)
        sel_row = QHBoxLayout()
        self.select_all_btn = QPushButton("Tümünü Seç")
        self.select_all_btn.setObjectName("Secondary")
        self.select_all_btn.clicked.connect(lambda: self._set_all_accounts(True))
        self.select_none_btn = QPushButton("Seçimi Kaldır")
        self.select_none_btn.setObjectName("Secondary")
        self.select_none_btn.clicked.connect(lambda: self._set_all_accounts(False))
        self.refresh_btn = QPushButton("Yenile")
        self.refresh_btn.setObjectName("Secondary")
        self.refresh_btn.clicked.connect(self.refresh_accounts)
        sel_row.addWidget(self.select_all_btn)
        sel_row.addWidget(self.select_none_btn)
        sel_row.addWidget(self.refresh_btn)
        sel_row.addStretch()
        av.addLayout(sel_row)
        self.acc_list = QListWidget()
        self.acc_list.setMaximumHeight(120)
        av.addWidget(self.acc_list)
        root.addWidget(acc_box)

        # --- Kaydırılabilir işlem bölümleri ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.sections = QVBoxLayout(inner)
        self.sections.setSpacing(12)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        self._build_login_monitor()
        self._build_reactions()
        self._build_giveaway()
        self._build_bulk_dm()
        self._build_join()
        self._build_leave()
        self._build_profile()
        self.sections.addStretch()

        # --- Ortak günlük ---
        log_box = QGroupBox("İşlem Günlüğü")
        lv = QVBoxLayout(log_box)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        self.log.setPlaceholderText("İşlem günlükleri burada görünecek...")
        lv.addWidget(self.log)
        root.addWidget(log_box)

    # ------------------------------------------------------------------ #
    #  Hesap seçim yardımcıları
    # ------------------------------------------------------------------ #
    def refresh_accounts(self):
        checked_ids = set(self._selected_account_ids())
        first_load = self.acc_list.count() == 0
        self.acc_list.clear()
        accounts = self.db.get_active_accounts()
        for acc in accounts:
            label = acc.get("name") or acc.get("phone") or acc.get("session_name")
            item = QListWidgetItem(f"{label}  ({acc.get('session_name')})")
            item.setData(Qt.UserRole, acc["id"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            # İlk yüklemede hepsi seçili; sonra önceki seçim korunur
            if first_load or acc["id"] in checked_ids:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.acc_list.addItem(item)
        if not accounts:
            item = QListWidgetItem("Aktif hesap yok — Hesap Yönetimi'nden hesap etkinleştirin.")
            item.setFlags(Qt.NoItemFlags)
            self.acc_list.addItem(item)

    def _set_all_accounts(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self.acc_list.count()):
            item = self.acc_list.item(i)
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(state)

    def _selected_account_ids(self):
        ids = []
        for i in range(self.acc_list.count()):
            item = self.acc_list.item(i)
            if (item.flags() & Qt.ItemIsUserCheckable) and item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids

    def selected_accounts(self):
        ids = set(self._selected_account_ids())
        return [a for a in self.db.get_active_accounts() if a["id"] in ids]

    def _require_accounts(self):
        accs = self.selected_accounts()
        if not accs:
            QMessageBox.information(self, "Bilgi", "Lütfen en az bir aktif hesap seçin.")
            return None
        return accs

    def _log(self, text: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{ts}] {text}")

    # ================================================================== #
    #  1) Giriş Kodu İzleme
    # ================================================================== #
    def _build_login_monitor(self):
        box = QGroupBox("Giriş Kodu İzleme")
        v = QVBoxLayout(box)
        info = QLabel("Seçili hesaplara Telegram'dan (777000) gelen giriş kodlarını canlı izler.")
        info.setObjectName("SecondaryText")
        info.setWordWrap(True)
        v.addWidget(info)

        row = QHBoxLayout()
        self.monitor_start_btn = QPushButton("İzlemeyi Başlat")
        self.monitor_start_btn.setObjectName("Success")
        self.monitor_start_btn.clicked.connect(self.start_monitor)
        self.monitor_stop_btn = QPushButton("İzlemeyi Durdur")
        self.monitor_stop_btn.setObjectName("Danger")
        self.monitor_stop_btn.setEnabled(False)
        self.monitor_stop_btn.clicked.connect(self.stop_monitor)
        row.addWidget(self.monitor_start_btn)
        row.addWidget(self.monitor_stop_btn)
        row.addStretch()
        v.addLayout(row)

        self.code_table = QTableWidget()
        self.code_table.setColumnCount(3)
        self.code_table.setHorizontalHeaderLabels(["Hesap", "Kod", "Zaman"])
        self.code_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.code_table.setMaximumHeight(160)
        self.code_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        v.addWidget(self.code_table)
        self.sections.addWidget(box)

    def start_monitor(self):
        accs = self._require_accounts()
        if not accs:
            return
        self.code_table.setRowCount(0)
        self.monitor_start_btn.setEnabled(False)
        self.monitor_stop_btn.setEnabled(True)
        self.monitor_worker = LoginCodeMonitorWorker(self.db, accs, interval=5)
        self.monitor_worker.log.connect(self._log)
        self.monitor_worker.code_found.connect(self._on_code_found)
        self.monitor_worker.finished.connect(self._on_monitor_finished)
        self.monitor_worker.start()
        self._log(f"👁️ {len(accs)} hesap için giriş kodu izleme başlatıldı.")

    def stop_monitor(self):
        if self.monitor_worker and self.monitor_worker.isRunning():
            self.monitor_worker.stop()
            self.monitor_stop_btn.setEnabled(False)

    def _on_monitor_finished(self):
        self.monitor_start_btn.setEnabled(True)
        self.monitor_stop_btn.setEnabled(False)

    def _on_code_found(self, account, code, tstr):
        row = self.code_table.rowCount()
        self.code_table.insertRow(row)
        self.code_table.setItem(row, 0, text_item(account))
        self.code_table.setItem(row, 1, text_item(code, center=True))
        self.code_table.setItem(row, 2, text_item(tstr, center=True))
        self.code_table.scrollToBottom()

    # ================================================================== #
    #  2) Toplu Emoji ve Görüntülenme
    # ================================================================== #
    def _build_reactions(self):
        box = QGroupBox("Toplu Emoji ve Görüntülenme")
        v = QVBoxLayout(box)
        v.addWidget(QLabel("Gönderi Linkleri (her satıra bir tane)"))
        self.react_links = QPlainTextEdit()
        self.react_links.setPlaceholderText("https://t.me/kanal/123\nhttps://t.me/c/1234567/89")
        self.react_links.setMaximumHeight(70)
        v.addWidget(self.react_links)

        form = QHBoxLayout()
        form.addWidget(QLabel("Emoji"))
        self.react_emoji = QLineEdit("👍 ❤️")
        self.react_emoji.setToolTip("Birden fazla emoji için boşluk/virgül ile ayırın; "
                                    "hesaplar sırayla farklı emoji kullanır.")
        form.addWidget(self.react_emoji)
        v.addLayout(form)

        cr = QHBoxLayout()
        self.react_check = QCheckBox("Tepki gönder")
        self.react_check.setChecked(True)
        self.view_check = QCheckBox("Görüntülenme gönder")
        self.view_check.setChecked(True)
        cr.addWidget(self.react_check)
        cr.addWidget(self.view_check)
        cr.addStretch()
        v.addLayout(cr)

        self.react_progress = QProgressBar()
        self.react_progress.setVisible(False)
        v.addWidget(self.react_progress)

        self.react_start_btn = QPushButton("Başlat")
        self.react_start_btn.setObjectName("Success")
        self.react_start_btn.clicked.connect(self.start_reactions)
        v.addWidget(self.react_start_btn)
        self.sections.addWidget(box)

    def start_reactions(self):
        accs = self._require_accounts()
        if not accs:
            return
        links = _lines(self.react_links)
        if not links:
            QMessageBox.information(self, "Bilgi", "En az bir gönderi linki girin.")
            return
        if not (self.react_check.isChecked() or self.view_check.isChecked()):
            QMessageBox.information(self, "Bilgi", "Tepki veya görüntülenmeden en az birini seçin.")
            return
        raw = self.react_emoji.text().replace(",", " ").replace("/", " ")
        emojis = [e for e in raw.split() if e] or ["👍"]
        self.react_start_btn.setEnabled(False)
        self.react_progress.setVisible(True)
        self.react_progress.setRange(0, len(accs) * len(links))
        self.react_progress.setValue(0)
        self.react_worker = ReactionsViewsWorker(
            self.db, accs, links, emojis,
            self.react_check.isChecked(), self.view_check.isChecked(), delay=3,
        )
        self.react_worker.log.connect(self._log)
        self.react_worker.progress.connect(
            lambda d, t: (self.react_progress.setRange(0, t), self.react_progress.setValue(d))
        )
        self.react_worker.finished_ok.connect(
            lambda ok, err: self._simple_finish(self.react_start_btn, self.react_progress,
                                                f"Emoji/görüntülenme bitti — {ok} başarılı, {err} hata.")
        )
        self.react_worker.start()
        self._log(f"🚀 {len(accs)} hesap, {len(links)} gönderi için başladı.")

    # ================================================================== #
    #  3) Randy Çekilişlerine Katıl
    # ================================================================== #
    def _build_giveaway(self):
        box = QGroupBox("Randy Çekilişlerine Katıl")
        v = QVBoxLayout(box)
        v.addWidget(QLabel("Çekiliş Linkleri (her satıra bir tane)"))
        self.giveaway_links = QPlainTextEdit()
        self.giveaway_links.setPlaceholderText("https://t.me/kanal/123")
        self.giveaway_links.setMaximumHeight(60)
        v.addWidget(self.giveaway_links)

        self.giveaway_progress = QProgressBar()
        self.giveaway_progress.setVisible(False)
        v.addWidget(self.giveaway_progress)

        self.giveaway_start_btn = QPushButton("Başlat")
        self.giveaway_start_btn.setObjectName("Success")
        self.giveaway_start_btn.clicked.connect(self.start_giveaway)
        v.addWidget(self.giveaway_start_btn)
        self.sections.addWidget(box)

    def start_giveaway(self):
        accs = self._require_accounts()
        if not accs:
            return
        links = _lines(self.giveaway_links)
        if not links:
            QMessageBox.information(self, "Bilgi", "En az bir çekiliş linki girin.")
            return
        self.giveaway_start_btn.setEnabled(False)
        self.giveaway_progress.setVisible(True)
        self.giveaway_progress.setRange(0, len(accs) * len(links))
        self.giveaway_progress.setValue(0)
        self.giveaway_worker = GiveawayJoinWorker(self.db, accs, links, delay=3)
        self.giveaway_worker.log.connect(self._log)
        self.giveaway_worker.progress.connect(
            lambda d, t: (self.giveaway_progress.setRange(0, t), self.giveaway_progress.setValue(d))
        )
        self.giveaway_worker.finished_ok.connect(
            lambda ok, err: self._simple_finish(self.giveaway_start_btn, self.giveaway_progress,
                                                f"Çekiliş bitti — {ok} katılım, {err} hata.")
        )
        self.giveaway_worker.start()
        self._log(f"🎉 {len(accs)} hesap, {len(links)} çekiliş için başladı.")

    # ================================================================== #
    #  4) Toplu Özel Mesaj
    # ================================================================== #
    def _build_bulk_dm(self):
        box = QGroupBox("Toplu Özel Mesaj")
        v = QVBoxLayout(box)
        v.addWidget(QLabel("Hedef Gruplar / Kullanıcılar (her satıra bir tane)"))
        self.dm_targets = QPlainTextEdit()
        self.dm_targets.setPlaceholderText(
            "https://t.me/grup_linki   (üyelerine mesaj atılır)\n@kullaniciadi\n123456789"
        )
        self.dm_targets.setMaximumHeight(70)
        v.addWidget(self.dm_targets)

        v.addWidget(QLabel("Mesaj"))
        self.dm_message = QPlainTextEdit()
        self.dm_message.setPlaceholderText("Gönderilecek mesaj metni...")
        self.dm_message.setMaximumHeight(70)
        v.addWidget(self.dm_message)

        drow = QHBoxLayout()
        drow.addWidget(QLabel("Mesajlar arası bekleme (sn)"))
        self.dm_delay = QSpinBox()
        self.dm_delay.setRange(1, 3600)
        self.dm_delay.setValue(30)
        drow.addWidget(self.dm_delay)
        drow.addWidget(QLabel("Hesap başına azami (0 = sınırsız)"))
        self.dm_max = QSpinBox()
        self.dm_max.setRange(0, 100000)
        self.dm_max.setValue(0)
        drow.addWidget(self.dm_max)
        drow.addStretch()
        v.addLayout(drow)

        self.dm_progress = QProgressBar()
        self.dm_progress.setVisible(False)
        v.addWidget(self.dm_progress)

        self.dm_start_btn = QPushButton("Başlat")
        self.dm_start_btn.setObjectName("Success")
        self.dm_start_btn.clicked.connect(self.start_dm)
        v.addWidget(self.dm_start_btn)
        self.sections.addWidget(box)

    def start_dm(self):
        accs = self._require_accounts()
        if not accs:
            return
        targets = _lines(self.dm_targets)
        message = self.dm_message.toPlainText().strip()
        if not targets:
            QMessageBox.information(self, "Bilgi", "En az bir hedef grup/kullanıcı girin.")
            return
        if not message:
            QMessageBox.information(self, "Bilgi", "Gönderilecek mesaj boş olamaz.")
            return
        group_links, user_targets = [], []
        for t in targets:
            low = t.lower()
            if "t.me/" in low or low.startswith("+") or "joinchat" in low:
                group_links.append(t)
            else:
                user_targets.append(t)
        self.dm_start_btn.setEnabled(False)
        self.dm_progress.setVisible(True)
        self.dm_progress.setRange(0, 0)
        self.dm_worker = BulkDMWorker(
            self.db, accs, group_links, user_targets, message,
            delay=self.dm_delay.value(), max_per_account=self.dm_max.value(),
        )
        self.dm_worker.log.connect(self._log)
        self.dm_worker.progress.connect(
            lambda d, t: (self.dm_progress.setRange(0, t), self.dm_progress.setValue(d))
        )
        self.dm_worker.finished_ok.connect(
            lambda ok, err: self._simple_finish(self.dm_start_btn, self.dm_progress,
                                                f"Toplu mesaj bitti — {ok} gönderildi, {err} hata.")
        )
        self.dm_worker.start()
        self._log(f"📨 {len(accs)} hesapla toplu mesaj başladı.")

    # ================================================================== #
    #  5) Toplu Kanal/Grup Katılımı
    # ================================================================== #
    def _build_join(self):
        box = QGroupBox("Toplu Kanal/Grup Katılımı")
        v = QVBoxLayout(box)
        v.addWidget(QLabel("Kanal/Grup Linkleri (her satıra bir tane — özel davet linkleri dahil)"))
        self.join_links = QPlainTextEdit()
        self.join_links.setPlaceholderText("https://t.me/kanaladi\nhttps://t.me/+abcdefGHIJ")
        self.join_links.setMaximumHeight(60)
        v.addWidget(self.join_links)

        self.join_progress = QProgressBar()
        self.join_progress.setVisible(False)
        v.addWidget(self.join_progress)

        self.join_start_btn = QPushButton("Başlat")
        self.join_start_btn.setObjectName("Success")
        self.join_start_btn.clicked.connect(self.start_join)
        v.addWidget(self.join_start_btn)
        self.sections.addWidget(box)

    def start_join(self):
        accs = self._require_accounts()
        if not accs:
            return
        links = _lines(self.join_links)
        if not links:
            QMessageBox.information(self, "Bilgi", "En az bir kanal/grup linki girin.")
            return
        self.join_start_btn.setEnabled(False)
        self.join_progress.setVisible(True)
        self.join_progress.setRange(0, len(accs) * len(links))
        self.join_progress.setValue(0)
        self.join_worker = JoinChannelsWorker(self.db, accs, links, delay=5)
        self.join_worker.log.connect(self._log)
        self.join_worker.progress.connect(
            lambda d, t: (self.join_progress.setRange(0, t), self.join_progress.setValue(d))
        )
        self.join_worker.finished_ok.connect(
            lambda ok, err: self._simple_finish(self.join_start_btn, self.join_progress,
                                                f"Katılım bitti — {ok} katılım, {err} hata.")
        )
        self.join_worker.start()
        self._log(f"➕ {len(accs)} hesap, {len(links)} kanal için katılım başladı.")

    # ================================================================== #
    #  6) Toplu Gruptan Çıkma
    # ================================================================== #
    def _build_leave(self):
        box = QGroupBox("Toplu Gruptan Çıkma")
        v = QVBoxLayout(box)
        v.addWidget(QLabel("Kanal/Grup Linkleri (her satıra bir tane)"))
        self.leave_links = QPlainTextEdit()
        self.leave_links.setPlaceholderText("https://t.me/kanaladi")
        self.leave_links.setMaximumHeight(60)
        v.addWidget(self.leave_links)

        self.leave_progress = QProgressBar()
        self.leave_progress.setVisible(False)
        v.addWidget(self.leave_progress)

        self.leave_start_btn = QPushButton("Başlat")
        self.leave_start_btn.setObjectName("Danger")
        self.leave_start_btn.clicked.connect(self.start_leave)
        v.addWidget(self.leave_start_btn)
        self.sections.addWidget(box)

    def start_leave(self):
        accs = self._require_accounts()
        if not accs:
            return
        links = _lines(self.leave_links)
        if not links:
            QMessageBox.information(self, "Bilgi", "En az bir kanal/grup linki girin.")
            return
        self.leave_start_btn.setEnabled(False)
        self.leave_progress.setVisible(True)
        self.leave_progress.setRange(0, len(accs) * len(links))
        self.leave_progress.setValue(0)
        self.leave_worker = LeaveChannelsWorker(self.db, accs, links, delay=3)
        self.leave_worker.log.connect(self._log)
        self.leave_worker.progress.connect(
            lambda d, t: (self.leave_progress.setRange(0, t), self.leave_progress.setValue(d))
        )
        self.leave_worker.finished_ok.connect(
            lambda ok, err: self._simple_finish(self.leave_start_btn, self.leave_progress,
                                                f"Çıkış bitti — {ok} çıkış, {err} hata.")
        )
        self.leave_worker.start()
        self._log(f"🚪 {len(accs)} hesap, {len(links)} grup için çıkış başladı.")

    # ================================================================== #
    #  7) Toplu Profil Güncelleme
    # ================================================================== #
    def _build_profile(self):
        box = QGroupBox("Toplu Profil Güncelleme")
        g = QGridLayout(box)
        g.addWidget(QLabel("Ad"), 0, 0)
        self.profile_first = QLineEdit()
        self.profile_first.setPlaceholderText("Boş bırakılırsa değişmez")
        g.addWidget(self.profile_first, 0, 1)
        g.addWidget(QLabel("Soyad"), 1, 0)
        self.profile_last = QLineEdit()
        self.profile_last.setPlaceholderText("Boş bırakılırsa değişmez")
        g.addWidget(self.profile_last, 1, 1)
        g.addWidget(QLabel("Hakkında (bio)"), 2, 0)
        self.profile_about = QLineEdit()
        self.profile_about.setPlaceholderText("Boş bırakılırsa değişmez")
        g.addWidget(self.profile_about, 2, 1)

        g.addWidget(QLabel("Profil fotoğrafı (opsiyonel)"), 3, 0)
        photo_row = QHBoxLayout()
        self.profile_photo = QLineEdit()
        self.profile_photo.setPlaceholderText("İsteğe bağlı — boş bırakılabilir")
        browse = QPushButton("Seç")
        browse.setObjectName("Secondary")
        browse.clicked.connect(self._pick_photo)
        photo_row.addWidget(self.profile_photo)
        photo_row.addWidget(browse)
        photo_wrap = QWidget()
        photo_wrap.setLayout(photo_row)
        g.addWidget(photo_wrap, 3, 1)

        self.profile_progress = QProgressBar()
        self.profile_progress.setVisible(False)
        g.addWidget(self.profile_progress, 4, 0, 1, 2)

        self.profile_start_btn = QPushButton("Başlat")
        self.profile_start_btn.setObjectName("Success")
        self.profile_start_btn.clicked.connect(self.start_profile)
        g.addWidget(self.profile_start_btn, 5, 0, 1, 2)
        self.sections.addWidget(box)

    def _pick_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Profil Fotoğrafı Seç", "", "Resimler (*.jpg *.jpeg *.png);;Tümü (*)"
        )
        if path:
            self.profile_photo.setText(path)

    def start_profile(self):
        accs = self._require_accounts()
        if not accs:
            return
        first = self.profile_first.text().strip()
        last = self.profile_last.text().strip()
        about = self.profile_about.text().strip()
        photo = self.profile_photo.text().strip()
        if not (first or last or about or photo):
            QMessageBox.information(self, "Bilgi", "En az bir alan (ad/soyad/bio/foto) girin.")
            return
        self.profile_start_btn.setEnabled(False)
        self.profile_progress.setVisible(True)
        self.profile_progress.setRange(0, len(accs))
        self.profile_progress.setValue(0)
        self.profile_worker = ProfileUpdateWorker(
            self.db, accs,
            first_name=first or None,
            last_name=last or None,
            about=about or None,
            photo_path=photo or None,
            delay=3,
        )
        self.profile_worker.log.connect(self._log)
        self.profile_worker.progress.connect(
            lambda d, t: (self.profile_progress.setRange(0, t), self.profile_progress.setValue(d))
        )
        self.profile_worker.finished_ok.connect(
            lambda ok, err: self._simple_finish(self.profile_start_btn, self.profile_progress,
                                                f"Profil güncelleme bitti — {ok} güncellendi, {err} hata.")
        )
        self.profile_worker.start()
        self._log(f"👤 {len(accs)} hesap için profil güncelleme başladı.")

    # ------------------------------------------------------------------ #
    def _simple_finish(self, btn, progress, msg):
        btn.setEnabled(True)
        progress.setRange(0, 1)
        progress.setValue(1)
        self._log(f"🏁 {msg}")
        if self.main_window:
            self.main_window.set_status(msg)
