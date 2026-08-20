"""
TGraph - Hesap Yönetimi Sayfası
"""
import os
import shutil

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QLineEdit, QComboBox, QFormLayout, QLabel, QMessageBox,
    QFileDialog, QCheckBox, QAbstractItemView, QPlainTextEdit, QListWidget,
)
from PySide6.QtCore import Qt

from ..database import Database
from ..config import SESSIONS_DIR, STATUS_UNKNOWN, STATUS_OK, STATUS_LABELS
from ..telegram_client import TGClient, session_path
from .. import cgraph_compat
from .. import bulk_utils
from ..workers.login_worker import (
    SendCodeWorker, SignInWorker, ConnectCheckWorker, BulkImportSessionsWorker,
)
from .widgets import status_item, text_item, make_title


class AddAccountDialog(QDialog):
    """API ID/Hash + telefon ile giriş diyalogu (OTP + 2FA)."""

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Hesap Ekle")
        self.setMinimumWidth(400)
        self.tg_client = None
        self.phone_code_hash = None
        self.result_account = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.api_id_input = QLineEdit()
        self.api_id_input.setPlaceholderText("Örn: 1234567")
        self.api_hash_input = QLineEdit()
        self.api_hash_input.setPlaceholderText("API Hash")
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("+90...")
        self.proxy_combo = QComboBox()
        self.proxy_combo.addItem("Proxy Yok", None)
        for p in self.db.get_proxies():
            self.proxy_combo.addItem(f"{p['proxy_type']}://{p['host']}:{p['port']}", p["id"])

        form.addRow("API ID:", self.api_id_input)
        form.addRow("API Hash:", self.api_hash_input)
        form.addRow("Telefon:", self.phone_input)
        form.addRow("Proxy:", self.proxy_combo)
        layout.addLayout(form)

        # Kod + 2FA alanları (başta gizli)
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Telegram'dan gelen kod")
        self.code_label = QLabel("Doğrulama Kodu:")
        self.code_input.setVisible(False)
        self.code_label.setVisible(False)
        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.Password)
        self.pass_input.setPlaceholderText("İki adımlı doğrulama şifresi")
        self.pass_label = QLabel("2FA Şifresi:")
        self.pass_input.setVisible(False)
        self.pass_label.setVisible(False)
        form2 = QFormLayout()
        form2.addRow(self.code_label, self.code_input)
        form2.addRow(self.pass_label, self.pass_input)
        layout.addLayout(form2)

        self.status_label = QLabel("")
        self.status_label.setObjectName("SecondaryText")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        btns = QHBoxLayout()
        self.action_btn = QPushButton("Kod Gönder")
        self.action_btn.clicked.connect(self.on_action)
        cancel_btn = QPushButton("İptal")
        cancel_btn.setObjectName("Secondary")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)
        btns.addWidget(self.action_btn)
        layout.addLayout(btns)

        self.step = 1  # 1: kod gönder, 2: giriş yap

    def _proxy(self):
        pid = self.proxy_combo.currentData()
        return self.db.get_proxy(pid) if pid else None

    def on_action(self):
        if self.step == 1:
            self.send_code()
        else:
            self.do_sign_in()

    def send_code(self):
        api_id = self.api_id_input.text().strip()
        api_hash = self.api_hash_input.text().strip()
        phone = self.phone_input.text().strip()
        if not (api_id and api_hash and phone):
            QMessageBox.warning(self, "Eksik Bilgi", "API ID, API Hash ve telefon zorunludur.")
            return
        session_name = phone.replace("+", "").replace(" ", "")
        self.session_name = session_name
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.action_btn.setEnabled(False)
        self.status_label.setText("Kod gönderiliyor...")

        self.send_worker = SendCodeWorker(session_name, api_id, api_hash, phone, self._proxy())
        self.send_worker.code_sent.connect(self.on_code_sent)
        self.send_worker.error.connect(self.on_error)
        self.send_worker.start()

    def on_code_sent(self, phone_code_hash):
        self.phone_code_hash = phone_code_hash
        self.tg_client = self.send_worker.client
        self.code_label.setVisible(True)
        self.code_input.setVisible(True)
        self.pass_label.setVisible(True)
        self.pass_input.setVisible(True)
        self.action_btn.setText("Giriş Yap")
        self.action_btn.setEnabled(True)
        self.status_label.setText("Kod gönderildi. Lütfen kodu girin (2FA varsa şifreyi de).")
        self.step = 2

    def do_sign_in(self):
        code = self.code_input.text().strip()
        password = self.pass_input.text().strip()
        if not code:
            QMessageBox.warning(self, "Eksik Bilgi", "Doğrulama kodunu girin.")
            return
        self.action_btn.setEnabled(False)
        self.status_label.setText("Giriş yapılıyor...")
        self.signin_worker = SignInWorker(
            self.tg_client, self.phone, code, self.phone_code_hash, password
        )
        self.signin_worker.success.connect(self.on_success)
        self.signin_worker.need_password.connect(self.on_need_password)
        self.signin_worker.error.connect(self.on_error)
        self.signin_worker.start()

    def on_need_password(self):
        self.action_btn.setEnabled(True)
        self.status_label.setText("İki adımlı doğrulama şifresi gerekli. Lütfen 2FA şifresini girin.")

    def on_success(self, me):
        # Bağlantıyı kapat (session diske yazıldı)
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self.tg_client.disconnect())
            loop.close()
        except Exception:
            pass
        self.db.add_account(
            session_name=self.session_name,
            phone=me.get("phone", self.phone),
            name=me.get("name", ""),
            api_id=self.api_id,
            api_hash=self.api_hash,
            proxy_id=self.proxy_combo.currentData(),
            status=STATUS_OK,
        )
        self.result_account = me
        QMessageBox.information(self, "Başarılı", f"Hesap eklendi: {me.get('name') or self.phone}")
        self.accept()

    def on_error(self, msg):
        self.action_btn.setEnabled(True)
        self.status_label.setText(f"Hata: {msg}")
        QMessageBox.critical(self, "Hata", f"İşlem başarısız:\n{msg}")


