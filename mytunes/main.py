from __future__ import annotations
import os
import sys
import ctypes
import time
import flet as ft

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mytunes.models.schema import init_db
from mytunes.models.track import Track
from mytunes.models.radio import RadioStation
from mytunes.models.podcast import Episode, PodcastShow
from mytunes.providers.local import LocalProvider
from mytunes.providers.metadata import ArtistMetadataProvider
from mytunes.sync.sync_manager import SyncManager
from mytunes.core.queue import QueueManager
from mytunes.core.audio import AudioEngine
from mytunes.core.playback_session import PlaybackSessionStore
from mytunes.core.media_controls import create_media_controls
from mytunes.ui.theme import MetroTheme
from mytunes.ui.components.pivot_nav import PivotNav
from mytunes.ui.components.player_bar import PlayerBar
from mytunes.ui.components.sleep_timer_dialog import SleepTimerDialog
from mytunes.ui.components.equalizer_dialog import EqualizerDialog
from mytunes.ui.components.quick_mix_dialog import QuickMixDialog
from mytunes.ui.components.lyrics_view import LyricsView
from mytunes.ui.views.music_view import MusicView
from mytunes.ui.views.radio_view import RadioView
from mytunes.ui.views.now_playing_view import NowPlayingView
from mytunes.ui.views.podcasts_view import PodcastsView
from mytunes.ui.views.cloud_view import CloudView
from mytunes.ui.views.playlists_view import PlaylistsView
from mytunes.ui.views.settings_view import SettingsView

from mytunes.ui.dialog_utils import show_snackbar, open_dialog, close_dialog


