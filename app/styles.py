"""
TGraph - Karanlık Tema (QSS)
Cgraph benzeri renk paleti kullanılır.
"""
from .config import COLORS


def get_stylesheet() -> str:
    c = COLORS
    return f"""
/* ---------- Genel ---------- */
QMainWindow, QDialog {{
    background-color: {c['bg']};
}}

QWidget {{
    background-color: {c['bg']};
    color: {c['text']};
    font-family: "Segoe UI", "Arial", sans-serif;
    font-size: 13px;
}}

QToolTip {{
    background-color: {c['panel2']};
    color: {c['text']};
    border: 1px solid {c['accent']};
    padding: 4px;
    border-radius: 4px;
}}

/* ---------- Kart / Panel ---------- */
QFrame#Card, QFrame#Panel {{
    background-color: {c['panel']};
    border-radius: 10px;
    border: 1px solid {c['panel2']};
}}

QFrame#Sidebar {{
    background-color: {c['panel']};
    border: none;
}}

/* ---------- Etiket ---------- */
QLabel {{
    background: transparent;
    color: {c['text']};
}}

QLabel#Title {{
    font-size: 22px;
    font-weight: bold;
    color: {c['text']};
}}

QLabel#Subtitle {{
    font-size: 13px;
    color: {c['text_secondary']};
}}

QLabel#PageTitle {{
    font-size: 20px;
    font-weight: bold;
    color: {c['text']};
    padding: 4px 0px;
}}

QLabel#Logo {{
    font-size: 26px;
    font-weight: bold;
    color: {c['accent']};
}}

QLabel#SecondaryText {{
    color: {c['text_secondary']};
    font-size: 12px;
}}

/* ---------- Butonlar ---------- */
QPushButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {c['accent']}, stop:1 {c['accent_dark']});
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
    min-height: 18px;
}}

QPushButton:hover {{
    background-color: {c['accent']};
}}

QPushButton:pressed {{
    background-color: {c['accent_dark']};
}}

QPushButton:disabled {{
    background-color: #3a3a4e;
    color: #6a6a7e;
}}

QPushButton#Secondary {{
    background: {c['panel2']};
    color: {c['text']};
}}
QPushButton#Secondary:hover {{
    background: {c['hover']};
}}

QPushButton#Success {{
    background: {c['success']};
    color: #06231a;
}}
QPushButton#Danger {{
    background: {c['error']};
    color: white;
}}

/* ---------- Sidebar Navigasyon Butonları ---------- */
QPushButton#NavButton {{
    background: transparent;
    color: {c['text_secondary']};
    border: none;
    border-radius: 8px;
    padding: 12px 16px;
    text-align: left;
    font-size: 14px;
    font-weight: normal;
}}
QPushButton#NavButton:hover {{
    background: {c['panel2']};
    color: {c['text']};
}}
QPushButton#NavButton:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['accent']}, stop:1 {c['accent_dark']});
    color: white;
    font-weight: bold;
}}

/* ---------- Giriş Alanları ---------- */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {c['input_bg']};
    border: 1px solid {c['panel2']};
    border-radius: 6px;
    padding: 7px 10px;
    color: {c['text']};
    selection-background-color: {c['accent']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {c['accent']};
}}
QLineEdit:disabled {{
    color: {c['text_secondary']};
}}

/* ---------- ComboBox ---------- */
QComboBox {{
    background-color: {c['input_bg']};
    border: 1px solid {c['panel2']};
    border-radius: 6px;
    padding: 7px 10px;
    color: {c['text']};
    min-height: 18px;
}}
QComboBox:hover {{
    border: 1px solid {c['accent']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {c['text_secondary']};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {c['panel']};
    border: 1px solid {c['panel2']};
    selection-background-color: {c['accent']};
    color: {c['text']};
    outline: none;
}}

/* ---------- SpinBox ---------- */
QSpinBox, QDoubleSpinBox {{
    background-color: {c['input_bg']};
    border: 1px solid {c['panel2']};
    border-radius: 6px;
    padding: 6px 8px;
    color: {c['text']};
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {c['accent']};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: {c['panel2']};
    border: none;
    width: 16px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: {c['hover']};
}}

/* ---------- CheckBox ---------- */
QCheckBox {{
    spacing: 8px;
    color: {c['text']};
    background: transparent;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid {c['panel2']};
    background: {c['input_bg']};
}}
QCheckBox::indicator:checked {{
    background: {c['accent']};
    border: 1px solid {c['accent']};
}}

/* ---------- RadioButton ---------- */
QRadioButton {{
    spacing: 8px;
    color: {c['text']};
    background: transparent;
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 9px;
    border: 1px solid {c['panel2']};
    background: {c['input_bg']};
}}
QRadioButton::indicator:checked {{
    background: {c['accent']};
    border: 3px solid {c['input_bg']};
}}

/* ---------- Tablo ---------- */
QTableWidget, QTableView {{
    background-color: {c['panel']};
    alternate-background-color: {c['input_bg']};
    gridline-color: {c['panel2']};
    border: 1px solid {c['panel2']};
    border-radius: 8px;
    color: {c['text']};
    selection-background-color: {c['hover']};
    selection-color: {c['text']};
    outline: none;
}}
QTableWidget::item, QTableView::item {{
    padding: 4px;
    border: none;
}}
QTableWidget::item:selected {{
    background: {c['hover']};
}}
QHeaderView::section {{
    background-color: {c['panel2']};
    color: {c['text']};
    padding: 8px;
    border: none;
    font-weight: bold;
}}
QHeaderView::section:horizontal {{
    border-right: 1px solid {c['bg']};
}}
QTableCornerButton::section {{
    background-color: {c['panel2']};
    border: none;
}}

/* ---------- ProgressBar ---------- */
QProgressBar {{
    background-color: {c['input_bg']};
    border: 1px solid {c['panel2']};
    border-radius: 8px;
    text-align: center;
    color: {c['text']};
    height: 22px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['accent']}, stop:1 {c['accent_dark']});
    border-radius: 7px;
}}

/* ---------- ScrollBar ---------- */
QScrollBar:vertical {{
    background: {c['bg']};
    width: 12px;
    margin: 0px;
    border-radius: 6px;
}}
QScrollBar::handle:vertical {{
    background: {c['panel2']};
    min-height: 30px;
    border-radius: 6px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c['accent']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: {c['bg']};
    height: 12px;
    margin: 0px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal {{
    background: {c['panel2']};
    min-width: 30px;
    border-radius: 6px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {c['accent']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ---------- TabWidget ---------- */
QTabWidget::pane {{
    border: 1px solid {c['panel2']};
    border-radius: 8px;
    background: {c['panel']};
    top: -1px;
}}
QTabBar::tab {{
    background: {c['panel']};
    color: {c['text_secondary']};
    padding: 10px 20px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {c['accent']};
    color: white;
    font-weight: bold;
}}
QTabBar::tab:hover:!selected {{
    background: {c['panel2']};
    color: {c['text']};
}}

/* ---------- GroupBox ---------- */
QGroupBox {{
    background-color: {c['panel']};
    border: 1px solid {c['panel2']};
    border-radius: 8px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0px 6px;
    color: {c['accent']};
}}

/* ---------- ListWidget ---------- */
QListWidget {{
    background-color: {c['input_bg']};
    border: 1px solid {c['panel2']};
    border-radius: 8px;
    color: {c['text']};
    outline: none;
}}
QListWidget::item {{
    padding: 8px;
    border-radius: 4px;
}}
QListWidget::item:selected {{
    background: {c['hover']};
    color: {c['text']};
}}
QListWidget::item:hover {{
    background: {c['panel2']};
}}

/* ---------- StatusBar ---------- */
QStatusBar {{
    background: {c['panel']};
    color: {c['text_secondary']};
    border-top: 1px solid {c['panel2']};
}}
QStatusBar::item {{
    border: none;
}}

/* ---------- Menu ---------- */
QMenu {{
    background-color: {c['panel']};
    border: 1px solid {c['panel2']};
    color: {c['text']};
}}
QMenu::item:selected {{
    background-color: {c['accent']};
}}
"""