class ImportSessionDialog(QDialog):
    """.session dosyasını içe aktarır (Cgraph uyumlu)."""

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Session Dosyası Yükle")
        self.setMinimumWidth(420)
        self.file_path = None

        self.is_cgsession = False  # seçilen dosya .cgsession mı?

        layout = QVBoxLayout(self)
        info = QLabel("Cgraph (.cgsession) veya Telethon (.session) dosyanızı içe aktarın.\n"
                      "• .cgsession seçerseniz API ID/Hash otomatik doldurulur ve oturum "
                      "Telethon formatına çevrilir (SMS gerekmez).\n"
                      "• Düz .session için API ID ve API Hash girmeniz gerekir.")
        info.setObjectName("SecondaryText")
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.file_label = QLabel("Dosya seçilmedi")
        file_btn = QPushButton("Dosya Seç (.cgsession / .session)")
        file_btn.setObjectName("Secondary")
        file_btn.clicked.connect(self.pick_file)
        self.api_id_input = QLineEdit()
        self.api_hash_input = QLineEdit()
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("Opsiyonel")
        self.proxy_combo = QComboBox()
        self.proxy_combo.addItem("Proxy Yok", None)
        for p in self.db.get_proxies():
            self.proxy_combo.addItem(f"{p['proxy_type']}://{p['host']}:{p['port']}", p["id"])

        form.addRow(file_btn, self.file_label)
        form.addRow("API ID:", self.api_id_input)
        form.addRow("API Hash:", self.api_hash_input)
        form.addRow("Telefon:", self.phone_input)
        form.addRow("Proxy:", self.proxy_combo)
        layout.addLayout(form)

        btns = QHBoxLayout()
        ok_btn = QPushButton("İçe Aktar")
        ok_btn.clicked.connect(self.do_import)
        cancel_btn = QPushButton("İptal")
        cancel_btn.setObjectName("Secondary")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        layout.addLayout(btns)

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Session Dosyası Seç", "",
            "Cgraph/Telethon Oturum (*.cgsession *.session);;"
            "Cgraph Oturum (*.cgsession);;Telethon Oturum (*.session);;Tüm Dosyalar (*)"
        )
        if not path:
            return
        self.file_path = path
        self.file_label.setText(os.path.basename(path))

        # .cgsession ise otomatik çöz ve API bilgilerini doldur
        self.is_cgsession = cgraph_compat.is_cgsession(path)
        if self.is_cgsession:
            try:
                info = cgraph_compat.decrypt_cgsession(path)
                self.api_id_input.setText(str(info["api_id"]))
                self.api_hash_input.setText(info["api_hash"])
                self.api_id_input.setEnabled(False)
                self.api_hash_input.setEnabled(False)
                QMessageBox.information(
                    self, "Cgraph Oturumu Algılandı",
                    "Cgraph .cgsession dosyası çözüldü.\n"
                    f"Kullanıcı ID: {info.get('user_id')}\n"
                    f"Ana DC: {info.get('main_dc')}\n\n"
                    "API bilgileri otomatik dolduruldu. 'İçe Aktar' ile devam edin."
                )
            except Exception as e:
                self.is_cgsession = False
                self.api_id_input.setEnabled(True)
                self.api_hash_input.setEnabled(True)
                QMessageBox.critical(
                    self, "Çözme Hatası",
                    f".cgsession dosyası çözülemedi:\n{e}"
                )
        else:
            self.api_id_input.setEnabled(True)
            self.api_hash_input.setEnabled(True)

    def do_import(self):
        if not self.file_path:
            QMessageBox.warning(self, "Eksik", "Lütfen bir oturum dosyası seçin.")
            return
        api_id = self.api_id_input.text().strip()
        api_hash = self.api_hash_input.text().strip()
        if not (api_id and api_hash):
            QMessageBox.warning(self, "Eksik", "API ID ve API Hash zorunludur.")
            return

        base = os.path.basename(self.file_path)
        # Uzantıyı ayıkla, oturum adını üret
        for ext in (".cgsession", ".session"):
            if base.lower().endswith(ext):
                base = base[: -len(ext)]
                break
        session_name = base
        dest = session_path(session_name) + ".session"

        try:
            if self.is_cgsession:
                # Cgraph oturumunu Telethon .session dosyasına çevir
                info = cgraph_compat.convert_cgsession_to_telethon(self.file_path, dest)
                phone = self.phone_input.text().strip()
            else:
                # Düz Telethon .session -> kopyala
                if os.path.abspath(self.file_path) != os.path.abspath(dest):
                    shutil.copy2(self.file_path, dest)
                phone = self.phone_input.text().strip()
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Oturum içe aktarılamadı:\n{e}")
            return

        self.db.add_account(
            session_name=session_name,
            phone=phone,
            name="",
            api_id=api_id,
            api_hash=api_hash,
            proxy_id=self.proxy_combo.currentData(),
            status=STATUS_UNKNOWN,
        )
        extra = ("Cgraph oturumu Telethon formatına çevrildi (SMS gerekmez).\n"
                 if self.is_cgsession else "")
        QMessageBox.information(self, "Başarılı",
                               f"Oturum içe aktarıldı: {session_name}\n{extra}"
                               "Doğrulamak için 'Tümünü Bağla' kullanın.")
        self.accept()


