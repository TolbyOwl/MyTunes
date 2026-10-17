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
        self.header_buttons: List[ft.Container] = []

        self._build_nav()

    def _build_nav(self) -> None:
        self.padding = ft.Padding.only(left=28, right=28, top=16, bottom=12)
        self.border = ft.Border.only(bottom=ft.BorderSide(1, self._mt.border_color))
        self.bgcolor = self._mt.bg_color

        self.header_buttons.clear()
        for idx, title in enumerate(self.sections):
            is_active = (idx == self.active_index)
            btn = self._create_pivot_item(title, idx, is_active)
            self.header_buttons.append(btn)

        self.content = ft.Row(
            spacing=32,
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=self.header_buttons
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

        return ft.Container(
            content=text,
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

    def _update_styles(self) -> None:
        for idx, container in enumerate(self.header_buttons):
            is_active = (idx == self.active_index)
            text_ctrl = container.content
            if isinstance(text_ctrl, ft.Text):
                text_ctrl.size = 22 if is_active else 18
                text_ctrl.weight = ft.FontWeight.W_800 if is_active else ft.FontWeight.W_400
                text_ctrl.color = self._mt.current_accent if is_active else self._mt.text_secondary
        safe_update(self)
