"""Centralized theme constants and style helpers for the Carton UI."""


# ── Color palette ──

BG_PRIMARY = "#282c34"
BG_SECONDARY = "#1d1f23"
BG_SIDEBAR = "#21252b"
BG_HOVER = "#2c313a"
BG_CARD_HOVER = "#2c313a"

TEXT_PRIMARY = "#abb2bf"
TEXT_SECONDARY = "#7f848e"
TEXT_DIM = "#5c6370"
TEXT_HEADING = "#d7dae0"
TEXT_MUTED = "#495162"

BORDER = "#3e4452"
BORDER_LIGHT = "#353b45"
BORDER_HOVER = "#4e5666"

ACCENT_BLUE = "#4d78cc"
ACCENT_BLUE_HOVER = "#5a8ae6"
ACCENT_GREEN = "#98c379"
ACCENT_GREEN_HOVER = "#a9d487"
ACCENT_ORANGE = "#d19a66"
ACCENT_ORANGE_HOVER = "#e0a972"
ACCENT_RED = "#e06c75"
ACCENT_RED_BG = "#382025"
ACCENT_LINK = "#61afef"
ACCENT_LINK_HOVER = "#8bc4f7"

SCROLLBAR_HANDLE = "#4e5666"
SCROLLBAR_HANDLE_HOVER = "#495162"

FONT_FAMILY = '"Segoe UI", "Yu Gothic UI", sans-serif'


# ── Composite styles ──

MAIN_STYLE = """
QWidget {{
    background-color: {bg};
    color: {text};
    font-family: {font};
}}
QLineEdit {{
    background: {bg2};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 7px 12px;
    color: {text};
    font-size: 13px;
    selection-background-color: {border};
}}
QLineEdit:focus {{
    border-color: {accent};
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {scroll};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {scroll_hover};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
""".format(
    bg=BG_PRIMARY, bg2=BG_SECONDARY, text=TEXT_PRIMARY,
    border=BORDER, accent=ACCENT_BLUE, font=FONT_FAMILY,
    scroll=SCROLLBAR_HANDLE, scroll_hover=SCROLLBAR_HANDLE_HOVER,
)


def dialog_style(extra=""):
    """Base stylesheet for dialogs with standard form controls."""
    base = (
        "QDialog {{ background: {bg}; }}"
        "QLabel {{ color: {text}; font-size: 13px; }}"
        "QLineEdit {{"
        "  background: {bg2}; border: 1px solid {border};"
        "  border-radius: 4px; padding: 6px; color: {text};"
        "  font-size: 13px;"
        "}}"
        "QLineEdit:focus {{ border-color: {accent}; }}"
    ).format(bg=BG_PRIMARY, bg2=BG_SECONDARY, text=TEXT_PRIMARY,
             border=BORDER, accent=ACCENT_BLUE)
    return base + extra


def combobox_style():
    """Stylesheet for QComboBox widgets."""
    return (
        "QComboBox {{ background: {bg2}; border: 1px solid {border};"
        "  border-radius: 4px; padding: 6px; color: {text}; font-size: 13px; }}"
        "QComboBox:focus {{ border-color: {accent}; }}"
        "QComboBox QAbstractItemView {{ background: {bg2}; color: {text};"
        "  selection-background-color: {accent}; }}"
    ).format(bg2=BG_SECONDARY, border=BORDER, text=TEXT_PRIMARY, accent=ACCENT_BLUE)


def listwidget_style():
    """Stylesheet for QListWidget in settings dialogs."""
    return (
        "QListWidget {{"
        "  background: {bg2}; border: 1px solid {border};"
        "  border-radius: 4px; color: {text}; font-size: 13px;"
        "}}"
        "QListWidget::item {{ padding: 6px; }}"
        "QListWidget::item:selected {{ background: {accent}; }}"
    ).format(bg2=BG_SECONDARY, border=BORDER, text=TEXT_PRIMARY, accent=ACCENT_BLUE)


def sidebar_list_style():
    """Stylesheet for sidebar navigation list."""
    return (
        "QListWidget {{ background: transparent; border: none; outline: none; }}"
        "QListWidget::item {{ color: {dim}; padding: 6px 8px; border-radius: 4px; }}"
        "QListWidget::item:selected {{ background: {hover}; color: {orange};"
        "  border-left: 3px solid {orange}; }}"
        "QListWidget::item:hover {{ background: {hover}; }}"
    ).format(dim=TEXT_SECONDARY, hover=BG_HOVER, orange=ACCENT_ORANGE)


def sidebar_list_style_extended():
    """Extended sidebar list style with disabled item support."""
    return (
        sidebar_list_style()
        + "QListWidget::item:disabled {{ background: transparent; padding: 0; }}"
        "QListWidget::item:disabled:hover {{ background: transparent; }}"
    )


def groupbox_style():
    """Stylesheet for QGroupBox widgets."""
    return (
        "QGroupBox {{ color: {dim}; font-size: 12px; border: 1px solid {border};"
        "  border-radius: 4px; margin-top: 8px; padding-top: 16px; }}"
        "QGroupBox::title {{ subcontrol-origin: margin; left: 10px; }}"
    ).format(dim=TEXT_DIM, border=BORDER)


# ── Button styles ──

