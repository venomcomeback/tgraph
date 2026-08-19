"""
TGraph - Telegram Grup Yöneticisi
Giriş noktası.
"""
import sys
import os

# Proje kök dizinini path'e ekle (exe için)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QSplashScreen, QLabel
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QColor, QPainter, QFont

from app.config import APP_NAME, APP_VERSION, COLORS
from app.styles import get_stylesheet
from app.database import Database
from app.ui.main_window import MainWindow


def make_splash() -> QSplashScreen:
    pix = QPixmap(480, 260)
    pix.fill(QColor(COLORS["bg"]))
    painter = QPainter(pix)
    # Başlık
    painter.setPen(QColor(COLORS["accent"]))
    painter.setFont(QFont("Segoe UI", 44, QFont.Bold))
    painter.drawText(pix.rect().adjusted(0, -30, 0, -30), Qt.AlignCenter, "TGraph")
    # Alt yazı
    painter.setPen(QColor(COLORS["text_secondary"]))
    painter.setFont(QFont("Segoe UI", 12))
    painter.drawText(pix.rect().adjusted(0, 70, 0, 70), Qt.AlignCenter,
                     f"Telegram Grup Yöneticisi  •  v{APP_VERSION}")
    painter.setPen(QColor(COLORS["text_secondary"]))
    painter.setFont(QFont("Segoe UI", 10))
    painter.drawText(pix.rect().adjusted(0, 105, 0, 105), Qt.AlignCenter, "Yükleniyor...")
    painter.end()
    splash = QSplashScreen(pix)
    splash.setWindowFlag(Qt.WindowStaysOnTopHint)
    return splash


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(get_stylesheet())

    splash = make_splash()
    splash.show()
    app.processEvents()

    # Veritabanı başlat
    db = Database()

    window = MainWindow(db)

    def show_main():
        window.show()
        splash.finish(window)

    QTimer.singleShot(1200, show_main)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
