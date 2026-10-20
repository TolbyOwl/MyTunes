from __future__ import annotations
from mytunes.ui.dialog_utils import safe_update
import flet as ft
from typing import List, Callable
from mytunes.ui.theme import MetroTheme

class PivotNav(ft.Container):
    """
    Metro Pivot Navigation Header.
    Features bold typographic section titles inspired by Zune and Groove Music.
    """

    def __init__(
        self,
        sections: List[str],
        active_index: int,
        theme: MetroTheme,
        on_section_change: Callable[[int], None]
    ):
        super().__init__()
        self.sections = sections
        self.active_index = active_index
        self._mt = theme
        self.on_section_change = on_section_change
        self.header_buttons: List[ft.Control] = []
        self.header_texts: List[ft.Text] = []
        self.header_indicators: List[ft.Container] = []
        self.fullscreen_button = ft.IconButton(
            icon=ft.Icons.FULLSCREEN,
            tooltip="Toggle fullscreen",
            icon_color=self._mt.text_secondary,
            on_click=lambda e: None,
        )

        self._build_nav()

    def _build_nav(self) -> None:
        self.padding = ft.Padding.only(left=28, right=28, top=16, bottom=12)
        self.border = ft.Border.only(bottom=ft.BorderSide(1, self._mt.border_color))
        self.bgcolor = self._mt.bg_color

        self.header_buttons.clear()
        self.header_texts.clear()
        self.header_indicators.clear()
        for idx, title in enumerate(self.sections):
            is_active = (idx == self.active_index)
            btn = self._create_pivot_item(title, idx, is_active)
            self.header_buttons.append(btn)

        self.content = ft.Row(
            spacing=32,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Row(
                    spacing=32,
                    alignment=ft.MainAxisAlignment.START,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=self.header_buttons,
                ),
                self.fullscreen_button,
            ],
        )

    def _create_pivot_item(self, title: str, index: int, is_active: bool) -> ft.Container:
        text = ft.Text(
            title.upper(),
            size=22 if is_active else 18,
            weight=ft.FontWeight.W_800 if is_active else ft.FontWeight.W_400,
            color=self._mt.current_accent if is_active else self._mt.text_secondary,
            animate_size=200,
            animate_opacity=200,
        )
        indicator = ft.Container(
            width=28 if is_active else 0,
            height=2,
            bgcolor=self._mt.current_accent,
            animate_size=ft.Animation(180, ft.AnimationCurve.EASE_OUT_CUBIC),
            animate_opacity=ft.Animation(180, ft.AnimationCurve.EASE_OUT_CUBIC),
            opacity=1 if is_active else 0,
        )
        self.header_texts.append(text)
        self.header_indicators.append(indicator)

        return ft.Container(
            content=ft.Column(
                controls=[text, indicator],
                spacing=4,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.START,
            ),
            ink=True,
            on_click=lambda e, i=index: self._on_item_click(i),
            padding=ft.Padding.symmetric(vertical=4, horizontal=6),
            border_radius=4,
        )

    def _on_item_click(self, index: int) -> None:
        if index != self.active_index:
            self.active_index = index
            self._update_styles()
            self.on_section_change(index)

    def set_active_index(self, index: int) -> None:
        if 0 <= index < len(self.sections):
            self.active_index = index
            self._update_styles()

    def set_fullscreen(self, enabled: bool) -> None:
        self.fullscreen_button.icon = (
            ft.Icons.FULLSCREEN_EXIT if enabled else ft.Icons.FULLSCREEN
        )
        self.fullscreen_button.tooltip = (
            "Exit borderless fullscreen"
            if enabled
            else "Enter borderless fullscreen"
        )
        safe_update(self.fullscreen_button)

    def _update_styles(self) -> None:
        for idx, text_ctrl in enumerate(self.header_texts):
            is_active = (idx == self.active_index)
            text_ctrl.size = 22 if is_active else 18
            text_ctrl.weight = ft.FontWeight.W_800 if is_active else ft.FontWeight.W_400
            text_ctrl.color = self._mt.current_accent if is_active else self._mt.text_secondary
            indicator = self.header_indicators[idx]
            indicator.width = 28 if is_active else 0
            indicator.opacity = 1 if is_active else 0
        safe_update(self)
