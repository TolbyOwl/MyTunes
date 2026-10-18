import unittest
from unittest.mock import MagicMock

import flet as ft

from mytunes.core.queue import QueueManager
from mytunes.models.track import Track
from mytunes.ui.components.player_bar import PlayerBar
from mytunes.ui.theme import MetroTheme


class TestPlayerBarNavigation(unittest.TestCase):

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
        track_info = player.content.controls[0].controls[1]
        metadata_row = track_info.controls[1]

        self.assertEqual(track_info.width, 200)
        self.assertEqual(metadata_row.width, 200)
        self.assertEqual(metadata_row.scroll, ft.ScrollMode.AUTO)
        self.assertTrue(player.track_artist_label.no_wrap)
        self.assertTrue(player.track_album_label.no_wrap)

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