class BulkSessionImportDialog(QDialog):
    """Bir klasördeki tüm .cgsession / .session dosyalarını toplu içe aktarır."""

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Toplu Session Yükle")
        self.setMinimumWidth(560)
        self.setMinimumHeight(440)
        self.folder = None
        self.worker = None

        layout = QVBoxLayout(self)
        info = QLabel(
            "Bir klasör seçin. Klasör (ve bir alt klasör seviyesi) içindeki tüm "
            ".cgsession ve .session dosyaları taranır.\n"
            "• .cgsession dosyaları otomatik Telethon formatına çevrilir (API bilgileri içinden okunur).\n"
            "• Düz .session dosyaları için API bilgisi aynı klasördeki .txt dosyasından "
            "(telefon eşlemesiyle) veya aşağıdaki varsayılan API ID/Hash'ten alınır."
        )
        info.setObjectName("SecondaryText")
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.folder_label = QLabel("Klasör seçilmedi")
        folder_btn = QPushButton("Klasör Seç")
        folder_btn.setObjectName("Secondary")
        folder_btn.clicked.connect(self.pick_folder)
        self.def_api_id = QLineEdit()
        self.def_api_id.setPlaceholderText("Opsiyonel (düz .session için)")
        self.def_api_hash = QLineEdit()
        self.def_api_hash.setPlaceholderText("Opsiyonel (düz .session için)")
        form.addRow(folder_btn, self.folder_label)
        form.addRow("Varsayılan API ID:", self.def_api_id)
        form.addRow("Varsayılan API Hash:", self.def_api_hash)
        layout.addLayout(form)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("İşlem günlüğü burada görünecek...")
        layout.addWidget(self.log)

        btns = QHBoxLayout()
        self.start_btn = QPushButton("İçe Aktarmayı Başlat")
        self.start_btn.clicked.connect(self.start_import)
        self.start_btn.setEnabled(False)
        self.close_btn = QPushButton("Kapat")
        self.close_btn.setObjectName("Secondary")
        self.close_btn.clicked.connect(self.reject)
        btns.addWidget(self.close_btn)
        btns.addWidget(self.start_btn)
        layout.addLayout(btns)

    def pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Session Klasörü Seç", "")
        if not folder:
            return
        self.folder = folder
        self.folder_label.setText(folder)
        self.start_btn.setEnabled(True)

    def _log(self, line):
        self.log.appendPlainText(line)

    def start_import(self):
        if not self.folder:
            QMessageBox.warning(self, "Eksik", "Lütfen bir klasör seçin.")
            return
        self.start_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        existing = [a["session_name"] for a in self.db.get_accounts()]
        self.worker = BulkImportSessionsWorker(
            self.db, self.folder, existing,
            self.def_api_id.text().strip(), self.def_api_hash.text().strip(),
        )
        self.worker.progress.connect(self._log)
        self.worker.finished_summary.connect(self.on_finished)
        self.worker.start()

    def on_finished(self, imported, skipped, errors):
        self.close_btn.setEnabled(True)
        self.close_btn.setText("Kapat ve Yenile")
        self.imported = imported
        QMessageBox.information(
            self, "Toplu İçe Aktarma Tamamlandı",
            f"{imported} içe aktarıldı, {skipped} atlandı, {errors} hata."
        )


