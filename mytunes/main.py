from __future__ import annotations
import os
import sys
import flet as ft

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mytunes.models.schema import init_db
from mytunes.models.track import Track
from mytunes.models.radio import RadioStation
from mytunes.models.podcast import Episode, PodcastShow
from mytunes.providers.local import LocalProvider
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
from mytunes.ui.views.podcasts_view import PodcastsView
from mytunes.ui.views.cloud_view import CloudView
from mytunes.ui.views.playlists_view import PlaylistsView
from mytunes.ui.views.settings_view import SettingsView

from mytunes.ui.dialog_utils import show_snackbar, open_dialog, close_dialog

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

    # Forward declaration for UI callbacks
    def on_track_changed(track: Track | None) -> None:
        player_bar.update_track(track)
        media_controls.update_track(track)
        if track and lyrics_active:
            lyrics_view.load_for_track(track)
        page.update()

    queue_manager.on_track_changed = on_track_changed

    def on_playback_state_changed(is_playing: bool) -> None:
        player_bar.update_playback_state(is_playing)
        media_controls.update_playback_state(is_playing)

    def on_position_changed(current: float, total: float) -> None:
        player_bar.update_position(current, total)
        media_controls.update_position(current, total)
        persist_playback_session()
        if lyrics_active:
            lyrics_view.update_position(current)

    def on_volume_changed(volume: float) -> None:
        media_controls.update_volume(volume)
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
            content_container.content = lyrics_view
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

    views = [view_music, view_podcasts, view_radio, view_playlists, view_settings]

    content_container = ft.Container(content=views[0], expand=True)

    def on_section_change(index: int) -> None:
        nonlocal lyrics_active
        lyrics_active = False
        content_container.content = views[index]
        page.update()

    # 7. Metro Pivot Navigation Header
    pivot_nav = PivotNav(
        sections=["Music", "Podcasts", "Radio", "Playlists", "Settings"],
        active_index=0,
        theme=theme,
        on_section_change=on_section_change
    )

    def open_artist_in_music(artist_name: str) -> None:
        pivot_nav.set_active_index(0)
        on_section_change(0)
        view_music._open_artist_page(artist_name)

    def open_album_in_music(album_name: str, album_artist: str) -> None:
        pivot_nav.set_active_index(0)
        on_section_change(0)
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
        player_bar.btn_volume.icon = (
            ft.Icons.VOLUME_OFF
            if saved_session.is_muted
            else ft.Icons.VOLUME_MUTE
            if saved_session.volume == 0
            else ft.Icons.VOLUME_DOWN
            if saved_session.volume < 0.5
            else ft.Icons.VOLUME_UP
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
        media_controls.update_track(restored_track)
        if restored_track:
            audio_engine.restore_paused_track(
                restored_track,
                saved_session.position_seconds,
            )
        player_bar.update_playback_state(False)

if __name__ == "__main__":
    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)
