import asyncio
import unittest
from unittest.mock import MagicMock, patch

import flet as ft

from mytunes.core.queue import QueueManager
from mytunes.models.track import Track
from mytunes.ui.components.player_bar import PlayerBar
from mytunes.ui.theme import MetroTheme


class TestPlayerBarNavigation(unittest.TestCase):

    def _create_player(self, page=None, theme=None):
        page = page or MagicMock()
        theme = theme or MetroTheme()
        return PlayerBar(
            page,
            MagicMock(),
            QueueManager(),
            theme,
            lambda: None,
            lambda: None,
            lambda: None,
            lambda: None,
            lambda: None,
        )

    def test_long_artist_and_album_names_scroll_within_track_info_width(self):
        player = PlayerBar(
            MagicMock(),
            MagicMock(),
            QueueManager(),
            MetroTheme(),
            lambda: None,
            lambda: None,
            lambda: None,
            lambda: None,
            lambda: None,
        )
        player_row = player.content.controls[1]
        track_info = player_row.controls[0].controls[1]
        metadata_row = track_info.controls[1]

        self.assertEqual(track_info.width, 200)
        self.assertEqual(metadata_row.width, 200)
        self.assertEqual(metadata_row.scroll, ft.ScrollMode.AUTO)
        self.assertTrue(player.track_artist_label.no_wrap)
        self.assertTrue(player.track_album_label.no_wrap)

    def test_controller_mode_shows_button_badges_and_restores_player_controls(self):
        player = self._create_player()

        player.set_controller_mode(True)
        player.set_controller_hints({"A": "Confirm", "Back": "Fullscreen"})

        self.assertTrue(player.controller_overlay.visible)
        self.assertIsInstance(player.controller_hints.controls[0], ft.Row)
        self.assertFalse(player.btn_lyrics.visible)
        self.assertFalse(player.btn_sleep.visible)
        self.assertFalse(player.btn_eq.visible)
        self.assertFalse(player.btn_shuffle.visible)
        self.assertTrue(player.btn_play.visible)
        self.assertFalse(player.time_current.visible)
        self.assertFalse(player.time_total.visible)

        player.set_controller_mode(False)

        self.assertTrue(player.btn_lyrics.visible)
        self.assertTrue(player.btn_sleep.visible)
        self.assertTrue(player.btn_eq.visible)
        self.assertTrue(player.btn_shuffle.visible)
        self.assertTrue(player.time_current.visible)
        self.assertTrue(player.time_total.visible)

    def test_local_artwork_accent_extraction_runs_as_a_background_task(self):
        page = MagicMock()
        theme = MetroTheme()
        player = self._create_player(page, theme)
        track = Track(
            id="track",
            title="Song",
            artwork_path="C:\\covers\\large.jpg",
        )

        with patch.object(
            theme,
            "find_dominant_accent",
            return_value="#aa3344",
        ) as find_accent:
            player.update_track(track, update_ui=False)

            page.run_task.assert_called_once_with(
                player._extract_track_accent,
                player._track_update_generation,
                track.artwork_path,
            )
            find_accent.assert_not_called()

            callback, generation, path = page.run_task.call_args.args
            with patch("mytunes.ui.components.player_bar.safe_update") as update:
                asyncio.run(callback(generation, path))

        self.assertEqual(theme.dynamic_accent, "#aa3344")
        self.assertEqual(player.btn_play.icon_color, "#aa3344")
        update.assert_called_once_with(player)

    def test_stale_artwork_accent_does_not_override_new_track(self):
        page = MagicMock()
        theme = MetroTheme()
        player = self._create_player(page, theme)
        track = Track(
            id="old-track",
            title="Old Song",
            artwork_path="C:\\covers\\old.jpg",
        )

        player.update_track(track, update_ui=False)
        callback, generation, path = page.run_task.call_args.args
        player.update_track(None, update_ui=False)

        with patch.object(
            theme,
            "find_dominant_accent",
            return_value="#aa3344",
        ) as find_accent:
            with patch("mytunes.ui.components.player_bar.safe_update") as update:
                asyncio.run(callback(generation, path))

        find_accent.assert_not_called()
        update.assert_not_called()
        self.assertIsNone(theme.dynamic_accent)

    def test_position_updates_only_individual_progress_controls(self):
        player = self._create_player()

        with patch("mytunes.ui.components.player_bar.safe_update") as update:
            player.update_position(65, 180)

        self.assertEqual(
            update.call_args_list,
            [
                unittest.mock.call(player.time_current),
                unittest.mock.call(player.time_total),
                unittest.mock.call(player.progress_slider),
            ],
        )

    def test_artist_and_album_buttons_forward_current_track(self):
        queue = QueueManager()
        track = Track(
            id="track",
            title="Song",
            artist="Track Artist",
            album="Track Album",
            album_artist="Album Artist",
        )
        queue.set_queue([track])
        artists = []
        albums = []
        player = PlayerBar(
            MagicMock(),
            MagicMock(),
            queue,
            MetroTheme(),
            lambda: None,
            lambda: None,
            lambda: None,
            lambda: None,
            lambda: None,
            on_artist_click=artists.append,
            on_album_click=lambda album, artist: albums.append((album, artist)),
        )

        self.assertEqual(player.track_artist.on_click, player._on_artist_click)
        self.assertEqual(player.track_album.on_click, player._on_album_click)
        player._on_artist_click(None)
        player._on_album_click(None)

        self.assertEqual(artists, ["Track Artist"])
        self.assertEqual(albums, [("Track Album", "Album Artist")])

    def test_album_navigation_falls_back_to_track_artist(self):
        queue = QueueManager()
        queue.set_queue([
            Track(id="track", title="Song", artist="Track Artist", album="Track Album")
        ])
        albums = []
        player = PlayerBar(
            MagicMock(),
            MagicMock(),
            queue,
            MetroTheme(),
            lambda: None,
            lambda: None,
            lambda: None,
            lambda: None,
            lambda: None,
            on_album_click=lambda album, artist: albums.append((album, artist)),
        )

        player._on_album_click(None)

        self.assertEqual(albums, [("Track Album", "Track Artist")])

    def test_collaboration_links_navigate_to_individual_artists_and_primary_album_artist(self):
        queue = QueueManager()
        track = Track(
            id="collaboration",
            title="Let Me Down Slowly",
            artist="Alec Benjamin feat. Alessia Cara",
            album="Let Me Down Slowly",
            album_artist="Alec Benjamin + Alessia Cara",
        )
        queue.set_queue([track])
        artists = []
        albums = []
        player = PlayerBar(
            MagicMock(),
            MagicMock(),
            queue,
            MetroTheme(),
            lambda: None,
            lambda: None,
            lambda: None,
            lambda: None,
            lambda: None,
            on_artist_click=artists.append,
            on_album_click=lambda album, artist: albums.append((album, artist)),
        )

        player.update_track(track)
        collaborator_button = next(
            control for control in player.collaborator_links.controls
            if isinstance(control, ft.TextButton)
        )
        player.track_artist.on_click(None)
        collaborator_button.on_click(None)
        player.track_album.on_click(None)

        self.assertEqual(artists, ["Alec Benjamin", "Alessia Cara"])
        self.assertEqual(albums, [("Let Me Down Slowly", "Alec Benjamin")])


if __name__ == "__main__":
    unittest.main()
