"""
Tokens de diseño de InfoHub File Manager según el manual de marca KnowHub v1.0
(octubre 2026). Interfaz de producto: blanco/crema + tinta, acento violeta InfoHub,
índigo solo para la firma «by KnowHub». Misma paleta que InfoHub Chat y DMS
(~/desarrollo/knowhub_assets/marca/marca.css).
"""

import flet as ft

# Marca (manual pág. 03)
TINTA = "#14152E"
CREMA = "#FBF6E3"
INDIGO = "#4B4FC4"
VIOLETA = "#7B61FF"          # símbolo, foco, indicadores
VIOLETA_OSC = "#5A42D6"      # botones con texto blanco (6,6:1) y textos de acento
VIOLETA_VELO = "#EFEBFF"

# Superficies
BG_PRIMARY = CREMA       # fondo de la app
BG_SECONDARY = "#FFFFFF"  # tarjetas / paneles
BG_INPUT = "#FFFFFF"      # campos
BG_POPUP = TINTA          # snackbars (texto crema)
BG_CONTAINER = "#FFFFFF"

# Acento
ACCENT = VIOLETA_OSC
ACCENT_HOVER = VIOLETA_OSC  # íconos y textos de acento sobre fondo claro
ACCENT_DEEP = "#4A33BD"
ACCENT_SOFT = "#A695FF"
ACCENT_DIM = "#F2EBD1"      # botones secundarios
ACCENT_WASH = VIOLETA_VELO  # chips / hover
ON_ACCENT = "#FFFFFF"       # texto e íconos sobre ACCENT y colores de estado

# Texto
TEXT = TINTA
TEXT_2 = "#5A5B70"
TEXT_3 = "#7A7B8C"
PLACEHOLDER = "#8E8FA0"
ON_POPUP = CREMA

# Líneas
BORDER = "#E3DCC0"
BORDER_STRONG = "#C9C7BB"

# Estados (texto sobre claro con contraste AA; *_DEEP como fondo con texto blanco)
OK = "#127A4A"
OK_DEEP = "#127A4A"
WARN = "#B54708"
WARN_DEEP = "#B54708"
DANGER = "#B42318"
DANGER_DEEP = "#B42318"
TEAL = VIOLETA_OSC  # acento único por producto: las tarjetas informativas van en violeta

# Tipografía (manual pág. 04). Registrar con page.fonts = FONTS.
FONT_SANS = "IBM Plex Sans"
FONT_TITULO = "Space Grotesk"
FONT_MONO = "IBM Plex Mono"
FONTS = {
    FONT_SANS: "fonts/IBMPlexSans-Regular.ttf",
    FONT_TITULO: "fonts/SpaceGrotesk-SemiBold.ttf",
    FONT_MONO: "fonts/IBMPlexMono-Medium.ttf",
}

RADIUS = 8

BORDER_SIDE = ft.border.BorderSide(1, BORDER)
BORDER_TOP = ft.border.Border.only(top=ft.border.BorderSide(1, BORDER))
BORDER_BOTTOM = ft.border.Border.only(bottom=ft.border.BorderSide(1, BORDER))

SHAPE = ft.RoundedRectangleBorder(radius=RADIUS)


def page_theme() -> ft.Theme:
    """Tema claro de la marca InfoHub."""
    return ft.Theme(
        color_scheme_seed=VIOLETA,
        use_material3=True,
        font_family=FONT_SANS,
        color_scheme=ft.ColorScheme(
            primary=ACCENT,
            on_primary=ON_ACCENT,
            secondary=ACCENT_HOVER,
            surface=BG_SECONDARY,
            on_surface=TEXT,
            error=DANGER,
        ),
    )


_LOGO = ft.TextStyle(letter_spacing=-0.8)  # −4,5 % del cuerpo (manual pág. 06)


def brand(subtitle):
    """Imagotipo: símbolo InfoHub + nombre (Space Grotesk) + «by KnowHub» (Plex Mono, índigo)."""
    return ft.Row(
        [
            ft.Image(src="marca/infohub-simbolo.svg", width=46, height=24),
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("InfoHub", size=18, font_family=FONT_TITULO, color=TEXT, style=_LOGO),
                            ft.Text(subtitle, size=18, font_family=FONT_TITULO, color=TEXT_2, style=_LOGO),
                        ],
                        spacing=5,
                    ),
                    ft.Text("by KnowHub", size=11, font_family=FONT_MONO, color=INDIGO),
                ],
                spacing=0,
                tight=True,
            ),
        ],
        spacing=12,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
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
    """Campo con borde de la marca y foco violeta."""
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
            color=ON_ACCENT,
            shape=SHAPE,
            padding=ft.padding.Padding.symmetric(horizontal=16, vertical=10),
        ),
        **kw,
    )


def dialog(title, content, actions, *, width=None, height=None):
    return ft.AlertDialog(
        modal=True,
        bgcolor=BG_SECONDARY,
        title=ft.Text(title, size=18, font_family=FONT_TITULO, color=TEXT),
        content=ft.Container(content=content, width=width, height=height),
        actions=actions,
        actions_alignment=ft.MainAxisAlignment.END,
    )
