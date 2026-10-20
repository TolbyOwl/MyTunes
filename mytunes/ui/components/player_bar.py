from __future__ import annotations
from mytunes.ui.dialog_utils import safe_update
import flet as ft
from typing import Optional, Callable
from mytunes.models.track import Track
from mytunes.core.audio import AudioEngine
from mytunes.core.queue import QueueManager, RepeatMode
from mytunes.models.artist_credits import split_artist_credits
from mytunes.ui.theme import MetroTheme
from mytunes.ui.components.controller_hints import build_controller_hints
import sqlite3

class PlayerBar(ft.Container):
    """
    Bottom Now Playing bar implementing the Metro/Groove UI design language:
    square album art, bold typography, dynamic accent theming,
    scrubbing progress bar, and quick action buttons.
    """

    def __init__(
        self,
        page: ft.Page,
        audio_engine: AudioEngine,
        queue_manager: QueueManager,
        theme: MetroTheme,
        on_lyrics_click: Callable[[], None],
        on_eq_click: Callable[[], None],
        on_sleep_click: Callable[[], None],
        on_mix_click: Callable[[], None],
        on_queue_click: Callable[[], None],
        db_conn: Optional[sqlite3.Connection] = None,
        on_artist_click: Optional[Callable[[str], None]] = None,
        on_album_click: Optional[Callable[[str, str], None]] = None,
    ):
        super().__init__()
        self.app_page = page
        self.audio = audio_engine
        self.queue = queue_manager
        self._mt = theme
        self.conn = db_conn

        self.on_lyrics_click = on_lyrics_click
        self.on_eq_click = on_eq_click
        self.on_sleep_click = on_sleep_click
        self.on_mix_click = on_mix_click
        self.on_queue_click = on_queue_click
        self.on_artist_navigation = on_artist_click
        self.on_album_navigation = on_album_click

        self.is_dragging_slider = False
        self._controller_mode = False
        self._controller_visible_state: dict[str, bool] = {}

        # UI Controls
        # Placeholder disc — shown when no artwork is loaded
        self._placeholder_icon = ft.Icon(
            ft.Icons.MUSIC_NOTE,
            size=20,
            color=ft.Colors.with_opacity(0.45, ft.Colors.WHITE),
        )
        _placeholder = ft.Container(
            width=54,
            height=54,
            bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.WHITE),
            border_radius=4,
            content=ft.Stack(
                width=54,
                height=54,
                controls=[
                    # Outer disc ring
                    ft.Container(
                        width=54,
                        height=54,
                        border_radius=27,
                        bgcolor=ft.Colors.with_opacity(0.28, ft.Colors.GREY_500),
                    ),
                    # Inner disc ring
                    ft.Container(
                        width=36,
                        height=36,
                        border_radius=18,
                        bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.GREY_700),
                        margin=ft.Margin(left=9, top=9, right=0, bottom=0),
                    ),
                    # Centre hole
                    ft.Container(
                        width=12,
                        height=12,
                        border_radius=6,
                        bgcolor=ft.Colors.with_opacity(0.35, ft.Colors.GREY_400),
                        margin=ft.Margin(left=21, top=21, right=0, bottom=0),
                    ),
                    # Music note icon centred
                    ft.Container(
                        width=54,
                        height=54,
                        alignment=ft.Alignment(0, 0),
                        content=self._placeholder_icon,
                    ),
                ]
            ),
        )

        self._artwork_error_icon = ft.Icon(
            ft.Icons.MUSIC_NOTE,
            size=20,
            color=ft.Colors.with_opacity(0.45, ft.Colors.WHITE),
        )
        # Actual artwork image — starts invisible, shown once src is set
        self.album_art_img = ft.Image(
            src="",
            width=54,
            height=54,
            fit=ft.BoxFit.COVER,
            border_radius=4,
            visible=False,
            error_content=ft.Container(
                width=54,
                height=54,
                bgcolor=self._mt.surface_variant,
                alignment=ft.Alignment(0, 0),
                content=self._artwork_error_icon,
            ),
        )

        # Stack: placeholder behind, real art in front
        self.album_art = ft.Stack(
            width=54,
            height=54,
            controls=[_placeholder, self.album_art_img],
        )
        # Keep a reference to the placeholder so we can show/hide it
        self._album_art_placeholder = _placeholder

        self.track_title = ft.Text(
            "No track playing",
            size=14,
            weight=ft.FontWeight.BOLD,
            color=self._mt.text_primary,
            no_wrap=True,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )

        self.track_artist_label = ft.Text(
            "—",
            size=12,
            color=self._mt.text_secondary,
            no_wrap=True,
        )
        self.track_artist = ft.TextButton(
            content=self.track_artist_label,
            style=ft.ButtonStyle(padding=0),
            tooltip="Open artist in Music",
            on_click=self._on_artist_click,
        )
        self.collaborator_links = ft.Row(spacing=0, tight=True)
        self.track_album_label = ft.Text(
            "",
            size=12,
            color=self._mt.text_secondary,
            no_wrap=True,
        )
        self.track_album = ft.TextButton(
            content=self.track_album_label,
            style=ft.ButtonStyle(padding=0),
            tooltip="Open album in Music",
            on_click=self._on_album_click,
        )

        self.fav_button = ft.IconButton(
            icon=ft.Icons.FAVORITE_BORDER,
            icon_color=ft.Colors.GREY_400,
            icon_size=20,
            tooltip="Favorite",
            on_click=self._toggle_favorite
        )

        # Progress slider & timestamps
        self.time_current = ft.Text("0:00", size=11, color=self._mt.text_secondary)
        self.time_total = ft.Text("0:00", size=11, color=self._mt.text_secondary)
        self.progress_slider = ft.Slider(
            min=0.0,
            max=100.0,
            value=0.0,
            active_color=self._mt.current_accent,
            inactive_color=ft.Colors.GREY_800,
            on_change=self._on_slider_change,
            on_change_start=self._on_slider_start,
            on_change_end=self._on_slider_end,
            expand=True
        )

        # Playback control buttons
        self.btn_shuffle = ft.IconButton(
            icon=ft.Icons.SHUFFLE,
            icon_color=ft.Colors.GREY_400,
            icon_size=20,
            tooltip="Quick Mix / Smart Shuffle",
            on_click=lambda e: self.on_mix_click()
        )

        self.btn_prev = ft.IconButton(
            icon=ft.Icons.SKIP_PREVIOUS,
            icon_color=self._mt.text_primary,
            icon_size=26,
            tooltip="Previous",
            on_click=self._on_prev_click
        )

        self.btn_play = ft.IconButton(
            icon=ft.Icons.PLAY_CIRCLE_FILL,
            icon_color=self._mt.current_accent,
            icon_size=42,
            tooltip="Play / Pause",
            on_click=self._on_play_click
        )

        self.btn_next = ft.IconButton(
            icon=ft.Icons.SKIP_NEXT,
            icon_color=self._mt.text_primary,
            icon_size=26,
            tooltip="Next",
            on_click=self._on_next_click
        )

        self.btn_repeat = ft.IconButton(
            icon=ft.Icons.REPEAT,
            icon_color=ft.Colors.GREY_400,
            icon_size=20,
            tooltip="Repeat Mode",
            on_click=self._toggle_repeat
        )

        # Volume controls
        self.btn_volume = ft.IconButton(
            icon=ft.Icons.VOLUME_UP,
            icon_color=self._mt.text_secondary,
            icon_size=18,
            on_click=self._toggle_mute
        )
        self.volume_slider = ft.Slider(
            min=0.0,
            max=1.0,
            value=1.0,
            width=100,
            active_color=self._mt.current_accent,
            on_change=self._on_volume_change
        )

        self.controller_hints = ft.Row(
            spacing=6,
            wrap=True,
            alignment=ft.MainAxisAlignment.END,
            controls=[],
        )
        self.controller_overlay = ft.Container(
            visible=False,
            padding=ft.Padding.only(bottom=2),
            alignment=ft.Alignment(1, 0),
            content=ft.Row(
                expand=True,
                alignment=ft.MainAxisAlignment.END,
                controls=[self.controller_hints],
            ),
        )

        # Quick tools
        self.btn_sleep = ft.IconButton(
            icon=ft.Icons.BEDTIME,
            icon_color=ft.Colors.GREY_400,
            icon_size=20,
            tooltip="Sleep Timer",
            on_click=lambda e: self.on_sleep_click()
        )

        self.btn_eq = ft.IconButton(
            icon=ft.Icons.EQUALIZER,
            icon_color=ft.Colors.GREY_400,
            icon_size=20,
            tooltip="Equalizer",
            on_click=lambda e: self.on_eq_click()
        )

        self.btn_lyrics = ft.IconButton(
            icon=ft.Icons.LYRICS,
            icon_color=ft.Colors.GREY_400,
            icon_size=20,
            tooltip="Synced Lyrics",
            on_click=lambda e: self.on_lyrics_click()
        )

        # Podcast speed options: x1.0, x1.25, x1.50, x1.75, x2.0
        self.playback_rates = [1.0, 1.25, 1.5, 1.75, 2.0]
        self.current_rate_index = 0
        self.speed_label = ft.Text("1x")
        self.btn_speed = ft.TextButton(
            content=self.speed_label,
            tooltip="Playback Speed",
            visible=False,
            style=ft.ButtonStyle(
                color=self._mt.current_accent,
                padding=ft.Padding.symmetric(horizontal=6, vertical=2)
            ),
            on_click=self._cycle_playback_speed
        )

        self.btn_queue = ft.IconButton(
            icon=ft.Icons.QUEUE_MUSIC,
            icon_color=ft.Colors.GREY_400,
            icon_size=20,
            tooltip="Up Next / Queue",
            on_click=lambda e: self.on_queue_click()
        )

        self._build_layout()

    def _build_layout(self) -> None:
        self.bgcolor = self._mt.surface_color
        self.border = ft.Border.only(top=ft.BorderSide(1, self._mt.border_color))
        self.padding = ft.Padding.symmetric(horizontal=16, vertical=8)
        self.height = 102

        track_info_col = ft.Column(
            spacing=2,
            alignment=ft.MainAxisAlignment.CENTER,
            controls=[
                self.track_title,
                ft.Row(
                    width=200,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=4,
                    controls=[
                        ft.Row(
                            spacing=0,
                            tight=True,
                            controls=[self.track_artist, self.collaborator_links],
                        ),
                        ft.Text("—", size=12, color=self._mt.text_secondary),
                        self.track_album,
                    ],
                ),
            ],
            width=200
        )

        left_section = ft.Row(
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[self.album_art, track_info_col, self.fav_button]
        )

        playback_buttons_row = ft.Row(
            spacing=4,
            alignment=ft.MainAxisAlignment.CENTER,
            controls=[self.btn_shuffle, self.btn_prev, self.btn_play, self.btn_next, self.btn_repeat]
        )

        self.scrubber_row = ft.Row(
            spacing=8,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[self.time_current, self.progress_slider, self.time_total]
        )

        center_section = ft.Column(
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            expand=True,
            controls=[playback_buttons_row, self.scrubber_row]
        )

        right_section = ft.Row(
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                self.btn_lyrics,
                self.btn_speed,
                self.btn_eq,
                self.btn_sleep,
                self.btn_queue,
                self.btn_volume,
                self.volume_slider
            ]
        )

        self.content = ft.Column(
            spacing=4,
            controls=[
                self.controller_overlay,
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[left_section, center_section, right_section],
                ),
            ],
        )

    def set_controller_mode(self, enabled: bool) -> None:
        if enabled == self._controller_mode:
            return
        if enabled:
            self._controller_visible_state = {
                "lyrics": self.btn_lyrics.visible,
                "speed": self.btn_speed.visible,
                "eq": self.btn_eq.visible,
                "sleep": self.btn_sleep.visible,
                "queue": self.btn_queue.visible,
                "volume": self.btn_volume.visible,
                "volume_slider": self.volume_slider.visible,
                "fav": self.fav_button.visible,
                "shuffle": self.btn_shuffle.visible,
                "repeat": self.btn_repeat.visible,
                "time_current": self.time_current.visible,
                "time_total": self.time_total.visible,
            }
        self._controller_mode = enabled
        self.controller_overlay.visible = enabled
        self.controller_hints.visible = enabled
        if enabled:
            self.btn_lyrics.visible = False
            self.btn_speed.visible = False
            self.btn_eq.visible = False
            self.btn_sleep.visible = False
            self.btn_queue.visible = False
            self.btn_volume.visible = False
            self.volume_slider.visible = False
            self.fav_button.visible = False
            self.btn_shuffle.visible = False
            self.btn_repeat.visible = False
            self.time_current.visible = False
            self.time_total.visible = False
            self.height = 126
        else:
            self.btn_lyrics.visible = self._controller_visible_state.get("lyrics", True)
            self.btn_speed.visible = self._controller_visible_state.get("speed", True)
            self.btn_eq.visible = self._controller_visible_state.get("eq", True)
            self.btn_sleep.visible = self._controller_visible_state.get("sleep", True)
            self.btn_queue.visible = self._controller_visible_state.get("queue", True)
            self.btn_volume.visible = self._controller_visible_state.get("volume", True)
            self.volume_slider.visible = self._controller_visible_state.get("volume_slider", True)
            self.fav_button.visible = self._controller_visible_state.get("fav", True)
            self.btn_shuffle.visible = self._controller_visible_state.get("shuffle", True)
            self.btn_repeat.visible = self._controller_visible_state.get("repeat", True)
            self.time_current.visible = self._controller_visible_state.get(
                "time_current", True
            )
            self.time_total.visible = self._controller_visible_state.get(
                "time_total", True
            )
            self.height = 102
        safe_update(self)

    def set_controller_hints(self, hints: dict[str, str]) -> None:
        self.controller_hints.controls = build_controller_hints(
            hints,
            self._mt.text_primary,
        )
        self.controller_hints.visible = bool(hints)
        self.controller_overlay.visible = self.controller_overlay.visible or bool(hints)
        safe_update(self)

    def _show_artwork(self, src: str) -> None:
        """Display a real artwork URL/path and hide the placeholder."""
        self.album_art_img.src = src
        self.album_art_img.visible = True
        self._album_art_placeholder.visible = False

    def _hide_artwork(self) -> None:
        """Hide the real artwork and reveal the placeholder disc."""
        self.album_art_img.visible = False
        self.album_art_img.src = ""
        self._album_art_placeholder.visible = True

    def update_track(self, track: Optional[Track]) -> None:
        """Updates track information and extracts dynamic accent color."""
        if not track:
            self._placeholder_icon.icon = ft.Icons.MUSIC_NOTE
            self._artwork_error_icon.icon = ft.Icons.MUSIC_NOTE
            self.track_title.value = "No track playing"
            self.track_artist_label.value = "—"
            self.collaborator_links.controls.clear()
            self.track_album_label.value = ""
            self.track_artist.disabled = True
            self.track_album.disabled = True
            self._hide_artwork()

            self.fav_button.icon = ft.Icons.FAVORITE_BORDER
            self.fav_button.icon_color = ft.Colors.GREY_400
            self.scrubber_row.visible = True
            self.btn_lyrics.visible = True
            self.btn_speed.visible = False
            self.btn_prev.visible = True
            self.btn_next.visible = True
            self.btn_shuffle.visible = True
            self.btn_repeat.visible = True
            self.time_total.value = "0:00"
            self.progress_slider.value = 0.0
            self._mt.reset_dynamic_accent()
            self._apply_theme_colors()
            self._refresh_controller_visibility()
            safe_update(self)
            return

        is_radio = track.id.startswith("radio_")
        fallback_icon = ft.Icons.RADIO if is_radio else ft.Icons.MUSIC_NOTE
        self._placeholder_icon.icon = fallback_icon
        self._artwork_error_icon.icon = fallback_icon

        self.track_title.value = track.title
        artist_names = split_artist_credits(track.artist) or ["Unknown Artist"]
        self.track_artist_label.value = artist_names[0]
        self.collaborator_links.controls = []
        for artist_name in artist_names[1:]:
            self.collaborator_links.controls.extend([
                ft.Text(", ", size=12, color=self._mt.text_secondary),
                ft.TextButton(
                    content=ft.Text(
                        artist_name,
                        size=12,
                        color=self._mt.text_secondary,
                        no_wrap=True,
                    ),
                    style=ft.ButtonStyle(padding=0),
                    tooltip=f"Open {artist_name} in Music",
                    on_click=lambda e, name=artist_name: self._on_artist_click(e, name),
                ),
            ])
        self.track_album_label.value = track.album or "Unknown Album"
        can_navigate_to_music = not (is_radio or track.id.startswith("pod_"))
        self.track_artist.disabled = not can_navigate_to_music or self.on_artist_navigation is None
        for collaborator_link in self.collaborator_links.controls:
            if isinstance(collaborator_link, ft.TextButton):
                collaborator_link.disabled = (
                    not can_navigate_to_music or self.on_artist_navigation is None
                )
        self.track_album.disabled = not can_navigate_to_music or self.on_album_navigation is None
        self.fav_button.icon = ft.Icons.FAVORITE if track.is_favorite else ft.Icons.FAVORITE_BORDER
        self.fav_button.icon_color = ft.Colors.RED_400 if track.is_favorite else ft.Colors.GREY_400

        # Artwork & Dynamic Theme
        if track.artwork_path:
            self._show_artwork(track.artwork_path)
            extracted_color = self._mt.extract_dominant_accent(track.artwork_path)
            if extracted_color:
                self._apply_theme_colors()
        elif track.artwork_url:
            self._show_artwork(track.artwork_url)
            self._mt.reset_dynamic_accent()
            self._apply_theme_colors()
        else:
            self._hide_artwork()
            self._mt.reset_dynamic_accent()
            self._apply_theme_colors()

        # Adjust player controls based on media type:
        # - Radio stream (id starts with "radio_"): hide lyrics/speed, hide progress bar
        # - Podcast episode (id starts with "pod_"): show speed button (x1.0..x2.0), hide lyrics, show progress bar
        # - Music / other: show lyrics button, hide speed button, show progress bar
        is_podcast = track.id.startswith("pod_")

        self.scrubber_row.visible = not is_radio
        self.btn_lyrics.visible = not (is_radio or is_podcast)
        self.btn_speed.visible = is_podcast
        self.btn_prev.visible = not is_radio
        self.btn_next.visible = not is_radio
        self.btn_shuffle.visible = not (is_radio or is_podcast)
        self.btn_repeat.visible = not is_radio
        self._refresh_controller_visibility()

        self.time_total.value = track.formatted_duration
        self.progress_slider.max = track.duration if track.duration > 0 else 100.0
        self.progress_slider.value = 0.0
        safe_update(self)

    def _refresh_controller_visibility(self) -> None:
        if not self._controller_mode:
            return

        self._controller_visible_state.update(
            {
                "lyrics": self.btn_lyrics.visible,
                "speed": self.btn_speed.visible,
                "shuffle": self.btn_shuffle.visible,
                "repeat": self.btn_repeat.visible,
            }
        )
        for control in (
            self.btn_lyrics,
            self.btn_speed,
            self.btn_eq,
            self.btn_sleep,
            self.btn_queue,
            self.btn_volume,
            self.volume_slider,
            self.fav_button,
            self.btn_shuffle,
            self.btn_repeat,
        ):
            control.visible = False

    def _cycle_playback_speed(self, e) -> None:
        """Cycles through playback speed options: x1.0, x1.25, x1.5, x1.75, x2.0."""
        self.current_rate_index = (self.current_rate_index + 1) % len(self.playback_rates)
        rate = self.playback_rates[self.current_rate_index]
        self.audio.set_playback_rate(rate)
        # Format text, e.g. "1x", "1.25x", "1.5x", "1.75x", "2x"
        rate_str = f"{rate:g}x"
        self.speed_label.value = rate_str
        safe_update(self)

    def update_playback_state(self, is_playing: bool) -> None:
        self.btn_play.icon = ft.Icons.PAUSE_CIRCLE_FILLED if is_playing else ft.Icons.PLAY_CIRCLE_FILL
        safe_update(self)

    def update_position(self, current_seconds: float, total_seconds: float) -> None:
        if self.is_dragging_slider:
            return

        mins = int(current_seconds // 60)
        secs = int(current_seconds % 60)
        self.time_current.value = f"{mins}:{secs:02d}"

        if total_seconds > 0 and self.progress_slider.max != total_seconds:
            self.progress_slider.max = total_seconds
            t_mins = int(total_seconds // 60)
            t_secs = int(total_seconds % 60)
            self.time_total.value = f"{t_mins}:{t_secs:02d}"

        self.progress_slider.value = min(current_seconds, self.progress_slider.max)
        safe_update(self)

    def _apply_theme_colors(self) -> None:
        accent = self._mt.current_accent
        self.btn_play.icon_color = accent
        self.progress_slider.active_color = accent
        self.volume_slider.active_color = accent
        if hasattr(self, "btn_speed") and self.btn_speed.style:
            self.btn_speed.style.color = accent

    def _on_play_click(self, e) -> None:
        self.audio.toggle_play_pause()

    def _on_prev_click(self, e) -> None:
        prev_track = self.queue.prev_track()
        if prev_track:
            self.audio.play_track(prev_track)

    def _on_next_click(self, e) -> None:
        next_track = self.queue.next_track()
        if next_track:
            self.audio.play_track(next_track)

    def _on_artist_click(self, e, artist_name: Optional[str] = None) -> None:
        track = self.queue.current_track
        if track and self.on_artist_navigation:
            artists = split_artist_credits(track.artist)
            target_artist = artist_name or (artists[0] if artists else track.artist)
            self.on_artist_navigation(target_artist)

    def _on_album_click(self, e) -> None:
        track = self.queue.current_track
        if track and self.on_album_navigation:
            album_artists = split_artist_credits(track.album_artist)
            track_artists = split_artist_credits(track.artist)
            album_artist = (
                album_artists[0]
                if album_artists
                else track_artists[0] if track_artists else track.artist
            )
            self.on_album_navigation(track.album, album_artist)

    def _on_slider_start(self, e) -> None:
        self.is_dragging_slider = True

    def _on_slider_change(self, e) -> None:
        """Update the time label in real time while the user drags — no seek yet."""
        if self.is_dragging_slider:
            secs = float(e.control.value)
            mins = int(secs // 60)
            sec = int(secs % 60)
            self.time_current.value = f"{mins}:{sec:02d}"
            safe_update(self)

    def _on_slider_end(self, e) -> None:
        self.is_dragging_slider = False
        target_sec = float(e.control.value)
        self.audio.seek(target_sec)

    def _on_volume_change(self, e) -> None:
        vol = float(e.control.value)
        self.audio.set_volume(vol)
        self.btn_volume.icon = ft.Icons.VOLUME_MUTE if vol == 0 else (ft.Icons.VOLUME_DOWN if vol < 0.5 else ft.Icons.VOLUME_UP)
        safe_update(self)

    def _toggle_mute(self, e) -> None:
        self.audio.toggle_mute()
        self.btn_volume.icon = ft.Icons.VOLUME_OFF if self.audio.is_muted else ft.Icons.VOLUME_UP
        safe_update(self)

    def _toggle_favorite(self, e) -> None:
        track = self.queue.current_track
        if track:
            track.is_favorite = not track.is_favorite
            self.fav_button.icon = ft.Icons.FAVORITE if track.is_favorite else ft.Icons.FAVORITE_BORDER
            self.fav_button.icon_color = ft.Colors.RED_400 if track.is_favorite else ft.Colors.GREY_400
            
            # Persist favorite state to database
            if self.conn:
                try:
                    if track.id.startswith("radio_"):
                        # Extract station id or stream url
                        self.conn.execute(
                            """
                            INSERT INTO radio_stations (id, name, stream_url, favicon, is_favorite)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(stream_url) DO UPDATE SET is_favorite = excluded.is_favorite
                            """,
                            (track.id, track.title, track.file_path, track.artwork_url, 1 if track.is_favorite else 0)
                        )
                    else:
                        self.conn.execute(
                            "UPDATE tracks SET is_favorite = ? WHERE id = ?",
                            (1 if track.is_favorite else 0, track.id)
                        )
                    self.conn.commit()
                except Exception:
                    pass

            safe_update(self)

    def _toggle_repeat(self, e) -> None:
        if self.queue.repeat_mode == RepeatMode.OFF:
            self.queue.repeat_mode = RepeatMode.ALL
            self.btn_repeat.icon = ft.Icons.REPEAT
            self.btn_repeat.icon_color = self._mt.current_accent
        elif self.queue.repeat_mode == RepeatMode.ALL:
            self.queue.repeat_mode = RepeatMode.ONE
            self.btn_repeat.icon = ft.Icons.REPEAT_ONE
            self.btn_repeat.icon_color = self._mt.current_accent
        else:
            self.queue.repeat_mode = RepeatMode.OFF
            self.btn_repeat.icon = ft.Icons.REPEAT
            self.btn_repeat.icon_color = ft.Colors.GREY_400
        safe_update(self)