class BulkPhoneLoginDialog(QDialog):
    """TXT dosyasındaki numaralarla sırayla (kod girişi ile) giriş yapar."""

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("TXT'den Numaralarla Giriş")
        self.setMinimumWidth(600)
        self.setMinimumHeight(560)

        self.records = []          # parse edilmiş {phone, api_id, api_hash}
        self.index = -1            # işlenmekte olan numara indeksi
        self.tg_client = None
        self.phone_code_hash = None
        self.success_count = 0
        self.fail_count = 0
        self.send_worker = None
        self.signin_worker = None

        layout = QVBoxLayout(self)
        info = QLabel(
            "Bir .txt dosyası seçin. Her satır: telefon | telefon:api_id:api_hash | "
            "api_id:api_hash:telefon (ayraç otomatik algılanır).\n"
            "Yalnız telefon içeren satırlar için aşağıdaki Varsayılan API ID/Hash kullanılır.\n"
            "Giriş sırasında Telegram'ın gönderdiği kodu her numara için elle girmeniz gerekir."
        )
        info.setObjectName("SecondaryText")
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.file_label = QLabel("Dosya seçilmedi")
        file_btn = QPushButton("TXT Dosyası Seç")
        file_btn.setObjectName("Secondary")
        file_btn.clicked.connect(self.pick_file)
        self.def_api_id = QLineEdit()
        self.def_api_id.setPlaceholderText("Yalnız telefonlu satırlar için gerekli")
        self.def_api_hash = QLineEdit()
        self.def_api_hash.setPlaceholderText("Yalnız telefonlu satırlar için gerekli")
        self.proxy_combo = QComboBox()
        self.proxy_combo.addItem("Proxy Yok", None)
        for p in self.db.get_proxies():
            self.proxy_combo.addItem(f"{p['proxy_type']}://{p['host']}:{p['port']}", p["id"])
        form.addRow(file_btn, self.file_label)
        form.addRow("Varsayılan API ID:", self.def_api_id)
        form.addRow("Varsayılan API Hash:", self.def_api_hash)
        form.addRow("Proxy:", self.proxy_combo)
        layout.addLayout(form)

        self.count_label = QLabel("Numara: 0")
        self.count_label.setObjectName("SecondaryText")
        layout.addWidget(self.count_label)

        self.num_list = QListWidget()
        self.num_list.setMaximumHeight(120)
        layout.addWidget(self.num_list)

        # Kod + 2FA giriş alanı (başta gizli)
        code_form = QFormLayout()
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Telegram'dan gelen kod")
        self.code_label = QLabel("Kod:")
        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.Password)
        self.pass_input.setPlaceholderText("2FA şifresi (gerekiyorsa)")
        self.pass_label = QLabel("2FA Şifresi:")
        code_form.addRow(self.code_label, self.code_input)
        code_form.addRow(self.pass_label, self.pass_input)
        layout.addLayout(code_form)
        self._set_code_visible(False)

        self.status_label = QLabel("")
        self.status_label.setObjectName("SecondaryText")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        layout.addWidget(self.log)

        btns = QHBoxLayout()
        self.start_btn = QPushButton("Girişi Başlat")
        self.start_btn.clicked.connect(self.start_flow)
        self.start_btn.setEnabled(False)
        self.confirm_btn = QPushButton("Kodu Onayla / Sonraki")
        self.confirm_btn.clicked.connect(self.confirm_code)
        self.confirm_btn.setVisible(False)
        self.skip_btn = QPushButton("Bu Numarayı Atla")
        self.skip_btn.setObjectName("Secondary")
        self.skip_btn.clicked.connect(self.skip_current)
        self.skip_btn.setVisible(False)
        self.close_btn = QPushButton("Kapat")
        self.close_btn.setObjectName("Secondary")
        self.close_btn.clicked.connect(self.reject)
        btns.addWidget(self.close_btn)
        btns.addWidget(self.skip_btn)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.confirm_btn)
        layout.addLayout(btns)

    # ------------------------------------------------------------------ #
    def _set_code_visible(self, visible):
        for w in (self.code_label, self.code_input, self.pass_label, self.pass_input):
            w.setVisible(visible)

    def _log(self, line):
        self.log.appendPlainText(line)

    def _proxy(self):
        pid = self.proxy_combo.currentData()
        return self.db.get_proxy(pid) if pid else None

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Numara Listesi Seç", "", "Metin Dosyası (*.txt);;Tüm Dosyalar (*)"
        )
        if not path:
            return
        self.file_label.setText(os.path.basename(path))
        try:
            self.records = bulk_utils.parse_credentials_txt(path)
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Dosya okunamadı:\n{e}")
            return
        self.num_list.clear()
        for rec in self.records:
            cred = "API: dosyadan" if (rec.get("api_id") and rec.get("api_hash")) else "API: varsayılan gerekli"
            self.num_list.addItem(f"{rec['phone']}   ({cred})")
        self.count_label.setText(f"Numara: {len(self.records)}")
        self.start_btn.setEnabled(len(self.records) > 0)

    def start_flow(self):
        if not self.records:
            QMessageBox.warning(self, "Eksik", "Lütfen numara içeren bir .txt seçin.")
            return
        self.start_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.index = -1
        self._next_number()

    def _resolve_creds(self, rec):
        api_id = rec.get("api_id") or self.def_api_id.text().strip()
        api_hash = rec.get("api_hash") or self.def_api_hash.text().strip()
        return api_id, api_hash

    def _next_number(self):
        # Bir önceki istemciyi kapat
        self._disconnect_client()
        self.index += 1
        self._set_code_visible(False)
        self.confirm_btn.setVisible(False)
        self.skip_btn.setVisible(False)
        self.code_input.clear()
        self.pass_input.clear()

        if self.index >= len(self.records):
            self._finish()
            return

        rec = self.records[self.index]
        self.num_list.setCurrentRow(self.index)
        phone = rec["phone"]
        api_id, api_hash = self._resolve_creds(rec)
        self.status_label.setText(f"[{self.index + 1}/{len(self.records)}] {phone} — kod gönderiliyor...")

        if not (api_id and api_hash):
            self._log(f"❌ {phone}: API ID/Hash yok (Varsayılan alanları doldurun) — atlandı.")
            self.fail_count += 1
            self._next_number()
            return

        self.cur_phone = phone
        self.cur_api_id = api_id
        self.cur_api_hash = api_hash
        self.cur_session = bulk_utils.phone_key(phone) or phone.replace("+", "")

        self._log(f"📨 {phone}: kod gönderiliyor...")
        self.send_worker = SendCodeWorker(
            self.cur_session, api_id, api_hash, phone, self._proxy()
        )
        self.send_worker.code_sent.connect(self.on_code_sent)
        self.send_worker.error.connect(self.on_send_error)
        self.send_worker.start()

    def on_code_sent(self, phone_code_hash):
        self.phone_code_hash = phone_code_hash
        self.tg_client = self.send_worker.client
        self._set_code_visible(True)
        self.confirm_btn.setVisible(True)
        self.confirm_btn.setEnabled(True)
        self.skip_btn.setVisible(True)
        self.status_label.setText(
            f"[{self.index + 1}/{len(self.records)}] {self.cur_phone} — kod bekleniyor. "
            "Kodu girin (2FA varsa şifreyi de) ve onaylayın."
        )
        self._log(f"⏳ {self.cur_phone}: kod bekleniyor...")

    def on_send_error(self, msg):
        self._log(f"❌ {self.cur_phone}: kod gönderilemedi — {msg}")
        self.fail_count += 1
        self._next_number()

    def confirm_code(self):
        code = self.code_input.text().strip()
        password = self.pass_input.text().strip()
        if not code:
            QMessageBox.warning(self, "Eksik", "Doğrulama kodunu girin.")
            return
        self.confirm_btn.setEnabled(False)
        self.status_label.setText(f"{self.cur_phone} — giriş yapılıyor...")
        self.signin_worker = SignInWorker(
            self.tg_client, self.cur_phone, code, self.phone_code_hash, password
        )
        self.signin_worker.success.connect(self.on_signin_success)
        self.signin_worker.need_password.connect(self.on_need_password)
        self.signin_worker.error.connect(self.on_signin_error)
        self.signin_worker.start()

    def on_need_password(self):
        self.confirm_btn.setEnabled(True)
        self.status_label.setText(f"{self.cur_phone} — 2FA gerekli. Şifreyi girip tekrar onaylayın.")
        self._log(f"🔐 {self.cur_phone}: 2FA gerekli.")

    def on_signin_success(self, me):
        self._disconnect_client()
        self.db.add_account(
            session_name=self.cur_session,
            phone=me.get("phone", self.cur_phone),
            name=me.get("name", ""),
            api_id=self.cur_api_id,
            api_hash=self.cur_api_hash,
            proxy_id=self.proxy_combo.currentData(),
            status=STATUS_OK,
        )
        self.success_count += 1
        self._log(f"✅ {self.cur_phone}: giriş başarılı ({me.get('name') or ''}).")
        self._next_number()

    def on_signin_error(self, msg):
        self.confirm_btn.setEnabled(True)
        self._log(f"❌ {self.cur_phone}: giriş başarısız — {msg}")
        self.fail_count += 1
        self._next_number()

    def skip_current(self):
        self._log(f"⏭️ {self.cur_phone}: atlandı.")
        self.fail_count += 1
        self._next_number()

    def _disconnect_client(self):
        if self.tg_client:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.tg_client.disconnect())
                loop.close()
            except Exception:
                pass
            self.tg_client = None

    def _finish(self):
        self._set_code_visible(False)
        self.confirm_btn.setVisible(False)
        self.skip_btn.setVisible(False)
        self.close_btn.setEnabled(True)
        self.close_btn.setText("Kapat ve Yenile")
        self.status_label.setText(
            f"Tamamlandı — {self.success_count} giriş başarılı, {self.fail_count} atlandı/başarısız."
        )
        self._log(
            f"🏁 Tamamlandı — {self.success_count} başarılı, {self.fail_count} atlandı/başarısız."
        )
        QMessageBox.information(
            self, "Toplu Giriş Tamamlandı",
            f"{self.success_count} giriş başarılı, {self.fail_count} atlandı/başarısız."
        )

    def reject(self):
        self._disconnect_client()
        super().reject()


