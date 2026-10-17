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

    # 2. Theme & Design
    theme = MetroTheme(is_dark=True, default_accent="#0078D7")
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = theme.bg_color

    # 3. Queue & Audio Engine
    queue_manager = QueueManager()
    audio_engine = AudioEngine(page, queue_manager)

    # 4. Dialogs & Overlays
    sleep_dialog = SleepTimerDialog(page, audio_engine)
    eq_dialog = EqualizerDialog(page)

    # 5. Lyrics View (Toggleable)
    lyrics_view = LyricsView(page)
    lyrics_active = False

    # Forward declaration for UI callbacks
    def on_track_changed(track: Track | None) -> None:
        player_bar.update_track(track)
        if track and lyrics_active:
            lyrics_view.load_for_track(track)
        page.update()

    queue_manager.on_track_changed = on_track_changed

    audio_engine.on_state_changed = lambda is_playing: player_bar.update_playback_state(is_playing)
    audio_engine.on_position_changed = lambda cur, tot: (
        player_bar.update_position(cur, tot),
        lyrics_view.update_position(cur) if lyrics_active else None
    )

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
        podcast_track = Track(
            id=f"pod_{episode.id}",
            title=episode.title,
            artist=show.author or show.title,
            album=show.title,
            file_path=episode.audio_url,
            source="stream",
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
        tracks = queue_manager.queue
        curr_idx = queue_manager.current_index
        q_list = ft.ListView(expand=True, spacing=4)
        for i, t in enumerate(tracks):
            is_cur = (i == curr_idx)
            q_list.controls.append(
                ft.Container(
                    padding=8,
                    bgcolor=theme.surface_variant if is_cur else ft.Colors.TRANSPARENT,
                    content=ft.Row([
                        ft.Icon(ft.Icons.PLAY_ARROW if is_cur else ft.Icons.MUSIC_NOTE, size=16, color=theme.current_accent if is_cur else ft.Colors.GREY_500),
                        ft.Text(t.title, size=13, weight=ft.FontWeight.BOLD if is_cur else ft.FontWeight.W_400, expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(t.artist, size=12, color=theme.text_secondary),
                    ], spacing=8)
                )
            )

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
    view_cloud = CloudView(page, theme, sync_manager)
    view_podcasts = PodcastsView(page, db_conn, theme, play_podcast_episode)
    view_radio = RadioView(page, theme, play_radio_station, db_conn=db_conn)
    view_playlists = PlaylistsView(page, db_conn, theme, play_track)
    view_settings = SettingsView(page, theme, refresh_theme)

    views = [view_music, view_cloud, view_podcasts, view_radio, view_playlists, view_settings]

    content_container = ft.Container(
        content=views[0],
        expand=True
    )

    def on_section_change(index: int) -> None:
        nonlocal lyrics_active
        lyrics_active = False
        content_container.content = views[index]
        page.update()

    # 7. Metro Pivot Navigation Header
    pivot_nav = PivotNav(
        sections=["Music", "Cloud", "Podcasts", "Radio", "Playlists", "Settings"],
        active_index=0,
        theme=theme,
        on_section_change=on_section_change
    )

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
        db_conn=db_conn,
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

if __name__ == "__main__":
    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)
