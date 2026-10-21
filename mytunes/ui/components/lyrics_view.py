from __future__ import annotations
from mytunes.ui.dialog_utils import safe_update
import flet as ft
from typing import Callable, List
from mytunes.enrichment.lyrics import LyricsEngine, LyricsLine
from mytunes.models.track import Track

class LyricsView(ft.Container):
    """Component rendering real-time synchronized karaoke-style lyrics."""

    def __init__(self, page: ft.Page, on_seek: Callable[[float], None]):
        super().__init__()
        self.app_page = page
        self.on_seek = on_seek
        self.lyrics_engine = LyricsEngine()
        self.lines: List[LyricsLine] = []
        self.plain_lyrics: str = ""
        self.active_index: int = -1
        self.is_loading: bool = False
        self.auto_follow = True
        self.line_scroll_keys: List[ft.ScrollKey] = []

        self.lyrics_column = ft.Column(
            scroll=ft.ScrollMode.AUTO,
            spacing=16,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            expand=True,
            on_scroll=self._on_scroll
        )
        self.resume_auto_scroll_button = ft.TextButton(
            "Resume auto-scroll",
            visible=False,
            on_click=self._resume_auto_scroll
        )

        self.content = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [self.resume_auto_scroll_button],
                        alignment=ft.MainAxisAlignment.CENTER
                    ),
                    self.lyrics_column
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True
            ),
            alignment=ft.Alignment.CENTER,
            padding=30,
            expand=True
        )
        self.expand = True

    def load_for_track(self, track: Track) -> None:
        """Loads lyrics for a new track asynchronously."""
        self.lines.clear()
        self.plain_lyrics = ""
        self.active_index = -1
        self.is_loading = True
        self.auto_follow = True
        self.resume_auto_scroll_button.visible = False

        self.lyrics_column.controls = [
            ft.ProgressRing(),
            ft.Text("Searching lyrics on LRCLIB...", size=14, color=ft.Colors.GREY_400)
        ]
        safe_update(self)

        # In production this can run via thread/task
        lines, plain = self.lyrics_engine.fetch_lyrics(
            track_title=track.title,
            artist=track.artist,
            album=track.album,
            duration=track.duration
        )
        self.lines = lines
        self.plain_lyrics = plain
        self.is_loading = False

        self._render_lyrics()

    def _render_lyrics(self) -> None:
        self.lyrics_column.controls.clear()

        if self.lines:
            self.line_scroll_keys = [
                ft.ScrollKey(f"lyric-line-{i}") for i in range(len(self.lines))
            ]
            # Synced lyrics line by line
            for i, line in enumerate(self.lines):
                text_ctrl = ft.Text(
                    line.text,
                    key=self.line_scroll_keys[i],
                    size=18,
                    weight=ft.FontWeight.W_400,
                    color=ft.Colors.GREY_500,
                    text_align=ft.TextAlign.CENTER,
                    selectable=True,
                    animate_opacity=300,
                    on_tap=lambda *_, lyric_line=line: self._seek_to_line(lyric_line)
                )
                self.lyrics_column.controls.append(text_ctrl)
        elif self.plain_lyrics:
            self.line_scroll_keys = []
            # Plain un-synced lyrics
            self.lyrics_column.controls.append(
                ft.Text(
                    self.plain_lyrics,
                    size=16,
                    color=ft.Colors.WHITE,
                    text_align=ft.TextAlign.CENTER
                )
            )
        else:
            self.line_scroll_keys = []
            self.lyrics_column.controls.append(
                ft.Text(
                    "No lyrics found for this track.",
                    size=16,
                    color=ft.Colors.GREY_500,
                    italic=True
                )
            )
        safe_update(self)

    def update_position(self, current_seconds: float) -> None:
        """Updates the active highlight in synced lyrics according to audio progress."""
        if not self.lines or self.is_loading:
            return

        new_idx = self.lyrics_engine.get_active_line_index(self.lines, current_seconds)
        if new_idx != self.active_index and 0 <= new_idx < len(self.lyrics_column.controls):
            # Unhighlight previous
            if 0 <= self.active_index < len(self.lyrics_column.controls):
                prev_ctrl = self.lyrics_column.controls[self.active_index]
                if isinstance(prev_ctrl, ft.Text):
                    prev_ctrl.size = 18
                    prev_ctrl.weight = ft.FontWeight.W_400
                    prev_ctrl.color = ft.Colors.GREY_500

            # Highlight current line
            self.active_index = new_idx
            curr_ctrl = self.lyrics_column.controls[self.active_index]
            if isinstance(curr_ctrl, ft.Text):
                curr_ctrl.size = 24
                curr_ctrl.weight = ft.FontWeight.BOLD
                curr_ctrl.color = ft.Colors.BLUE_400  # Will adapt to theme accent

            safe_update(self)
            if self.auto_follow:
                self.app_page.run_task(self._scroll_to_line, new_idx)

    def _on_scroll(self, event: ft.OnScrollEvent) -> None:
        if self.lines and event.event_type == ft.ScrollType.USER and self.auto_follow:
            self.auto_follow = False
            self.resume_auto_scroll_button.visible = True
            safe_update(self)

    def _resume_auto_scroll(self) -> None:
        self.auto_follow = True
        self.resume_auto_scroll_button.visible = False
        safe_update(self)
        if 0 <= self.active_index < len(self.lines):
            self.app_page.run_task(self._scroll_to_line, self.active_index)

    async def _scroll_to_line(self, index: int) -> None:
        if self.auto_follow and 0 <= index < len(self.lines):
            await self.lyrics_column.scroll_to(
                scroll_key=self.line_scroll_keys[index],
                duration=350
            )

    def _seek_to_line(self, line: LyricsLine) -> None:
        self.on_seek(line.time_seconds)
        self.update_position(line.time_seconds)
