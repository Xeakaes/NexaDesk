"""Dark/light theme token palettes and QSS builder (spec: gui-renewal §4)."""

from __future__ import annotations

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0D0D0D",
        "bg_alt": "#181818",
        "surface": "#1F1F1F",
        "surface_hover": "#272727",
        "border": "#2E2E2E",
        "input_border": "#6E6E74",
        "fg": "#F2F2F2",
        "fg_muted": "#8E8E93",
        "accent": "#F87171",
        "accent_hover": "#FA8A8A",
        "bubble_user": "#2A1B1B",
        "bubble_assistant": "#1F1F1F",
        "danger": "#DC2626",
        "on_accent": "#1A0E0E",
        "on_danger": "#FFFFFF",
    },
    "light": {
        "bg": "#F6F6F7",
        "bg_alt": "#FFFFFF",
        "surface": "#FFFFFF",
        "surface_hover": "#EFEFF1",
        "border": "#E2E2E5",
        "input_border": "#8E8E93",
        "fg": "#17171A",
        "fg_muted": "#6B6B70",
        "accent": "#D1433B",
        "accent_hover": "#B93530",
        "bubble_user": "#FDECEC",
        "bubble_assistant": "#FFFFFF",
        "danger": "#C93636",
        "on_accent": "#FFFFFF",
        "on_danger": "#FFFFFF",
    },
}

REQUIRED_OBJECTNAMES: tuple[str, ...] = (
    "main",
    "sidebar",
    "chat",
    "msg_area",
    "chat_input",
    "msg_user",
    "msg_assistant",
    "msg_tool",
    "bubble",
    "settings_win",
    "new_chat",
    "sessions_header",
    "empty_state",
    "outline",
)


