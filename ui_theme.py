"""
InfoHub design tokens — ported from the InfoHub DMS frontend
(frontend/src/index.css + tailwind.config.js, "Azul profesional" theme).
Single source of truth for colors so the Flet panel matches the web app.
"""

import flet as ft

# Surfaces
BG_PRIMARY = "#0d1520"   # app background
BG_SECONDARY = "#16202e"  # cards / panels / chat
BG_INPUT = "#1e2a3b"  # inputs, action menus
BG_POPUP = "#0a111b"  # popups, snackbars
BG_CONTAINER = "#16202e"

# Accent
ACCENT = "#3b82f6"
ACCENT_HOVER = "#60a5fa"
ACCENT_DEEP = "#2563eb"
ACCENT_SOFT = "#93c5fd"
ACCENT_DIM = "#263449"  # secondary buttons
ACCENT_WASH = "#1e2a3b"  # hover wash / chips

# Text
TEXT = "#ffffff"
TEXT_2 = "#a3b2c8"
TEXT_3 = "#6b7d94"
PLACEHOLDER = "#57585a"

# Lines
BORDER = "#223047"
BORDER_STRONG = "#3c506b"

# Status
OK = "#4ade80"
OK_DEEP = "#15803d"
WARN = "#fec84b"
WARN_DEEP = "#b45309"
DANGER = "#f04438"
DANGER_DEEP = "#b42318"
TEAL = "#0ba5ec"

RADIUS = 8

BORDER_SIDE = ft.border.BorderSide(1, BORDER)
BORDER_TOP = ft.border.Border.only(top=ft.border.BorderSide(1, BORDER))
BORDER_BOTTOM = ft.border.Border.only(bottom=ft.border.BorderSide(1, BORDER))

SHAPE = ft.RoundedRectangleBorder(radius=RADIUS)


def page_theme() -> ft.Theme:
    """Flet theme matching the DMS dark palette."""
    return ft.Theme(
        color_scheme_seed=ACCENT,
        use_material3=True,
        font_family=None,  # ponytail: keep system font, DMS uses Plus Jakarta Sans (not bundled)
        color_scheme=ft.ColorScheme(
            primary=ACCENT,
            on_primary=TEXT,
            secondary=ACCENT_HOVER,
            surface=BG_SECONDARY,
            on_surface=TEXT,
            error=DANGER,
        ),
    )


def card(content, *, padding=20, col=None):
    """Flat bordered surface, same as a DMS home card (no Material elevation)."""
    return ft.Card(
        content=ft.Container(
            content=content,
            padding=padding,
            border_radius=RADIUS,
            bgcolor=BG_SECONDARY,
            border=ft.border.Border.all(1, BORDER),
        ),
        elevation=0,
        col=col,
    )


def textfield(**kw):
    """Dark input matching --theme-settings-input-bg / chat-input border."""
    kw.setdefault("border_color", BORDER_STRONG)
    kw.setdefault("focused_border_color", ACCENT)
    kw.setdefault("color", TEXT)
    kw.setdefault("bgcolor", BG_INPUT)
    kw.setdefault("cursor_color", ACCENT)
    return ft.TextField(**kw)


def dropdown(**kw):
    kw.setdefault("border_color", BORDER_STRONG)
    kw.setdefault("focused_border_color", ACCENT)
    kw.setdefault("color", TEXT)
    kw.setdefault("bgcolor", BG_INPUT)
    return ft.Dropdown(**kw)


def primary_button(label, icon=None, on_click=None, **kw):
    return ft.FilledButton(
        label,
        icon=icon,
        on_click=on_click,
        style=ft.ButtonStyle(
            bgcolor=ACCENT,
            color=TEXT,
            shape=SHAPE,
            padding=ft.padding.Padding.symmetric(horizontal=16, vertical=10),
        ),
        **kw,
    )


def dialog(title, content, actions, *, width=None, height=None):
    return ft.AlertDialog(
        modal=True,
        bgcolor=BG_SECONDARY,
        title=ft.Text(title, size=18, weight=ft.FontWeight.BOLD, color=TEXT),
        content=ft.Container(content=content, width=width, height=height),
        actions=actions,
        actions_alignment=ft.MainAxisAlignment.END,
    )