def btn_primary():
    """Blue primary action button."""
    return (
        "QPushButton {{ background: {bg}; color: white;"
        "  border: none; border-radius: 4px; padding: 6px 16px; }}"
        "QPushButton:hover {{ background: {hover}; }}"
    ).format(bg=ACCENT_BLUE, hover=ACCENT_BLUE_HOVER)


def btn_success():
    """Green success/install button."""
    return (
        "QPushButton {{ background: {bg}; color: white;"
        "  border: none; border-radius: 4px; padding: 6px 16px; }}"
        "QPushButton:hover {{ background: {hover}; }}"
    ).format(bg=ACCENT_GREEN, hover=ACCENT_GREEN_HOVER)


def btn_success_dark():
    """Green button with dark text (for contrast on green)."""
    return (
        "QPushButton {{ background: {bg}; color: {dark};"
        "  border: none; border-radius: 4px; padding: 6px 16px; }}"
        "QPushButton:hover {{ background: {hover}; }}"
    ).format(bg=ACCENT_GREEN, dark=BG_PRIMARY, hover=ACCENT_GREEN_HOVER)


def btn_danger():
    """Red danger/remove button (outlined)."""
    return (
        "QPushButton {{ color: {red}; background: transparent;"
        "  border: 1px solid {red}; border-radius: 4px; padding: 6px 12px; }}"
        "QPushButton:hover {{ background: {red_bg}; }}"
    ).format(red=ACCENT_RED, red_bg=ACCENT_RED_BG)


def btn_warning():
    """Orange warning button (outlined)."""
    return (
        "QPushButton {{ color: {orange}; background: transparent;"
        "  border: 1px solid {orange}; border-radius: 4px; padding: 6px 12px; }}"
        "QPushButton:hover {{ background: #382517; }}"
    ).format(orange=ACCENT_ORANGE)


def btn_ghost():
    """Transparent ghost button with border."""
    return (
        "QPushButton {{ background: transparent; color: {dim};"
        "  border: 1px solid {border}; border-radius: 4px; padding: 6px 16px; }}"
        "QPushButton:hover {{ background: {bg2}; }}"
    ).format(dim=TEXT_DIM, border=BORDER, bg2=BG_SECONDARY)


def btn_ghost_text():
    """Transparent ghost button with text color."""
    return (
        "QPushButton {{ background: transparent; color: {text};"
        "  border: 1px solid {border}; border-radius: 4px; padding: 6px 12px; }}"
        "QPushButton:hover {{ background: {bg2}; }}"
    ).format(text=TEXT_PRIMARY, border=BORDER, bg2=BG_SECONDARY)


def btn_muted():
    """Muted background button."""
    return (
        "QPushButton {{ background: {border}; color: {text}; border: none;"
        "  border-radius: 4px; padding: 6px 10px; }}"
        "QPushButton:hover {{ background: {border}; }}"
    ).format(border=BORDER, text=TEXT_PRIMARY)


def btn_small_browse():
    """Small browse file button."""
    return (
        "QPushButton {{ background: {bg2}; color: {dim};"
        "  border: 1px solid {border}; border-radius: 4px; padding: 4px; font-size: 12px; }}"
        "QPushButton:hover {{ background: {border}; }}"
    ).format(bg2=BG_SECONDARY, dim=TEXT_SECONDARY, border=BORDER)


def btn_link():
    """Link-style flat button."""
    return (
        "QPushButton {{ color: {link}; font-size: 12px; text-align: left;"
        "  background: transparent; border: none; padding: 0;"
        "  text-decoration: underline; }}"
        "QPushButton:hover {{ color: {hover}; }}"
    ).format(link=ACCENT_LINK, hover=ACCENT_LINK_HOVER)


def btn_outline(color, hover_bg):
    """Generic outlined button with custom color."""
    return (
        "QPushButton {{ background: transparent; color: {color};"
        "  border: 1px solid {color}; border-radius: 6px; padding: 8px; }}"
        "QPushButton:hover {{ background: {hover_bg}; }}"
    ).format(color=color, hover_bg=hover_bg)


def btn_card_action(bg, hover_bg, text_color="white", radius=6, padding=6,
                    font_size=12, font_weight=600):
    """Action button used inside cards and detail panels."""
    return (
        "QPushButton {{"
        "  background: {bg}; color: {text}; border: none;"
        "  border-radius: {r}px; padding: {p}px; font-weight: {w}; font-size: {fs}px;"
        "}}"
        "QPushButton:hover {{ background: {hover}; }}"
    ).format(bg=bg, text=text_color, hover=hover_bg, r=radius, p=padding,
             fs=font_size, w=font_weight)


def btn_card_outlined(color, border_color, hover_bg, font_size=11):
    """Outlined button for cards (publish, etc.)."""
    return (
        "QPushButton {{"
        "  background: transparent; color: {color};"
        "  border: 1px solid {border}; border-radius: 6px; padding: 4px;"
        "  font-size: {fs}px; font-weight: 600;"
        "}}"
        "QPushButton:hover {{ background: {hover}; border-color: {color}; }}"
    ).format(color=color, border=border_color, hover=hover_bg, fs=font_size)


# ── Label style helpers ──

LABEL_DIM = "color: {dim}; font-size: 12px;".format(dim=TEXT_DIM)
LABEL_DIM_BOLD = "color: {dim}; font-size: 12px; font-weight: bold;".format(dim=TEXT_DIM)
