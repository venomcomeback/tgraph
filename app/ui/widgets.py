"""
TGraph - Ortak UI yardımcıları
"""
from PySide6.QtWidgets import QTableWidgetItem, QLabel
from PySide6.QtGui import QColor, QBrush
from PySide6.QtCore import Qt

from ..config import COLORS, STATUS_LABELS, STATUS_OK, STATUS_SPAM, STATUS_BANNED


STATUS_COLORS = {
    STATUS_OK: COLORS["success"],
    STATUS_SPAM: COLORS["warning"],
    STATUS_BANNED: COLORS["error"],
    "unknown": COLORS["text_secondary"],
    "Hazır": COLORS["text_secondary"],
    "Ekliyor": COLORS["success"],
    "Spam!": COLORS["warning"],
}


def status_item(status: str) -> QTableWidgetItem:
    """Renkli durum hücresi döndürür."""
    label = STATUS_LABELS.get(status, status)
    item = QTableWidgetItem(label)
    color = STATUS_COLORS.get(status, COLORS["text"])
    item.setForeground(QBrush(QColor(color)))
    item.setTextAlignment(Qt.AlignCenter)
    return item


def text_item(text, center=False) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text) if text is not None else "")
    if center:
        item.setTextAlignment(Qt.AlignCenter)
    return item


def make_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("PageTitle")
    return lbl
