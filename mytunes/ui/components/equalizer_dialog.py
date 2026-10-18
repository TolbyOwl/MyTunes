import flet as ft
from typing import Dict, List, Optional
from mytunes.ui.dialog_utils import open_dialog, close_dialog

EQ_FREQUENCIES = ["32Hz", "64Hz", "125Hz", "250Hz", "500Hz", "1kHz", "2kHz", "4kHz", "8kHz", "16kHz"]

EQ_PRESETS: Dict[str, List[float]] = {
    "Flat": [0.0] * 10,
    "Bass Boost": [6.0, 5.0, 4.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "Rock": [4.0, 3.0, 2.0, 0.0, -1.0, -1.0, 0.0, 2.0, 3.0, 4.0],
    "Pop": [-1.0, 1.0, 3.0, 4.0, 3.0, 0.0, -1.0, -1.0, 1.0, 2.0],
    "Vocal": [-2.0, -2.0, -1.0, 2.0, 4.0, 4.0, 3.0, 1.0, 0.0, -2.0],
    "Acoustic": [3.0, 3.0, 2.0, 1.0, 2.0, 2.0, 3.0, 3.0, 2.0, 1.0],
    "Electronic": [5.0, 4.0, 2.0, 0.0, -2.0, 2.0, 1.0, 2.0, 4.0, 5.0],
}

class EqualizerDialog:
    """10-Band Graphic Equalizer modal with presets."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.dialog: Optional[ft.AlertDialog] = None
        self.current_preset = "Flat"
        self.band_values: List[float] = list(EQ_PRESETS["Flat"])
        self.sliders: List[ft.Slider] = []

    def show(self) -> None:
        self.sliders.clear()

        # Build vertical frequency sliders
        band_columns = []
        for i, freq in enumerate(EQ_FREQUENCIES):
            slider = ft.Slider(
                min=-12.0,
                max=12.0,
                divisions=24,
                value=self.band_values[i],
                label="{value} dB",
                height=160,
                active_color=ft.Colors.BLUE_400,
                on_change=lambda e, idx=i: self._on_slider_change(idx, e.control.value)
            )
            self.sliders.append(slider)

            band_columns.append(
                ft.Column(
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=4,
                    controls=[
                        ft.Text(f"{self.band_values[i]:+.0f}", size=11, color=ft.Colors.GREY_400),
                        ft.Container(content=slider, height=140),
                        ft.Text(freq, size=10, weight=ft.FontWeight.W_600),
                    ]
                )
            )

        slider_row = ft.Row(
            spacing=10,
            alignment=ft.MainAxisAlignment.CENTER,
            controls=band_columns
        )

        preset_dropdown = ft.Dropdown(
            label="Preset",
            value=self.current_preset,
            options=[ft.dropdown.Option(name) for name in EQ_PRESETS.keys()],
            width=200,
            on_select=self._on_preset_change
        )

        reset_btn = ft.TextButton("Reset to Flat", on_click=lambda e: self._apply_preset("Flat"))
        close_btn = ft.FilledButton("Done", on_click=lambda e: self._close())

        self.dialog = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.EQUALIZER, color=ft.Colors.BLUE_400),
                ft.Text("Graphic Equalizer", weight=ft.FontWeight.BOLD, size=20)
            ]),
            content=ft.Column(
                tight=True,
                spacing=16,
                controls=[
                    ft.Row([preset_dropdown, reset_btn], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    slider_row,
                ]
            ),
            actions=[close_btn],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        open_dialog(self.page, self.dialog)

    def _on_slider_change(self, index: int, val: float) -> None:
        self.band_values[index] = val
        self.current_preset = "Custom"
        self.page.update()

    def _on_preset_change(self, e) -> None:
        self._apply_preset(e.control.value)

    def _apply_preset(self, preset_name: str) -> None:
        if preset_name in EQ_PRESETS:
            self.current_preset = preset_name
            self.band_values = list(EQ_PRESETS[preset_name])
            for i, val in enumerate(self.band_values):
                if i < len(self.sliders):
                    self.sliders[i].value = val
            self.page.update()

    def _close(self) -> None:
        close_dialog(self.page, self.dialog)
