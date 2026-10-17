import flet as ft
from typing import Callable, Optional
from mytunes.core.audio import AudioEngine
from mytunes.ui.dialog_utils import open_dialog, close_dialog

class SleepTimerDialog:
    """Modal dialog for setting the sleep timer with the 'Finish current song' toggle."""

    def __init__(self, page: ft.Page, audio_engine: AudioEngine):
        self.page = page
        self.audio = audio_engine
        self.dialog: Optional[ft.AlertDialog] = None
        self.selected_minutes = 30
        self.finish_current_song_val = True  # Default recommended

    def show(self) -> None:
        state = self.audio.sleep_state

        # Status text if already active
        status_text = ""
        if state.is_active:
            mins = state.remaining_seconds // 60
            secs = state.remaining_seconds % 60
            mode_desc = " (will finish current track)" if state.finish_current_song else ""
            status_text = f"Timer currently active: {mins:02d}:{secs:02d} remaining{mode_desc}"
            if state.pending_finish:
                status_text = "Timer expired! Finishing current song..."

        status_label = ft.Text(
            status_text,
            size=13,
            color=ft.Colors.AMBER_400 if state.is_active else ft.Colors.TRANSPARENT,
            weight=ft.FontWeight.W_500
        )

        # Minutes preset buttons
        preset_row = ft.Row(
            spacing=8,
            controls=[
                self._build_preset_chip(15),
                self._build_preset_chip(30),
                self._build_preset_chip(45),
                self._build_preset_chip(60),
            ]
        )

        # Custom minute field
        custom_input = ft.TextField(
            label="Custom (minutes)",
            value=str(self.selected_minutes),
            width=140,
            text_size=14,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=self._on_custom_change
        )

        # "Finish Current Song" switch
        finish_switch = ft.Switch(
            label="Finish current song before sleeping",
            value=self.finish_current_song_val,
            on_change=lambda e: setattr(self, "finish_current_song_val", e.control.value),
            tooltip="When timer reaches 0, playback won't cut off abruptly; it will finish playing the current track."
        )

        # Actions
        start_btn = ft.FilledButton(
            "Start Timer",
            icon=ft.Icons.BEDTIME,
            on_click=lambda e: self._start_timer(custom_input.value)
        )

        cancel_btn = ft.OutlinedButton(
            "Cancel Timer",
            icon=ft.Icons.STOP,
            visible=state.is_active,
            on_click=self._cancel_timer
        )

        close_btn = ft.TextButton("Close", on_click=lambda e: self._close())

        self.dialog = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.BEDTIME, color=ft.Colors.BLUE_400),
                ft.Text("Sleep Timer", weight=ft.FontWeight.BOLD, size=20)
            ]),
            content=ft.Column(
                tight=True,
                spacing=16,
                controls=[
                    status_label,
                    ft.Text("Stop playback after:", size=14, weight=ft.FontWeight.W_600),
                    preset_row,
                    custom_input,
                    ft.Divider(height=1),
                    finish_switch,
                    ft.Text(
                        "Tips: If enabled, the player lets the current song play to completion when the timer hits zero.",
                        size=12,
                        color=ft.Colors.GREY_400
                    )
                ]
            ),
            actions=[cancel_btn, start_btn, close_btn],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        open_dialog(self.page, self.dialog)

    def _build_preset_chip(self, minutes: int) -> ft.FilledTonalButton:
        return ft.FilledTonalButton(
            f"{minutes}m",
            on_click=lambda e, m=minutes: self._select_preset(m)
        )

    def _select_preset(self, minutes: int) -> None:
        self.selected_minutes = minutes
        if self.dialog and self.dialog.content:
            for control in self.dialog.content.controls:
                if isinstance(control, ft.TextField):
                    control.value = str(minutes)
        self.page.update()

    def _on_custom_change(self, e) -> None:
        try:
            val = int(e.control.value)
            if val > 0:
                self.selected_minutes = val
        except ValueError:
            pass

    def _start_timer(self, minutes_str: str) -> None:
        try:
            mins = int(minutes_str)
        except ValueError:
            mins = self.selected_minutes

        self.audio.start_sleep_timer(
            minutes=mins,
            finish_current_song=self.finish_current_song_val
        )
        self._close()

    def _cancel_timer(self, e) -> None:
        self.audio.cancel_sleep_timer()
        self._close()

    def _close(self) -> None:
        close_dialog(self.page, self.dialog)
