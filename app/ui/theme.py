"""主题：默认跟随系统深浅色。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

_LIGHT_QSS = """
QMainWindow, QDialog, QWidget#CentralRoot { background: #f4f5f7; color: #1f2328; }
QMenuBar, QStatusBar { background: #f4f5f7; }
QFrame#Sidebar, QFrame#RightPanel { background: #ebeef2; border: none; }
QFrame#ReadoutCard, QFrame#TrendCard {
    background: #ffffff;
    border: 1px solid #d8dde5;
    border-radius: 10px;
}
QFrame#ErrorBanner {
    background: #fff1f0;
    border: 1px solid #f0b4ae;
    border-radius: 8px;
}
QLabel#SectionTitle { color: #5a6472; font-size: 12px; font-weight: 600; }
QLabel#Muted { color: #6b7280; }
QLabel#ValueLabel { color: #111827; }
QLabel#UnitLabel { color: #374151; }
QLabel#FunctionBadge {
    background: #e8f0fe; color: #1d4ed8;
    border-radius: 5px; padding: 3px 9px; font-weight: 600; font-size: 18px;
}
QLabel#StatusChip {
    background: #eceff3; color: #7a8491;
    border-radius: 9px; padding: 1px 8px; font-size: 11px;
}
QLabel#StatusChip[active="true"] { background: #dbeafe; color: #1d4ed8; }
QLabel#StatusChip[alarm="true"] { background: #fee2e2; color: #b91c1c; }
QLabel#StatusChip:disabled { background: #f0f2f5; color: #b3bac3; }
QLabel#FunctionBadge:disabled { background: #f0f2f5; color: #b3bac3; }
QPushButton {
    background: #ffffff; border: 1px solid #cfd6df; border-radius: 6px;
    padding: 6px 12px;
}
QPushButton:hover { background: #f7f9fc; border-color: #9aa5b4; }
QPushButton:disabled { color: #a0a7b1; background: #f0f2f5; }
QPushButton#PrimaryButton {
    background: #2563eb; color: #ffffff; border: none; font-weight: 600;
}
QPushButton#PrimaryButton:hover { background: #1d4ed8; }
QPushButton#PrimaryButton:disabled { background: #a9bce8; color: #eef2ff; }
QPushButton#RecordButton:checked, QPushButton#AverageButton:checked,
QPushButton#FloatingButton:checked {
    background: #2563eb; color: #ffffff; border-color: #2563eb; font-weight: 600;
}
QPushButton#RecordButton:checked:hover, QPushButton#AverageButton:checked:hover,
QPushButton#FloatingButton:checked:hover {
    background: #1d4ed8;
}
QPushButton#StartButton {
    background: #16a34a; color: #ffffff; border: none; font-weight: 600;
}
QPushButton#StartButton:hover { background: #15803d; }
QPushButton#StartButton:disabled { background: #86c99a; color: #f0fdf4; }
QPushButton#StopButton {
    background: #dc2626; color: #ffffff; border: none; font-weight: 600;
}
QPushButton#StopButton:hover { background: #b91c1c; }
QPushButton#FunctionButton { padding: 5px 4px; font-weight: 600; font-size: 18px; }
QPushButton#FunctionButton:checked {
    background: #2563eb; color: #ffffff; border-color: #2563eb;
}
QPushButton#FunctionButton:checked:hover { background: #1d4ed8; }
QPushButton#AutoRangeButton:checked, QPushButton#NullButton:checked {
    background: #2563eb; color: #ffffff; border-color: #2563eb;
}
QComboBox, QLineEdit {
    background: #ffffff; border: 1px solid #cfd6df; border-radius: 5px;
    padding: 4px 7px; min-height: 20px;
}
QComboBox:disabled, QLineEdit:disabled { color: #9aa1ab; background: #f0f2f5; }
QComboBox QAbstractItemView {
    background: #eef2f7;
    color: #1f2328;
    border: 1px solid #cfd6df;
    outline: 0;
    selection-background-color: #dbeafe;
    selection-color: #1f2328;
}
QComboBox QAbstractItemView::item {
    background: #eef2f7;
    min-height: 22px;
    padding: 3px 7px;
}
QComboBox QAbstractItemView::item:hover {
    background: #dbeafe;
    color: #1f2328;
}
QComboBox QAbstractItemView::item:selected {
    background: #dbeafe;
    color: #1f2328;
}
QGroupBox {
    border: 1px solid #d8dde5; border-radius: 8px;
    margin-top: 10px; padding-top: 8px; font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #5a6472; }
QFrame#CollapsibleSection {
    border: 1px solid #d8dde5; border-radius: 8px;
    background: transparent;
}
QToolButton#CollapsibleHeader {
    border: none; background: transparent; text-align: left;
    padding: 6px 8px; color: #5a6472; font-weight: 600;
}
QToolButton#CollapsibleHeader:hover { background: #eef2f7; border-radius: 7px; }
QStatusBar { color: #5f6875; }
QToolTip { background: #1f2937; color: #ffffff; border: none; padding: 4px; }
QMenuBar::item:selected { background: #e2e8f0; }
"""

_DARK_QSS = """
QMainWindow, QDialog, QWidget#CentralRoot { background: #171a1f; color: #e5e7eb; }
QMenuBar, QStatusBar { background: #171a1f; }
QFrame#Sidebar, QFrame#RightPanel { background: #1e2228; border: none; }
QFrame#ReadoutCard, QFrame#TrendCard {
    background: #20252c;
    border: 1px solid #343b45;
    border-radius: 10px;
}
QFrame#ErrorBanner {
    background: #3a1d1d;
    border: 1px solid #8f3d3d;
    border-radius: 8px;
}
QLabel#SectionTitle { color: #9aa4b2; font-size: 12px; font-weight: 600; }
QLabel#Muted { color: #98a2b3; }
QLabel#ValueLabel { color: #f3f4f6; }
QLabel#UnitLabel { color: #d1d5db; }
QLabel#FunctionBadge {
    background: #1e3a5f; color: #93c5fd;
    border-radius: 5px; padding: 3px 9px; font-weight: 600; font-size: 18px;
}
QLabel#StatusChip {
    background: #2b313a; color: #8d97a5;
    border-radius: 9px; padding: 1px 8px; font-size: 11px;
}
QLabel#StatusChip[active="true"] { background: #1e3a5f; color: #93c5fd; }
QLabel#StatusChip[alarm="true"] { background: #4a1f1f; color: #fca5a5; }
QLabel#StatusChip:disabled { background: #262a30; color: #6b7280; }
QLabel#FunctionBadge:disabled { background: #262a30; color: #6b7280; }
QPushButton {
    background: #262c34; border: 1px solid #3d4652; border-radius: 6px;
    padding: 6px 12px;
}
QPushButton:hover { background: #2e3640; border-color: #66758a; }
QPushButton:disabled { color: #6b7280; background: #222831; }
QPushButton#PrimaryButton {
    background: #2563eb; color: #ffffff; border: none; font-weight: 600;
}
QPushButton#PrimaryButton:hover { background: #3b82f6; }
QPushButton#PrimaryButton:disabled { background: #2f4d86; color: #a9bce8; }
QPushButton#RecordButton:checked, QPushButton#AverageButton:checked,
QPushButton#FloatingButton:checked {
    background: #3b82f6; color: #ffffff; border-color: #3b82f6; font-weight: 600;
}
QPushButton#RecordButton:checked:hover, QPushButton#AverageButton:checked:hover,
QPushButton#FloatingButton:checked:hover {
    background: #2563eb;
}
QPushButton#StartButton {
    background: #16a34a; color: #ffffff; border: none; font-weight: 600;
}
QPushButton#StartButton:hover { background: #22c55e; }
QPushButton#StartButton:disabled { background: #2f6b47; color: #c7f9d8; }
QPushButton#StopButton {
    background: #dc2626; color: #ffffff; border: none; font-weight: 600;
}
QPushButton#StopButton:hover { background: #ef4444; }
QPushButton#FunctionButton { padding: 5px 4px; font-weight: 600; font-size: 18px; }
QPushButton#FunctionButton:checked {
    background: #2563eb; color: #ffffff; border-color: #2563eb;
}
QPushButton#FunctionButton:checked:hover { background: #3b82f6; }
QPushButton#AutoRangeButton:checked, QPushButton#NullButton:checked {
    background: #2563eb; color: #ffffff; border-color: #2563eb;
}
QComboBox, QLineEdit {
    background: #20252c; border: 1px solid #3d4652; border-radius: 5px;
    padding: 4px 7px; min-height: 20px;
}
QComboBox:disabled, QLineEdit:disabled { color: #6b7280; background: #222831; }
QComboBox QAbstractItemView {
    background: #20252c;
    color: #e5e7eb;
    border: 1px solid #3d4652;
    outline: 0;
    selection-background-color: #1e3a5f;
    selection-color: #e5e7eb;
}
QComboBox QAbstractItemView::item {
    background: #20252c;
    min-height: 22px;
    padding: 3px 7px;
}
QComboBox QAbstractItemView::item:hover {
    background: #2e3640;
    color: #f3f4f6;
}
QComboBox QAbstractItemView::item:selected {
    background: #1e3a5f;
    color: #e5e7eb;
}
QGroupBox {
    border: 1px solid #343b45; border-radius: 8px;
    margin-top: 10px; padding-top: 8px; font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9aa4b2; }
QFrame#CollapsibleSection {
    border: 1px solid #343b45; border-radius: 8px;
    background: transparent;
}
QToolButton#CollapsibleHeader {
    border: none; background: transparent; text-align: left;
    padding: 6px 8px; color: #9aa4b2; font-weight: 600;
}
QToolButton#CollapsibleHeader:hover { background: #232a33; border-radius: 7px; }
QStatusBar { color: #9aa4b2; }
QToolTip { background: #f9fafb; color: #111827; border: none; padding: 4px; }
QMenuBar::item:selected { background: #2b313a; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    hints = app.styleHints()
    dark = hints.colorScheme() == Qt.ColorScheme.Dark
    palette = QPalette()
    if dark:
        palette.setColor(QPalette.ColorRole.Window, QColor("#171a1f"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#e5e7eb"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#20252c"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#262c34"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#e5e7eb"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#262c34"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e5e7eb"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#2563eb"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    else:
        palette.setColor(QPalette.ColorRole.Window, QColor("#f4f5f7"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#1f2328"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f7f9fc"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#1f2328"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#1f2328"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#2563eb"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    app.setStyleSheet(_DARK_QSS if dark else _LIGHT_QSS)
    app.setFont(QFont("Microsoft YaHei UI", 10))