class XInputController:
    """Minimal XInput driver for the app's controller flow.

    This listens for a connected Xbox-style controller and translates the
    expected actions into app callbacks while keeping mouse interaction as the
    fallback input mode.
    """

    # XInput bitmask constants
    DPAD_UP = 0x0001
    DPAD_DOWN = 0x0002
    DPAD_LEFT = 0x0004
    DPAD_RIGHT = 0x0008
    START = 0x0010
    BACK = 0x0020
    LEFT_THUMB = 0x0040
    RIGHT_THUMB = 0x0080
    LEFT_SHOULDER = 0x0100
    RIGHT_SHOULDER = 0x0200
    A = 0x1000
    B = 0x2000
    X = 0x4000
    Y = 0x8000

    def __init__(
        self,
        page: ft.Page,
        pivot_nav,
        player_bar,
        audio_engine,
        queue_manager,
        on_toggle_fullscreen,
        views,
        on_section_change,
        toggle_lyrics,
        open_queue_modal,
    ):
        self.page = page
        self.pivot_nav = pivot_nav
        self.player_bar = player_bar
        self.audio_engine = audio_engine
        self.queue_manager = queue_manager
        self.on_toggle_fullscreen = on_toggle_fullscreen
        self.views = views
        self.on_section_change = on_section_change
        self.toggle_lyrics = toggle_lyrics
        self.open_queue_modal = open_queue_modal

        self.connected = False
        self.controller_mode = False
        self._pressed_buttons = 0
        self._stick_dead_zone = 0.35
        self._last_mouse_move = 0.0
        self._xinput = self._load_xinput()

        self.page.on_mouse_move = lambda e: self._exit_controller_mode()
        self.page.on_scroll = lambda e: self._exit_controller_mode()
        self.page.run_task(self._poll_loop)

    def _load_xinput(self):
        try:
            return ctypes.windll.xinput1_4
        except Exception:
            try:
                return ctypes.windll.xinput9_1_0
            except Exception:
                return None

    def _set_connected(self, connected: bool) -> None:
        if self.connected == connected:
            return
        self.connected = connected
        self.controller_mode = connected
        self.player_bar.set_controller_mode(connected)
        self.player_bar.set_controller_hints(
            {
                "A": "Play",
                "B": "Back",
                "X": "More",
                "Y": "Search",
                "LB/RB": "Tabs",
                "DPad": "Volume",
                "LT/RT": "Seek",
                "Start": "Queue",
            }
            if connected
            else {}
        )
        self.page.update()

    def _exit_controller_mode(self) -> None:
        if self.controller_mode:
            self.controller_mode = False
            self.player_bar.set_controller_mode(False)
            self.page.update()

    async def _poll_loop(self):
        while True:
            if self._xinput is None:
                if self.connected:
                    self._set_connected(False)
                await __import__("asyncio").sleep(0.1)
                continue

            class XINPUT_GAMEPAD(ctypes.Structure):
                _fields_ = [
                    ("wButtons", ctypes.c_ushort),
                    ("bLeftTrigger", ctypes.c_ubyte),
                    ("bRightTrigger", ctypes.c_ubyte),
                    ("sThumbLX", ctypes.c_short),
                    ("sThumbLY", ctypes.c_short),
                    ("sThumbRX", ctypes.c_short),
                    ("sThumbRY", ctypes.c_short),
                ]

            class XINPUT_STATE(ctypes.Structure):
                _fields_ = [
                    ("dwPacketNumber", ctypes.c_ulong),
                    ("Gamepad", XINPUT_GAMEPAD),
                ]

            state = XINPUT_STATE()
            try:
                result = self._xinput.XInputGetState(0, ctypes.byref(state))
            except Exception:
                if self.connected:
                    self._set_connected(False)
                await __import__("asyncio").sleep(0.1)
                continue

            if result != 0:
                if self.connected:
                    self._set_connected(False)
                await __import__("asyncio").sleep(0.1)
                continue

            if not self.connected:
                self._set_connected(True)

            buttons = state.Gamepad.wButtons
            left_x = state.Gamepad.sThumbLX / 32767.0
            left_y = state.Gamepad.sThumbLY / 32767.0
            right_x = state.Gamepad.sThumbRX / 32767.0
            right_y = state.Gamepad.sThumbRY / 32767.0

            self._handle_button_state(buttons)
            self._handle_analog(left_x, left_y, right_x, right_y)
            self._handle_triggers(state.Gamepad.bLeftTrigger, state.Gamepad.bRightTrigger)
            await __import__("asyncio").sleep(0.05)

    def _handle_button_state(self, buttons: int) -> None:
        diff = buttons & ~self._pressed_buttons
        self._pressed_buttons = buttons
        if diff == 0:
            return

        if diff & self.A:
            self.audio_engine.toggle_play_pause()
        if diff & self.B:
            self._handle_back()
        if diff & self.X:
            self.open_queue_modal()
        if diff & self.Y:
            self._handle_search()
        if diff & self.LEFT_SHOULDER:
            self._handle_prev_tab()
        if diff & self.RIGHT_SHOULDER:
            self._handle_next_tab()
        if diff & self.START:
            self.open_queue_modal()
        if diff & self.BACK:
            self.on_toggle_fullscreen()
        if diff & self.DPAD_UP:
            self._adjust_volume(+0.05)
        if diff & self.DPAD_DOWN:
            self._adjust_volume(-0.05)
        if diff & self.DPAD_LEFT:
            self.queue_manager.prev_track()
        if diff & self.DPAD_RIGHT:
            self.queue_manager.next_track()

    def _handle_analog(self, left_x: float, left_y: float, right_x: float, right_y: float) -> None:
        if abs(left_y) > self._stick_dead_zone:
            if left_y < 0:
                self._move_list_selection(-1)
            else:
                self._move_list_selection(1)

        if abs(right_y) > self._stick_dead_zone:
            if right_y < 0:
                self._move_queue_order(-1)
            else:
                self._move_queue_order(1)

        if abs(left_x) > self._stick_dead_zone:
            if left_x < 0:
                self.queue_manager.prev_track()
            else:
                self.queue_manager.next_track()

        if abs(right_x) > self._stick_dead_zone and abs(right_x) > abs(right_y):
            self._adjust_volume(right_x * 0.10)

    def _handle_triggers(self, left_trigger: int, right_trigger: int) -> None:
        if left_trigger > 10:
            self.audio_engine.seek(max(0.0, self.audio_engine.current_position - 10.0))
        if right_trigger > 10:
            self.audio_engine.seek(self.audio_engine.current_position + 10.0)

    def _handle_back(self) -> None:
        if self.toggle_lyrics is not None:
            self.toggle_lyrics()
        elif self.pivot_nav.active_index > 0:
            self.on_section_change(max(0, self.pivot_nav.active_index - 1))

    def _handle_search(self) -> None:
        current_index = self.pivot_nav.active_index
        views = {
            1: getattr(self.views[1], "search_input", None),
            2: getattr(self.views[2], "search_input", None),
        }
        if current_index in views and views[current_index] is not None:
            views[current_index].focus()

    def _handle_prev_tab(self) -> None:
        if self.pivot_nav.active_index > 0:
            self.on_section_change(self.pivot_nav.active_index - 1)

    def _handle_next_tab(self) -> None:
        if self.pivot_nav.active_index < len(self.views) - 1:
            self.on_section_change(self.pivot_nav.active_index + 1)

    def _adjust_volume(self, delta: float) -> None:
        self.audio_engine.set_volume(max(0.0, min(1.0, self.audio_engine.volume + delta)))

    def _move_list_selection(self, direction: int) -> None:
        if self.pivot_nav.active_index == 0:
            return
        view = self.views[self.pivot_nav.active_index]
        elem = getattr(view, "content_area", None)
        list_view = getattr(elem, "controls", None)
        if not list_view:
            return
        if len(list_view) > 1:
            next_index = min(max(0, len(list_view) - 1), 1)
            target = list_view[next_index]
            if hasattr(target, "focus"):
                target.focus()

    def _move_queue_order(self, direction: int) -> None:
        if self.queue_manager.current_track is None:
            return
        current_index = self.queue_manager.current_index
        if current_index < 0:
            return
        if direction < 0:
            target_index = current_index - 1
        else:
            target_index = current_index + 1
        if 0 <= target_index < len(self.queue_manager.queue):
            self.queue_manager.reorder_at(current_index, target_index)


