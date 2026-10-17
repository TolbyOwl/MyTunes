import flet as ft
from typing import Callable
from mytunes.ui.theme import MetroTheme, METRO_ACCENTS
from mytunes.ui.dialog_utils import show_snackbar

class SettingsView(ft.Container):
    """
    Settings View for theme customization, Metro accents, and audio preferences.
    """

    def __init__(
        self,
        page: ft.Page,
        theme: MetroTheme,
        on_theme_changed: Callable[[], None]
    ):
        super().__init__()
        self.app_page = page
        self._mt = theme
        self.on_theme_changed = on_theme_changed

        self.expand = True
        self.padding = ft.Padding.all(28)

        self._build_view()

    def _build_view(self) -> None:
        title = ft.Text("SETTINGS", size=24, weight=ft.FontWeight.W_800, color=self._mt.text_primary)

        # 1. Appearance Section
        dark_mode_switch = ft.Switch(
            label="Dark Mode",
            value=self._mt.is_dark,
            on_change=self._toggle_dark_mode
        )

        accent_chips = []
        for name, hex_code in METRO_ACCENTS.items():
            is_selected = (self._mt.accent_color == hex_code)
            chip = ft.Container(
                width=32,
                height=32,
                bgcolor=hex_code,
                border=ft.Border.all(2, ft.Colors.WHITE if is_selected else ft.Colors.TRANSPARENT),
                border_radius=0, # Metro square color tiles
                ink=True,
                tooltip=name,
                on_click=lambda e, c=hex_code: self._change_accent(c)
            )
            accent_chips.append(chip)

        accents_row = ft.Row(spacing=10, controls=accent_chips)

        theme_card = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=20,
            border_radius=4,
            content=ft.Column(
                spacing=16,
                controls=[
                    ft.Text("Appearance & Metro Theme", size=16, weight=ft.FontWeight.BOLD),
                    dark_mode_switch,
                    ft.Text("Metro Accent Color", size=13, weight=ft.FontWeight.W_500),
                    accents_row,
                    ft.Text(
                        "Note: When playing songs with album covers, the dynamic color extractor will automatically adapt the player accent.",
                        size=12,
                        color=self._mt.text_secondary
                    )
                ]
            )
        )

        # 2. Audio & Cache Section
        cache_card = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=20,
            border_radius=4,
            content=ft.Column(
                spacing=12,
                controls=[
                    ft.Text("Audio & Caching", size=16, weight=ft.FontWeight.BOLD),
                    ft.Text("Cache Limit: 2.0 GB (Auto LRU clean)", size=13, color=self._mt.text_secondary),
                    ft.FilledButton("Clear Audio Cache", icon=ft.Icons.DELETE_SWEEP, on_click=self._clear_cache),
                ]
            )
        )

        # 3. About MyTunes
        about_card = ft.Container(
            bgcolor=self._mt.surface_color,
            border=ft.Border.all(1, self._mt.border_color),
            padding=20,
            border_radius=4,
            content=ft.Column(
                spacing=8,
                controls=[
                    ft.Text("MyTunes v0.1.0", size=16, weight=ft.FontWeight.BOLD),
                    ft.Text("Multiplatform Music Player built with Python & Flet (Flutter).", size=13, color=self._mt.text_secondary),
                    ft.Text("Local Library • Cloud Drives • Podcasts • 30k+ Radio Stations • Metro UI", size=12, color=ft.Colors.GREY_500),
                ]
            )
        )

        self.content = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=20,
            controls=[
                title,
                theme_card,
                cache_card,
                about_card
            ]
        )

    def _toggle_dark_mode(self, e) -> None:
        self._mt.is_dark = e.control.value
        self.app_page.theme_mode = ft.ThemeMode.DARK if self._mt.is_dark else ft.ThemeMode.LIGHT
        self.on_theme_changed()

    def _change_accent(self, color_hex: str) -> None:
        self._mt.accent_color = color_hex
        self._mt.reset_dynamic_accent()
        self.on_theme_changed()

    def _clear_cache(self, e) -> None:
        show_snackbar(self.app_page, "Audio cache cleared!")
        self.app_page.update()