class AccountsPage(QWidget):
    def __init__(self, db: Database, main_window=None):
        super().__init__()
        self.db = db
        self.main_window = main_window
        self.check_workers = []
        self._build()
        self.refresh()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        layout.addWidget(make_title("👤 Hesap Yönetimi"))

        btn_row = QHBoxLayout()
        add_btn = QPushButton("＋ Hesap Ekle")
        add_btn.clicked.connect(self.add_account)
        import_btn = QPushButton("Session Dosyası Yükle")
        import_btn.setObjectName("Secondary")
        import_btn.clicked.connect(self.import_session)
        bulk_session_btn = QPushButton("Toplu Session Yükle")
        bulk_session_btn.setObjectName("Secondary")
        bulk_session_btn.clicked.connect(self.bulk_import_sessions)
        bulk_phone_btn = QPushButton("TXT'den Numaralarla Giriş")
        bulk_phone_btn.setObjectName("Secondary")
        bulk_phone_btn.clicked.connect(self.bulk_phone_login)
        del_btn = QPushButton("Seçileni Sil")
        del_btn.setObjectName("Danger")
        del_btn.clicked.connect(self.delete_selected)
        connect_btn = QPushButton("Tümünü Bağla")
        connect_btn.setObjectName("Success")
        connect_btn.clicked.connect(self.connect_all)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(import_btn)
        btn_row.addWidget(bulk_session_btn)
        btn_row.addWidget(bulk_phone_btn)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(connect_btn)
        btn_row.addStretch()
        self.show_failed_chk = QCheckBox("Bağlantısı başarısız hesapları da göster")
        self.show_failed_chk.setChecked(False)
        self.show_failed_chk.toggled.connect(self.refresh)
        btn_row.addWidget(self.show_failed_chk)
        layout.addLayout(btn_row)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["Seç", "#", "Telefon", "İsim", "API ID", "Durum", "Proxy", "İşlem"]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

    def refresh(self):
        show_failed = self.show_failed_chk.isChecked() if hasattr(self, "show_failed_chk") else False
        if show_failed:
            accounts = self.db.get_accounts()
        else:
            accounts = self.db.get_active_accounts()
        self.table.setRowCount(len(accounts))
        for row, acc in enumerate(accounts):
            chk = QCheckBox()
            chk_wrap = QWidget()
            wl = QHBoxLayout(chk_wrap)
            wl.addWidget(chk)
            wl.setAlignment(Qt.AlignCenter)
            wl.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, 0, chk_wrap)
            chk.setProperty("account_id", acc["id"])

            self.table.setItem(row, 1, text_item(acc["id"], center=True))
            self.table.setItem(row, 2, text_item(acc.get("phone", "")))
            self.table.setItem(row, 3, text_item(acc.get("name", "")))
            self.table.setItem(row, 4, text_item(acc.get("api_id", "")))
            self.table.setItem(row, 5, status_item(acc.get("status", "unknown")))
            proxy_txt = ""
            if acc.get("proxy_host"):
                proxy_txt = f"{acc.get('proxy_type')}://{acc['proxy_host']}:{acc.get('proxy_port')}"
            self.table.setItem(row, 6, text_item(proxy_txt or "-"))

            conn_btn = QPushButton("Kes" if acc.get("is_active") else "Bağlan")
            conn_btn.setObjectName("Secondary")
            conn_btn.clicked.connect(lambda _=False, a=acc: self.toggle_connect(a))
            self.table.setCellWidget(row, 7, conn_btn)
        if self.main_window:
            self.main_window.update_account_count()

    def selected_account_ids(self):
        ids = []
        for row in range(self.table.rowCount()):
            wrap = self.table.cellWidget(row, 0)
            if wrap:
                chk = wrap.findChild(QCheckBox)
                if chk and chk.isChecked():
                    ids.append(chk.property("account_id"))
        return ids

    def add_account(self):
        dlg = AddAccountDialog(self.db, self)
        if dlg.exec():
            self.refresh()

    def import_session(self):
        dlg = ImportSessionDialog(self.db, self)
        if dlg.exec():
            self.refresh()
            self._verify_inactive_accounts()

    def bulk_import_sessions(self):
        dlg = BulkSessionImportDialog(self.db, self)
        dlg.exec()
        # İş bittikten sonra (kapatınca) tabloyu her durumda yenile
        self.refresh()
        self._verify_inactive_accounts()

    def _verify_inactive_accounts(self):
        """İçe aktarılan (bağlantısı doğrulanmamış) oturumları otomatik doğrular.
        Yalnızca bağlantısı başarılı olanlar (is_active=1) varsayılan listede görünür."""
        pending = [a for a in self.db.get_accounts() if not a.get("is_active")]
        if not pending:
            return
        if self.main_window:
            self.main_window.set_status(
                "İçe aktarılan oturumlar doğrulanıyor; yalnızca bağlantısı başarılı olanlar listede görünecek."
            )
        for acc in pending:
            proxy = self.db.get_proxy(acc["proxy_id"]) if acc.get("proxy_id") else None
            self._check_account(acc, proxy)

    def bulk_phone_login(self):
        dlg = BulkPhoneLoginDialog(self.db, self)
        dlg.exec()
        self.refresh()

    def delete_selected(self):
        ids = self.selected_account_ids()
        if not ids:
            QMessageBox.information(self, "Bilgi", "Silmek için hesap seçin (Seç kutusu).")
            return
        if QMessageBox.question(self, "Onay", f"{len(ids)} hesap silinsin mi?") != QMessageBox.Yes:
            return
        for aid in ids:
            self.db.delete_account(aid)
        self.refresh()

    def toggle_connect(self, account):
        """Tek hesabı bağla/kes (durum kontrolü)."""
        proxy = self.db.get_proxy(account["proxy_id"]) if account.get("proxy_id") else None
        if account.get("is_active"):
            self.db.update_account(account["id"], is_active=0)
            self.refresh()
            return
        self._check_account(account, proxy)

    def connect_all(self):
        accounts = self.db.get_accounts()
        if not accounts:
            QMessageBox.information(self, "Bilgi", "Kayıtlı hesap yok.")
            return
        for acc in accounts:
            proxy = self.db.get_proxy(acc["proxy_id"]) if acc.get("proxy_id") else None
            self._check_account(acc, proxy)

    def _check_account(self, account, proxy):
        worker = ConnectCheckWorker(account, proxy)
        worker.result.connect(self.on_check_result)
        worker.finished.connect(lambda w=worker: self.check_workers.remove(w) if w in self.check_workers else None)
        self.check_workers.append(worker)
        if self.main_window:
            self.main_window.set_status(f"'{account.get('name') or account['session_name']}' kontrol ediliyor...")
        worker.start()

    def on_check_result(self, account_id, ok, me, error):
        if ok:
            fields = {"is_active": 1, "status": STATUS_OK}
            if me:
                if me.get("name"):
                    fields["name"] = me["name"]
                if me.get("phone"):
                    fields["phone"] = me["phone"]
            self.db.update_account(account_id, **fields)
            if self.main_window:
                self.main_window.set_status("Hesap bağlandı.")
        else:
            self.db.update_account(account_id, is_active=0)
            if self.main_window:
                self.main_window.set_status(f"Bağlantı başarısız: {error}")
        self.refresh()
