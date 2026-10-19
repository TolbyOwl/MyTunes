import unittest
from unittest.mock import MagicMock, Mock

import flet as ft

from mytunes.models.playlist import Playlist
from mytunes.models.schema import init_db
from mytunes.ui.theme import MetroTheme
from mytunes.ui.views.playlists_view import PlaylistsView


class TestPlaylistSongMenu(unittest.TestCase):
    def setUp(self):
        self.connection = init_db(":memory:")
        self.connection.execute(
            "INSERT INTO tracks (id, title, artist, album, file_path, date_added) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("track-1", "Song", "Artist", "Album", "song.mp3", 1.0),
        )
        self.connection.execute(
            "INSERT INTO playlists (id, name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("playlist-1", "Playlist", 1.0, 1.0),
        )
        self.connection.execute(
            "INSERT INTO playlist_tracks (playlist_id, track_id, position) "
            "VALUES (?, ?, ?)",
            ("playlist-1", "track-1", 0),
        )
        self.connection.commit()
        self.on_play_next = Mock()
        self.view = PlaylistsView(
            MagicMock(),
            self.connection,
            MetroTheme(),
            Mock(),
            self.on_play_next,
        )
        self.view._select_playlist(
            Playlist(id="playlist-1", name="Playlist")
        )

    def tearDown(self):
        self.connection.close()

    def test_playlist_song_menu_can_queue_track_to_play_next(self):
        row = self.view.tracks_view.controls[2]
        menu = row.content.controls[-1]

        self.assertIsInstance(menu, ft.PopupMenuButton)
        self.assertEqual(menu.items[0].content, "Play Next")
        menu.items[0].on_click(None)

        self.on_play_next.assert_called_once_with(self.view.playlist_tracks[0])

    def test_loading_playlists_refreshes_selected_playlist_contents(self):
        self.connection.execute(
            "INSERT INTO tracks (id, title, file_path, date_added) "
            "VALUES (?, ?, ?, ?)",
            ("track-2", "Another Song", "another.mp3", 2.0),
        )
        self.connection.execute(
            "INSERT INTO playlist_tracks (playlist_id, track_id, position) "
            "VALUES (?, ?, ?)",
            ("playlist-1", "track-2", 1),
        )
        self.connection.commit()

        self.view.load_playlists()

        self.assertEqual(
            [track.id for track in self.view.playlist_tracks],
            ["track-1", "track-2"],
        )
        self.assertIn("2 tracks", self.view.tracks_view.controls[0].controls[0].value)


if __name__ == "__main__":
    unittest.main()