def qss(theme_name: str) -> str:
    if theme_name not in THEMES:
        raise ValueError(f"unknown theme: {theme_name}")
    t = THEMES[theme_name]
    return f"""
QWidget#main {{ background: {t['bg']}; color: {t['fg']};
    font-family: Nunito, sans-serif; }}
QFrame#sidebar {{ background: {t['bg_alt']}; border-right: 1px solid {t['border']}; }}
QLabel#sessions_header {{ color: {t['fg_muted']}; font-weight: bold;
    padding: 4px 8px; }}
QPushButton#new_chat {{ background: {t['accent']}; color: {t['on_accent']};
    border: 2px solid {t['accent']}; border-radius: 14px; padding: 6px 12px; }}
QPushButton#new_chat:hover {{ background: {t['accent_hover']};
    border-color: {t['accent_hover']}; }}
QPushButton#new_chat:focus {{ border-color: {t['fg']}; }}
QFrame#sidebar QPushButton {{ background: transparent; color: {t['fg']};
    border: 2px solid transparent; border-radius: 10px; padding: 6px 10px;
    text-align: left; }}
QFrame#sidebar QPushButton:hover {{ background: {t['surface_hover']}; }}
QFrame#sidebar QPushButton:focus {{ border-color: {t['accent']}; }}
QListWidget {{ background: {t['bg']}; color: {t['fg']};
    border: 1px solid {t['border']}; border-radius: 10px; }}
QListWidget::item {{ padding: 8px; border-radius: 10px; }}
QListWidget::item:hover {{ background: {t['surface_hover']}; }}
QListWidget::item:selected {{ background: {t['accent']}; color: {t['on_accent']}; }}
QScrollArea#chat {{ background: {t['bg']}; border: none; }}
QWidget#msg_area {{ background: {t['bg']}; }}
QFrame#empty_state {{ background: transparent; border: none; }}
QFrame#msg_user {{ background: {t['bubble_user']}; border-radius: 14px; }}
QFrame#msg_assistant {{ background: {t['bubble_assistant']}; border-radius: 14px; }}
QFrame#msg_tool {{ background: {t['surface_hover']}; border-radius: 10px; }}
QPlainTextEdit#chat_input, QLineEdit {{ background: {t['surface']};
    color: {t['fg']}; border: 2px solid {t['input_border']};
    border-radius: 10px; padding: 6px 10px; }}
QPlainTextEdit#chat_input:focus, QLineEdit:focus {{ border-color: {t['accent']}; }}
QLabel {{ color: {t['fg']}; background: transparent; }}
QLabel#muted {{ color: {t['fg_muted']}; }}
QDialog, QMessageBox {{ background: {t['bg']}; color: {t['fg']}; }}
QTextEdit {{ background: {t['surface']}; color: {t['fg']};
    border: 1px solid {t['border']}; border-radius: 8px; }}
QPushButton {{ background: {t['accent']}; color: {t['on_accent']};
    border: 2px solid {t['accent']}; border-radius: 10px; padding: 8px 16px; }}
QPushButton:hover {{ background: {t['accent_hover']}; border-color: {t['accent_hover']}; }}
QPushButton:focus {{ border-color: {t['fg']}; }}
QPushButton:disabled {{ background: {t['surface_hover']}; color: {t['fg_muted']};
    border-color: {t['surface_hover']}; }}
QPushButton#danger {{ background: {t['danger']}; color: {t['on_danger']};
    border-color: {t['danger']}; }}
QPushButton#danger:hover {{ background: {t['danger']}; border-color: {t['on_danger']}; }}
QPushButton#outline {{ background: transparent; color: {t['fg']};
    border: 2px solid {t['input_border']}; border-radius: 10px; padding: 8px 16px; }}
QPushButton#outline:hover {{ background: {t['surface_hover']}; }}
QPushButton#outline:focus {{ border-color: {t['accent']}; }}
QPushButton[outline="true"] {{ background: transparent; color: {t['fg']};
    border: 2px solid {t['input_border']}; border-radius: 10px; padding: 8px 16px; }}
QPushButton[outline="true"]:hover {{ background: {t['surface_hover']}; }}
QPushButton[outline="true"]:focus {{ border-color: {t['accent']}; }}
QPushButton#attach_plus {{ background: transparent; color: {t['fg_muted']};
    border: none; border-radius: 8px; padding: 0px; font-weight: bold; }}
QPushButton#attach_plus:hover {{ background: {t['surface_hover']};
    color: {t['fg']}; }}
QPushButton#attach_plus:focus {{ color: {t['accent']}; }}
QFrame#bubble {{ background: {t['bg_alt']}; border: 1px solid {t['border']};
    border-radius: 14px; }}
QFrame#bubble QPlainTextEdit, QFrame#bubble QLineEdit {{ background: {t['bg']};
    color: {t['fg']}; border: 2px solid {t['input_border']}; border-radius: 10px; }}
QFrame#bubble QPlainTextEdit:focus, QFrame#bubble QLineEdit:focus {{
    border-color: {t['accent']}; }}
QFrame#bubble QPushButton {{ background: {t['accent']}; color: {t['on_accent']};
    border-color: {t['accent']}; }}
QWidget#settings_win {{ background: {t['bg']}; color: {t['fg']};
    font-family: Nunito, sans-serif; }}
QTabWidget::pane {{ border: 1px solid {t['border']}; background: {t['bg']};
    top: -1px; }}
QTabBar::tab {{ background: {t['bg_alt']}; color: {t['fg_muted']};
    border: 1px solid {t['border']}; border-bottom: none;
    border-top-left-radius: 8px; border-top-right-radius: 8px;
    padding: 8px 16px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {t['bg']}; color: {t['accent']}; }}
QTabBar::tab:hover {{ background: {t['surface_hover']}; }}
QComboBox {{ background: {t['surface']}; color: {t['fg']};
    border: 2px solid {t['input_border']}; border-radius: 10px; padding: 4px 8px; }}
QComboBox:focus {{ border-color: {t['accent']}; }}
QComboBox:hover {{ background: {t['surface_hover']}; }}
QMenu {{ background: {t['bg_alt']}; color: {t['fg']};
    border: 1px solid {t['border']}; border-radius: 10px; padding: 4px; }}
QMenu::item {{ padding: 6px 24px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['accent']}; color: {t['on_accent']}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {t['surface_hover']};
    border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {t['input_border']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {t['surface_hover']};
    border-radius: 4px; min-width: 24px; }}
QScrollBar::handle:horizontal:hover {{ background: {t['input_border']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
"""


def apply_theme(app, theme_name: str) -> None:
    app.setStyleSheet(qss(theme_name))