def main(page: ft.Page) -> None:
    page.title = "MyTunes"
    if hasattr(page, "window") and page.window:
        page.window.width = 1100
        page.window.height = 720
        page.window.min_width = 850
        page.window.min_height = 600
    else:
        page.window_width = 1100
        page.window_height = 720
        page.window_min_width = 850
        page.window_min_height = 600

    page.padding = 0
    page.spacing = 0

    # 1. Initialize Database & Backend
    db_conn = init_db()
    local_provider = LocalProvider(db_conn)
    sync_manager = SyncManager(db_conn)
    playback_session = PlaybackSessionStore(db_conn)
    saved_session = playback_session.load(local_provider.get_all_tracks())

    # 2. Theme & Design
    theme = MetroTheme(is_dark=True, default_accent="#0078D7")
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = theme.bg_color

    # 3. Queue & Audio Engine
    queue_manager = QueueManager()
    if saved_session and saved_session.tracks:
        queue_manager.set_queue(saved_session.tracks, saved_session.current_index)
        if saved_session.current_index < 0:
            queue_manager.current_index = -1
    audio_engine = AudioEngine(page, queue_manager)
    if saved_session:
        audio_engine.set_volume(saved_session.volume)
        audio_engine.is_muted = saved_session.is_muted
        if audio_engine.audio and saved_session.is_muted:
            audio_engine.audio.volume = 0.0

    def persist_playback_session(force_position: bool = False) -> None:
        playback_session.save(
            queue_manager,
            audio_engine.current_position,
            audio_engine.volume,
            audio_engine.is_muted,
            force_position=force_position,
        )

    queue_manager.on_queue_changed = persist_playback_session
    if saved_session is None:
        persist_playback_session(force_position=True)
    media_controls = create_media_controls(page, audio_engine, queue_manager)

    def close_app(_event) -> None:
        persist_playback_session(force_position=True)
        media_controls.close()

    page.on_close = close_app

    # 4. Dialogs & Overlays
    sleep_dialog = SleepTimerDialog(page, audio_engine)
    eq_dialog = EqualizerDialog(page)

    # 5. Lyrics View (Toggleable)
    lyrics_view = LyricsView(page, audio_engine.seek)
    lyrics_active = False
    artist_metadata = ArtistMetadataProvider(db_conn=db_conn)

    def play_previous_track() -> None:
        previous_track = queue_manager.prev_track()
        if previous_track:
            audio_engine.play_track(previous_track)

    def play_next_track() -> None:
        next_track = queue_manager.next_track()
        if next_track:
            audio_engine.play_track(next_track)

    now_playing_view = NowPlayingView(
        page,
        theme,
        artist_metadata,
        audio_engine.toggle_play_pause,
        play_previous_track,
        play_next_track,
        audio_engine.seek,
        on_favorite=lambda: player_bar._toggle_favorite(None),
        on_mix=lambda: open_quick_mix(),
        on_repeat=lambda: (
            player_bar._toggle_repeat(None),
            queue_manager.repeat_mode,
        )[1],
        on_repeat_mode=lambda: queue_manager.repeat_mode,
        on_lyrics=lambda: toggle_lyrics(),
        on_speed=lambda: (
            player_bar._cycle_playback_speed(None),
            player_bar.speed_label.value,
        )[1],
        on_eq=lambda: eq_dialog.show(),
        on_sleep=lambda: sleep_dialog.show(),
        on_queue=lambda: open_queue_modal(),
        on_volume_change=audio_engine.set_volume,
        on_mute=lambda: (
            player_bar._toggle_mute(None),
            audio_engine.is_muted,
        )[1],
        on_artist_click=lambda artist: open_artist_in_music(artist),
        on_album_click=lambda album, artist: open_album_in_music(album, artist),
    )

    # Forward declaration for UI callbacks
    def on_track_changed(track: Track | None) -> None:
        player_bar.update_track(track)
        now_playing_view.update_track(track)
        media_controls.update_track(track)
        if track and lyrics_active:
            lyrics_view.load_for_track(track)
        page.update()

    queue_manager.on_track_changed = on_track_changed

    def on_playback_state_changed(is_playing: bool) -> None:
        player_bar.update_playback_state(is_playing)
        now_playing_view.update_playback_state(is_playing)
        media_controls.update_playback_state(is_playing)

    def on_position_changed(current: float, total: float) -> None:
        player_bar.update_position(current, total)
        now_playing_view.update_position(current, total)
        media_controls.update_position(current, total)
        persist_playback_session()
        if lyrics_active:
            lyrics_view.update_position(current)

    def on_volume_changed(volume: float) -> None:
        media_controls.update_volume(volume)
        now_playing_view.update_volume(audio_engine.volume, audio_engine.is_muted)
        player_bar.volume_slider.value = audio_engine.volume
        player_bar.btn_volume.icon = (
            ft.Icons.VOLUME_OFF
            if audio_engine.is_muted
            else ft.Icons.VOLUME_MUTE
            if audio_engine.volume == 0
            else ft.Icons.VOLUME_DOWN
            if audio_engine.volume < 0.5
            else ft.Icons.VOLUME_UP
        )
        persist_playback_session()

    def on_seeked(_position: float) -> None:
        persist_playback_session(force_position=True)

    audio_engine.on_state_changed = on_playback_state_changed
    audio_engine.on_stopped = media_controls.update_playback_stopped
    audio_engine.on_volume_changed = on_volume_changed
    audio_engine.on_position_changed = on_position_changed
    audio_engine.on_seeked = on_seeked

    audio_engine.on_sleep_triggered = lambda: (
        show_snackbar(page, "Sleep Timer expired: Playback stopped.")
    )

    # Playback handlers
    def play_track(track: Track, current_list: list[Track]) -> None:
        try:
            idx = current_list.index(track)
        except ValueError:
            idx = 0
        queue_manager.set_queue(current_list, start_index=idx)
        audio_engine.play_track(track)

    def play_next(track: Track) -> None:
        queue_manager.play_next(track)
        show_snackbar(page, f"Playing next: {track.title}")

    def add_to_queue(track: Track) -> None:
        queue_manager.add_to_queue(track)
        show_snackbar(page, f"Added to queue: {track.title}")

    def play_radio_station(station: RadioStation) -> None:
        stream_track = Track(
            id=f"radio_{station.id}",
            title=station.name,
            artist=f"Radio ({station.country or 'Global'})",
            album=station.tags or "Online Stream",
            file_path=station.stream_url,
            source="stream",
            artwork_url=station.favicon
        )
        queue_manager.set_queue([stream_track], 0)
        audio_engine.play_track(stream_track)

    def play_podcast_episode(episode: Episode, show: PodcastShow) -> None:
        downloaded_path = (
            episode.download_path
            if episode.download_path and os.path.isfile(episode.download_path)
            else None
        )
        podcast_track = Track(
            id=f"pod_{episode.id}",
            title=episode.title,
            artist=show.author or show.title,
            album=show.title,
            duration=episode.duration,
            file_path=downloaded_path or episode.audio_url,
            source="local" if downloaded_path else "stream",
            artwork_url=show.artwork_url
        )
        queue_manager.set_queue([podcast_track], 0)
        audio_engine.play_track(podcast_track)

    def on_mix_generated(mix_tracks: list[Track], mix_name: str) -> None:
        if mix_tracks:
            queue_manager.set_queue(mix_tracks, 0)
            audio_engine.play_track(mix_tracks[0])
            show_snackbar(page, f"Playing {mix_name}")

    def toggle_lyrics() -> None:
        nonlocal lyrics_active
        lyrics_active = not lyrics_active
        if lyrics_active:
            content_container.content = ft.Column(
                expand=True,
                spacing=0,
                controls=[
                    ft.Row(
                        controls=[
                            ft.TextButton(
                                "Back",
                                icon=ft.Icons.ARROW_BACK,
                                on_click=lambda e: toggle_lyrics(),
                            )
                        ],
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    lyrics_view,
                ],
            )
            if queue_manager.current_track:
                lyrics_view.load_for_track(queue_manager.current_track)
        else:
            content_container.content = views[pivot_nav.active_index]
        page.update()

    def open_quick_mix() -> None:
        all_library_tracks = local_provider.get_all_tracks()
        mix_dlg = QuickMixDialog(page, all_library_tracks, on_mix_generated)
        mix_dlg.show()

    def open_queue_modal() -> None:
        q_list = ft.ReorderableListView(
            expand=True,
            spacing=4,
            show_default_drag_handles=False,
        )

        def refresh_queue_items() -> None:
            q_list.controls = []
            for index, track in enumerate(queue_manager.queue):
                is_current = index == queue_manager.current_index
                q_list.controls.append(
                    ft.Container(
                        key=f"queue-item-{index}-{track.id}",
                        padding=8,
                        bgcolor=(
                            theme.surface_variant
                            if is_current
                            else ft.Colors.TRANSPARENT
                        ),
                        ink=True,
                        on_click=lambda e, item_index=index: play_queue_item(item_index),
                        content=ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.PLAY_ARROW
                                    if is_current
                                    else ft.Icons.MUSIC_NOTE,
                                    size=16,
                                    color=(
                                        theme.current_accent
                                        if is_current
                                        else ft.Colors.GREY_500
                                    ),
                                ),
                                ft.Text(
                                    track.title,
                                    size=13,
                                    weight=(
                                        ft.FontWeight.BOLD
                                        if is_current
                                        else ft.FontWeight.W_400
                                    ),
                                    expand=True,
                                    no_wrap=True,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.Text(
                                    track.artist,
                                    size=12,
                                    color=theme.text_secondary,
                                    width=110,
                                    no_wrap=True,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.ReorderableDragHandle(
                                    content=ft.Container(
                                        width=28,
                                        height=32,
                                        alignment=ft.Alignment(0, 0),
                                        content=ft.Icon(
                                            ft.Icons.DRAG_HANDLE,
                                            size=20,
                                            color=ft.Colors.GREY_500,
                                        ),
                                    ),
                                    mouse_cursor=ft.MouseCursor.GRAB,
                                ),
                            ],
                            spacing=8,
                        ),
                    )
                )

        def play_queue_item(index: int) -> None:
            track = queue_manager.play_at(index)
            if track:
                audio_engine.play_track(track)
                refresh_queue_items()
                q_list.update()

        def reorder_queue(event: ft.OnReorderEvent) -> None:
            if event.old_index is None or event.new_index is None:
                return
            if queue_manager.reorder_at(event.old_index, event.new_index):
                refresh_queue_items()
                q_list.update()

        refresh_queue_items()
        q_list.on_reorder = reorder_queue

        q_dlg = ft.AlertDialog(
            title=ft.Text("Up Next / Queue", weight=ft.FontWeight.BOLD),
            content=ft.Container(width=400, height=350, content=q_list),
            actions=[ft.TextButton("Close", on_click=lambda e: close_dialog(page, q_dlg))]
        )
        open_dialog(page, q_dlg)

    def refresh_theme() -> None:
        page.bgcolor = theme.bg_color
        pivot_nav._build_nav()
        player_bar._build_layout()
        page.update()

    def toggle_fullscreen() -> None:
        try:
            window = page.window
            if window is None:
                return
            if hasattr(window, "fullscreen"):
                window.fullscreen = not bool(getattr(window, "fullscreen", False))
            if hasattr(window, "borderless"):
                window.borderless = bool(getattr(window, "fullscreen", False))
        except Exception:
            pass
        page.update()

    # 6. Instantiate Views
    view_music = MusicView(page, local_provider, theme, play_track, play_next, add_to_queue)
    cloud_settings = CloudView(page, theme, sync_manager, embedded=True)
    view_podcasts = PodcastsView(
        page,
        db_conn,
        theme,
        play_podcast_episode,
        play_next,
        add_to_queue,
    )
    view_radio = RadioView(page, theme, play_radio_station, db_conn=db_conn)
    view_playlists = PlaylistsView(page, db_conn, theme, play_track, play_next)
    view_settings = SettingsView(
        page,
        theme,
        refresh_theme,
        db_conn,
        local_provider,
        view_music.load_tracks,
        cloud_settings,
    )

    views = [
        now_playing_view,
        view_music,
        view_podcasts,
        view_radio,
        view_playlists,
        view_settings,
    ]

    content_container = ft.Container(content=views[1], expand=True)

    def on_section_change(index: int) -> None:
        nonlocal lyrics_active
        lyrics_active = False
        content_container.content = views[index]
        player_bar.visible = index != 0
        if index == 4:
            view_playlists.load_playlists()
        page.update()

    # 7. Metro Pivot Navigation Header
    pivot_nav = PivotNav(
        sections=[
            "Now Playing",
            "Music",
            "Podcasts",
            "Radio",
            "Playlists",
            "Settings",
        ],
        active_index=1,
        theme=theme,
        on_section_change=on_section_change
    )
    pivot_nav.fullscreen_button.on_click = lambda e: toggle_fullscreen()

    def open_artist_in_music(artist_name: str) -> None:
        pivot_nav.set_active_index(1)
        on_section_change(1)
        view_music._open_artist_page(artist_name)

    def open_album_in_music(album_name: str, album_artist: str) -> None:
        pivot_nav.set_active_index(1)
        on_section_change(1)
        view_music._open_album_page(album_name, album_artist)

    # 8. Player Bar
    player_bar = PlayerBar(
        page=page,
        audio_engine=audio_engine,
        queue_manager=queue_manager,
        theme=theme,
        on_lyrics_click=toggle_lyrics,
        on_eq_click=lambda: eq_dialog.show(),
        on_sleep_click=lambda: sleep_dialog.show(),
        on_mix_click=open_quick_mix,
        on_queue_click=open_queue_modal,
        on_artist_click=open_artist_in_music,
        on_album_click=open_album_in_music,
        db_conn=db_conn,
    )
    if saved_session:
        player_bar.volume_slider.value = saved_session.volume
        now_playing_view.update_volume(
            saved_session.volume,
            saved_session.is_muted,
        )
        player_bar.btn_volume.icon = (
            ft.Icons.VOLUME_OFF
            if saved_session.is_muted
            else ft.Icons.VOLUME_MUTE
            if saved_session.volume == 0
            else ft.Icons.VOLUME_DOWN
            if saved_session.volume < 0.5
            else ft.Icons.VOLUME_UP
        )

    controller_manager = XInputController(
        page,
        pivot_nav,
        player_bar,
        audio_engine,
        queue_manager,
        toggle_fullscreen,
        views,
        on_section_change,
        toggle_lyrics,
        open_queue_modal,
    )

    # 9. Main Layout
    page.add(
        ft.Column(
            expand=True,
            spacing=0,
            controls=[
                pivot_nav,
                content_container,
                player_bar
            ]
        )
    )
    if saved_session:
        restored_track = queue_manager.current_track
        player_bar.update_track(restored_track)
        now_playing_view.update_track(restored_track)
        media_controls.update_track(restored_track)
        if restored_track:
            audio_engine.restore_paused_track(
                restored_track,
                saved_session.position_seconds,
            )
        player_bar.update_playback_state(False)
        now_playing_view.update_playback_state(False)

if __name__ == "__main__":
    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)
