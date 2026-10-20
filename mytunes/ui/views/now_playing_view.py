from __future__ import annotations

import threading
from typing import Callable, Optional

import flet as ft

from mytunes.core.queue import RepeatMode
from mytunes.models.artist_credits import split_artist_credits
from mytunes.models.track import Track
from mytunes.providers.metadata import ArtistMetadataProvider
from mytunes.ui.dialog_utils import safe_update
from mytunes.ui.theme import MetroTheme
from mytunes.ui.components.controller_hints import build_controller_hints


class NowPlayingView(ft.Container):
    """Full-page now-playing screen with an artist-photo backdrop."""

    def __init__(
        self,
        page: ft.Page,
        theme: MetroTheme,
        metadata_provider: ArtistMetadataProvider,
        on_play_pause: Callable[[], None],
        on_previous: Callable[[], None],
        on_next: Callable[[], None],
        on_seek: Callable[[float], None],
        on_favorite: Callable[[], None],
        on_mix: Callable[[], None],
        on_repeat: Callable[[], RepeatMode],
        on_repeat_mode: Callable[[], RepeatMode],
        on_lyrics: Callable[[], None],
        on_speed: Callable[[], str],
        on_eq: Callable[[], None],
        on_sleep: Callable[[], None],
        on_queue: Callable[[], None],
        on_volume_change: Callable[[float], None],
        on_mute: Callable[[], bool],
        on_artist_click: Callable[[str], None],
        on_album_click: Callable[[str, str], None],
    ):
        super().__init__()
        self.app_page = page
        self._mt = theme
        self.metadata_provider = metadata_provider
        self.on_play_pause = on_play_pause
        self.on_previous = on_previous
        self.on_next = on_next
        self.on_seek = on_seek
        self.on_favorite = on_favorite
        self.on_mix = on_mix
        self.on_repeat = on_repeat
        self.on_repeat_mode = on_repeat_mode
        self.on_lyrics = on_lyrics
        self.on_speed = on_speed
        self.on_eq = on_eq
        self.on_sleep = on_sleep
        self.on_queue = on_queue
        self.on_volume_change = on_volume_change
        self.on_mute = on_mute
        self.on_artist_click = on_artist_click
        self.on_album_click = on_album_click
        self.current_track: Optional[Track] = None
        self._track_token = 0
        self._is_dragging = False
        self._is_seekable = False
        self._is_radio = False
        self._portrait_refreshes: set[str] = set()
        self._controller_focus_control: Optional[ft.Control] = None
        self._controller_focus_original: Optional[dict[str, object]] = None
        self.expand = True
        self._build_view()

    def _build_view(self) -> None:
        self.background_image = ft.Container(
            expand=True,
            visible=False,
            image=ft.DecorationImage(
                src="",
                fit=ft.BoxFit.COVER,
            ),
        )
        self.album_image = ft.Image(
            src="",
            width=260,
            height=260,
            fit=ft.BoxFit.COVER,
            visible=False,
            border_radius=8,
        )
        self.album_placeholder = ft.Container(
            width=260,
            height=260,
            border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.30, ft.Colors.BLACK),
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(ft.Icons.ALBUM, size=80, color=ft.Colors.WHITE_70),
        )
        album_art = ft.Stack(
            width=260,
            height=260,
            controls=[self.album_placeholder, self.album_image],
        )

        self.title_text = ft.Text(
            "No track playing",
            size=30,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.WHITE,
            text_align=ft.TextAlign.CENTER,
            max_lines=2,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.artist_text = ft.Text(
            "Choose something to play",
            size=17,
            color=ft.Colors.WHITE_70,
            text_align=ft.TextAlign.CENTER,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.artist_button = ft.TextButton(
            content=self.artist_text,
            style=ft.ButtonStyle(padding=0),
            on_click=self._on_artist_click,
            disabled=True,
        )
        self.album_text = ft.Text(
            "",
            size=14,
            color=ft.Colors.WHITE_60,
            text_align=ft.TextAlign.CENTER,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.album_button = ft.TextButton(
            content=self.album_text,
            style=ft.ButtonStyle(padding=0),
            on_click=self._on_album_click,
            disabled=True,
        )
        self.time_current = ft.Text("0:00", size=12, color=ft.Colors.WHITE_70)
        self.time_total = ft.Text("0:00", size=12, color=ft.Colors.WHITE_70)
        self.progress_slider = ft.Slider(
            min=0,
            max=100,
            value=0,
            active_color=self._mt.current_accent,
            inactive_color=ft.Colors.with_opacity(0.45, ft.Colors.WHITE),
            on_change_start=lambda e: self._set_dragging(True),
            on_change_end=self._on_seek,
            expand=True,
        )
        self.progress_slider.disabled = True

        self.play_button = ft.IconButton(
            icon=ft.Icons.PLAY_CIRCLE_FILL,
            icon_size=64,
            icon_color=self._mt.current_accent,
            tooltip="Play / Pause",
            on_click=lambda e: self.on_play_pause(),
        )
        self.favorite_button = ft.IconButton(
            icon=ft.Icons.FAVORITE_BORDER,
            icon_color=ft.Colors.WHITE_70,
            icon_size=22,
            tooltip="Favorite",
            on_click=self._toggle_favorite,
        )
        self.shuffle_button = ft.IconButton(
            icon=ft.Icons.SHUFFLE,
            icon_color=ft.Colors.WHITE_70,
            tooltip="Quick Mix / Smart Shuffle",
            on_click=lambda e: self.on_mix(),
        )
        self.repeat_button = ft.IconButton(
            icon=ft.Icons.REPEAT,
            icon_color=ft.Colors.WHITE_70,
            tooltip="Repeat Mode",
            on_click=self._toggle_repeat,
        )
        self.previous_button = ft.IconButton(
            icon=ft.Icons.SKIP_PREVIOUS,
            icon_size=38,
            icon_color=ft.Colors.WHITE,
            tooltip="Previous",
            on_click=lambda e: self.on_previous(),
        )
        self.next_button = ft.IconButton(
            icon=ft.Icons.SKIP_NEXT,
            icon_size=38,
            icon_color=ft.Colors.WHITE,
            tooltip="Next",
            on_click=lambda e: self.on_next(),
        )
        self.lyrics_button = ft.IconButton(
            icon=ft.Icons.LYRICS,
            icon_color=ft.Colors.WHITE_70,
            tooltip="Synced Lyrics",
            on_click=lambda e: self.on_lyrics(),
        )
        self.speed_button = ft.TextButton(
            "1x",
            tooltip="Playback Speed",
            style=ft.ButtonStyle(color=ft.Colors.WHITE_70),
            visible=False,
            on_click=self._cycle_speed,
        )
        self.eq_button = ft.IconButton(
            icon=ft.Icons.EQUALIZER,
            icon_color=ft.Colors.WHITE_70,
            tooltip="Equalizer",
            on_click=lambda e: self.on_eq(),
        )
        self.sleep_button = ft.IconButton(
            icon=ft.Icons.BEDTIME,
            icon_color=ft.Colors.WHITE_70,
            tooltip="Sleep Timer",
            on_click=lambda e: self.on_sleep(),
        )
        self.queue_button = ft.IconButton(
            icon=ft.Icons.QUEUE_MUSIC,
            icon_color=ft.Colors.WHITE_70,
            tooltip="Up Next / Queue",
            on_click=lambda e: self.on_queue(),
        )
        self.volume_button = ft.IconButton(
            icon=ft.Icons.VOLUME_UP,
            icon_color=ft.Colors.WHITE_70,
            tooltip="Mute / Unmute",
            on_click=self._toggle_mute,
        )
        self.volume_slider = ft.Slider(
            min=0,
            max=1,
            value=1,
            width=220,
            active_color=self._mt.current_accent,
            on_change=self._on_volume_change,
        )

        content = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=14,
            controls=[
                album_art,
                ft.Container(height=4),
                self.title_text,
                self.artist_button,
                self.album_button,
                ft.Container(
                    width=500,
                    content=ft.Row(
                        spacing=10,
                        controls=[
                            self.time_current,
                            self.progress_slider,
                            self.time_total,
                        ],
                    ),
                ),
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=12,
                    controls=[
                        self.shuffle_button,
                        self.previous_button,
                        self.play_button,
                        self.next_button,
                        self.repeat_button,
                        self.favorite_button,
                    ],
                ),
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=8,
                    controls=[
                        self.lyrics_button,
                        self.speed_button,
                        self.eq_button,
                        self.sleep_button,
                        self.queue_button,
                    ],
                ),
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                    controls=[self.volume_button, self.volume_slider],
                ),
            ],
        )

        self.content = ft.Stack(
            expand=True,
            controls=[
                self.background_image,
                ft.Container(
                    expand=True,
                    bgcolor=ft.Colors.with_opacity(0.76, ft.Colors.BLACK),
                ),
                ft.Container(
                    expand=True,
                    padding=24,
                    content=content,
                ),
                self._build_controller_overlay(),
            ],
        )

    def _build_controller_overlay(self) -> ft.Container:
        self.controller_hints = ft.Row(
            spacing=8,
            wrap=True,
            alignment=ft.MainAxisAlignment.END,
            controls=[],
        )
        self.controller_overlay = ft.Container(
            visible=False,
            left=0,
            right=0,
            bottom=0,
            alignment=ft.Alignment(1, 1),
            padding=12,
            content=self.controller_hints,
        )
        return self.controller_overlay

    def set_controller_mode(
        self,
        enabled: bool,
        hints: Optional[dict[str, str]] = None,
    ) -> None:
        self.controller_overlay.visible = enabled
        self.controller_hints.controls = build_controller_hints(
            hints or {},
            ft.Colors.WHITE,
        )
        self.controller_hints.visible = enabled
        if not enabled:
            self.set_controller_focus(-1)
        safe_update(self)

    def controller_focusables(self) -> list[ft.Control]:
        candidates: list[ft.Control] = [
            self.artist_button,
            self.album_button,
            self.progress_slider,
            self.shuffle_button,
            self.previous_button,
            self.play_button,
            self.next_button,
            self.repeat_button,
            self.favorite_button,
            self.lyrics_button,
            self.speed_button,
            self.eq_button,
            self.sleep_button,
            self.queue_button,
            self.volume_button,
            self.volume_slider,
        ]
        return [
            control
            for control in candidates
            if control.visible and not control.disabled
        ]

    def set_controller_focus(self, index: int) -> Optional[ft.Control]:
        if self._controller_focus_control is not None:
            self._restore_controller_focus()

        controls = self.controller_focusables()
        if index < 0 or index >= len(controls):
            self._controller_focus_control = None
            return None

        control = controls[index]
        self._controller_focus_control = control
        accent = self._mt.current_accent
        if isinstance(control, ft.IconButton):
            self._controller_focus_original = {
                "icon_color": control.icon_color,
                "style": control.style,
            }
            control.icon_color = accent
            control.style = ft.ButtonStyle(
                bgcolor=ft.Colors.with_opacity(0.22, accent),
                side=ft.BorderSide(2, accent),
                shape=ft.RoundedRectangleBorder(radius=10),
                shadow_color=accent,
                elevation=8,
            )
        elif isinstance(control, ft.Slider):
            self._controller_focus_original = {
                "active_color": control.active_color,
                "inactive_color": control.inactive_color,
                "thumb_color": control.thumb_color,
                "overlay_color": control.overlay_color,
            }
            control.active_color = ft.Colors.WHITE
            control.inactive_color = accent
            control.thumb_color = accent
            control.overlay_color = ft.Colors.with_opacity(0.3, accent)
        elif isinstance(control, ft.TextButton):
            self._controller_focus_original = {"style": control.style}
            control.style = ft.ButtonStyle(
                color=accent,
                bgcolor=ft.Colors.with_opacity(0.22, accent),
                side=ft.BorderSide(2, accent),
                shape=ft.RoundedRectangleBorder(radius=10),
                shadow_color=accent,
                elevation=8,
            )
        safe_update(control)
        return control

    def _restore_controller_focus(self) -> None:
        control = self._controller_focus_control
        original = getattr(self, "_controller_focus_original", None)
        if control is None or original is None:
            return
        for attribute, value in original.items():
            setattr(control, attribute, value)
        safe_update(control)
        self._controller_focus_control = None
        self._controller_focus_original = None

    def update_track(self, track: Optional[Track]) -> None:
        self._track_token += 1
        token = self._track_token
        if track is None:
            self.current_track = None
            self.title_text.value = "No track playing"
            self.artist_text.value = "Choose something to play"
            self.album_text.value = ""
            self.artist_button.disabled = True
            self.album_button.disabled = True
            self.favorite_button.disabled = True
            self.shuffle_button.disabled = True
            self.repeat_button.disabled = True
            self.lyrics_button.disabled = True
            self.speed_button.disabled = True
            self._set_artwork(None)
            self._set_background(None)
            self.progress_slider.value = 0
            self.progress_slider.max = 100
            self.progress_slider.disabled = True
            self._is_seekable = False
            self._is_radio = False
            self.time_current.value = "0:00"
            self.time_total.value = "0:00"
            safe_update(self)
            return

        self.current_track = track
        self.title_text.value = track.title
        artist_names = split_artist_credits(track.artist)
        self.artist_text.value = ", ".join(artist_names) or "Unknown Artist"
        self.album_text.value = track.album or ""
        can_navigate = not (
            track.id.startswith("radio_") or track.id.startswith("pod_")
        )
        self.artist_button.disabled = not can_navigate or not bool(artist_names)
        self.album_button.disabled = not can_navigate or not bool(track.album)
        self.favorite_button.disabled = False
        self.favorite_button.icon = (
            ft.Icons.FAVORITE if track.is_favorite else ft.Icons.FAVORITE_BORDER
        )
        self.favorite_button.icon_color = (
            ft.Colors.RED_400 if track.is_favorite else ft.Colors.WHITE_70
        )
        self._set_artwork(track.artwork_path or track.artwork_url)
        self.progress_slider.value = 0
        self.progress_slider.max = track.duration if track.duration > 0 else 100
        is_radio = track.id.startswith("radio_")
        is_podcast = track.id.startswith("pod_")
        self.shuffle_button.visible = not (is_radio or is_podcast)
        self.repeat_button.visible = not is_radio
        self.lyrics_button.visible = not (is_radio or is_podcast)
        self.speed_button.visible = is_podcast
        self.shuffle_button.disabled = is_radio or is_podcast
        self.repeat_button.disabled = is_radio
        self.lyrics_button.disabled = is_radio or is_podcast
        self.speed_button.disabled = not is_podcast
        self._sync_repeat_mode()
        self._is_radio = is_radio
        self._is_seekable = not is_radio and track.duration > 0
        self.progress_slider.disabled = not self._is_seekable
        self.time_current.value = "0:00"
        self.time_total.value = track.formatted_duration

        fallback_image = track.artwork_path or track.artwork_url
        primary_artist = artist_names[0] if artist_names else ""
        cached = (
            self.metadata_provider.get_cached_metadata(primary_artist)
            if primary_artist and not is_radio
            else None
        )
        artist_image = (
            (cached.get("picture_url") or cached.get("picture_medium"))
            if cached
            else None
        )
        self._set_background(artist_image or fallback_image)

        refresh_cached_image = bool(
            artist_image
            and primary_artist.casefold() not in self._portrait_refreshes
        )
        if primary_artist and (
            not artist_image or refresh_cached_image
        ) and not is_radio:
            self._portrait_refreshes.add(primary_artist.casefold())
            threading.Thread(
                target=self._fetch_artist_image,
                args=(token, primary_artist, fallback_image, refresh_cached_image),
                daemon=True,
            ).start()

        safe_update(self)

    def _fetch_artist_image(
        self,
        token: int,
        artist_name: str,
        fallback_image: Optional[str],
        force_refresh: bool,
    ) -> None:
        metadata = self.metadata_provider.fetch_and_cache(
            artist_name,
            force_refresh=force_refresh,
        )
        image = metadata.get("picture_url") or metadata.get("picture_medium")
        if token != self._track_token:
            return
        self._set_background(image or fallback_image)
        safe_update(self)

    def update_playback_state(self, is_playing: bool) -> None:
        self.play_button.icon = (
            ft.Icons.PAUSE_CIRCLE_FILLED
            if is_playing
            else ft.Icons.PLAY_CIRCLE_FILL
        )
        safe_update(self)

    def update_volume(self, volume: float, is_muted: bool = False) -> None:
        self.volume_slider.value = volume
        if is_muted:
            self.volume_button.icon = ft.Icons.VOLUME_OFF
        elif volume == 0:
            self.volume_button.icon = ft.Icons.VOLUME_MUTE
        elif volume < 0.5:
            self.volume_button.icon = ft.Icons.VOLUME_DOWN
        else:
            self.volume_button.icon = ft.Icons.VOLUME_UP
        safe_update(self)

    def _toggle_favorite(self, event) -> None:
        self.on_favorite()
        if self.current_track:
            self.favorite_button.icon = (
                ft.Icons.FAVORITE
                if self.current_track.is_favorite
                else ft.Icons.FAVORITE_BORDER
            )
            self.favorite_button.icon_color = (
                ft.Colors.RED_400
                if self.current_track.is_favorite
                else ft.Colors.WHITE_70
            )
        safe_update(self)

    def _toggle_repeat(self, event) -> None:
        self.on_repeat()
        self._sync_repeat_mode()
        safe_update(self)

    def _sync_repeat_mode(self) -> None:
        mode = self.on_repeat_mode()
        self.repeat_button.icon = (
            ft.Icons.REPEAT_ONE if mode == RepeatMode.ONE else ft.Icons.REPEAT
        )
        self.repeat_button.icon_color = (
            self._mt.current_accent
            if mode != RepeatMode.OFF
            else ft.Colors.WHITE_70
        )

    def _cycle_speed(self, event) -> None:
        self.speed_button.content = self.on_speed()
        safe_update(self)

    def _on_volume_change(self, event) -> None:
        volume = float(event.control.value)
        self.on_volume_change(volume)

    def _toggle_mute(self, event) -> None:
        is_muted = self.on_mute()
        self.update_volume(self.volume_slider.value, is_muted)

    def _on_artist_click(self, event) -> None:
        artist_names = (
            split_artist_credits(self.current_track.artist)
            if self.current_track
            else []
        )
        if artist_names:
            self.on_artist_click(artist_names[0])

    def _on_album_click(self, event) -> None:
        track = self.current_track
        if not track or not track.album:
            return
        album_artists = split_artist_credits(track.album_artist)
        track_artists = split_artist_credits(track.artist)
        album_artist = (
            album_artists[0]
            if album_artists
            else track_artists[0] if track_artists else track.artist
        )
        self.on_album_click(track.album, album_artist)

    def update_position(self, current_seconds: float, total_seconds: float) -> None:
        if self._is_dragging:
            return
        self.time_current.value = self._format_time(current_seconds)
        if total_seconds > 0:
            self.progress_slider.max = total_seconds
            self.time_total.value = self._format_time(total_seconds)
            self._is_seekable = not self._is_radio
            self.progress_slider.disabled = not self._is_seekable
        self.progress_slider.value = min(current_seconds, self.progress_slider.max)
        safe_update(self)

    def _set_artwork(self, source: Optional[str]) -> None:
        self.album_image.src = source or ""
        self.album_image.visible = bool(source)
        self.album_placeholder.visible = not bool(source)

    def _set_background(self, source: Optional[str]) -> None:
        self.background_image.image.src = source or ""
        self.background_image.visible = bool(source)

    def _set_dragging(self, is_dragging: bool) -> None:
        self._is_dragging = is_dragging

    def _on_seek(self, event) -> None:
        self._is_dragging = False
        self.on_seek(float(event.control.value))

    @staticmethod
    def _format_time(seconds: float) -> str:
        minutes = int(seconds // 60)
        remainder = int(seconds % 60)
        return f"{minutes}:{remainder:02d}"
