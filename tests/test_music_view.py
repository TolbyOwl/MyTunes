import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import flet as ft

from mytunes.models.track import Track
from mytunes.ui.theme import MetroTheme
from mytunes.ui.views.music_view import MusicView


class TestMusicSongList(unittest.TestCase):

    def _create_view(self, tracks):
        provider = Mock()
        provider.get_all_tracks.return_value = tracks
        provider.conn = MagicMock()
        play_track = Mock()
        view = MusicView(
            MagicMock(),
            provider,
            MetroTheme(),
            play_track,
            Mock(),
            Mock(),
        )
        return view, play_track

    def test_alphabetical_song_list_groups_letters_digits_and_other_scripts(self):
        tracks = [
            Track(id="z", title="Zebra"),
            Track(id="two", title="2nd song"),
            Track(id="japanese", title="東京"),
            Track(id="a", title="Apple"),
            Track(id="accented", title="Éclair"),
            Track(id="symbol", title="# Hashtag"),
            Track(id="b", title="Beta"),
            Track(id="one", title="1st song"),
        ]
        view, _ = self._create_view(tracks)

        headings = [
            control.key
            for control in view.songs_list.controls
            if isinstance(control, ft.Container) and control.key is not None
        ]

        self.assertEqual(
            [str(key) for key in headings],
            [
                "songs-index-#",
                "songs-index-A",
                "songs-index-B",
                "songs-index-E",
                "songs-index-Z",
                "songs-index-~",
            ],
        )
        self.assertTrue(all(isinstance(key, ft.ScrollKey) for key in headings))

    def test_alphabetical_list_shows_direct_letter_rail_with_empty_groups_disabled(self):
        view, _ = self._create_view([
            Track(id="a", title="Apple"),
            Track(id="number", title="7th song"),
            Track(id="other", title="東京"),
        ])

        self.assertEqual(
            list(view.song_index_buttons),
            ["#", *"ABCDEFGHIJKLMNOPQRSTUVWXYZ", "~"],
        )
        self.assertFalse(view.song_index_buttons["#"].disabled)
        self.assertFalse(view.song_index_buttons["A"].disabled)
        self.assertFalse(view.song_index_buttons["~"].disabled)
        self.assertTrue(view.song_index_buttons["B"].disabled)
        song_layout = view.content_area.content
        if not isinstance(song_layout, ft.Row):
            self.fail("Expected the song list and direct letter rail in a row")
        list_container = song_layout.controls[0]
        letter_rail = song_layout.controls[1]
        if not isinstance(list_container, ft.Container):
            self.fail("Expected the song list to occupy the flexible row space")
        if not isinstance(letter_rail, ft.Column):
            self.fail("Expected a fixed-width letter rail")
        self.assertIs(list_container.content, view.songs_list)
        self.assertEqual(letter_rail.width, 36)
        self.assertIsNone(letter_rail.expand)
        self.assertIsInstance(view.songs_list, ft.Column)
        self.assertEqual(view.songs_list.scroll, ft.ScrollMode.AUTO)

    def test_direct_letter_selection_jumps_to_selected_group(self):
        view, _ = self._create_view([
            Track(id="a", title="Apple"),
            Track(id="b", title="Beta"),
        ])
        view.songs_list.scroll_to = AsyncMock()

        asyncio.run(view._jump_to_song_group("B"))

        view.songs_list.scroll_to.assert_awaited_once_with(
            scroll_key="songs-index-B",
            duration=280,
            curve=ft.AnimationCurve.EASE_OUT_CUBIC,
        )
        self.assertIsInstance(view.content_area.content, ft.Row)

    def test_clicking_letter_schedules_scroll_to_that_group(self):
        view, _ = self._create_view([
            Track(id="a", title="Apple"),
            Track(id="b", title="Beta"),
        ])
        run_task = Mock()
        setattr(view.app_page, "run_task", run_task)
        button = view.song_index_buttons["B"]
        callback = getattr(button, "on_click", None)
        if not callable(callback):
            self.fail("Expected the letter button to have a click handler")

        callback(None)

        run_task.assert_called_once_with(view._jump_to_song_group, "B")

    def test_descending_sort_reverses_letter_rail(self):
        view, _ = self._create_view([
            Track(id="a", title="Apple"),
            Track(id="z", title="Zebra"),
        ])

        view.current_sort = "alpha_desc"
        view._render_songs_tab(view.displayed_tracks)

        self.assertEqual(
            list(view.song_index_buttons),
            ["#", *reversed("ABCDEFGHIJKLMNOPQRSTUVWXYZ"), "~"],
        )

    def test_date_sorted_songs_show_shuffle_but_not_letter_index(self):
        view, _ = self._create_view([
            Track(id="a", title="Apple"),
            Track(id="b", title="Beta"),
        ])

        view.current_sort = "date_desc"
        view._render_songs_tab(view.displayed_tracks)
        toolbar_container = view.songs_list.controls[0]
        if not isinstance(toolbar_container, ft.Container):
            self.fail("Expected the songs-list toolbar container")
        shuffle_button = toolbar_container.content
        if not isinstance(shuffle_button, ft.OutlinedButton):
            self.fail("Expected the shuffle action button")
        self.assertEqual(shuffle_button.content, "Play all on shuffle")
        self.assertFalse(view._song_group_keys)
        self.assertEqual(view.song_index_buttons, {})
        self.assertIsInstance(view.songs_list, ft.ListView)

    def test_missing_album_art_has_visible_album_placeholder(self):
        view, _ = self._create_view([])

        album_card = view._build_album_card(
            {"name": "Album", "artist": "Artist", "artwork_path": None}
        )
        artwork = album_card.content.controls[0]
        if not isinstance(artwork, ft.Stack):
            self.fail("Expected album artwork to include an explicit placeholder")

        placeholder, image = artwork.controls
        self.assertEqual(artwork.width, 160)
        self.assertEqual(placeholder.content.icon, ft.Icons.ALBUM)
        self.assertFalse(image.visible)

    def test_missing_artist_art_has_visible_artist_placeholder(self):
        view, _ = self._create_view([])
        view.metadata_provider.fetch_and_cache = Mock(return_value={})

        with patch("mytunes.ui.views.music_view.threading.Thread") as thread:
            artist_card = view._build_artist_card(
                {
                    "name": "Artist",
                    "picture_url": None,
                    "local_fallback_art": None,
                    "albums": set(),
                    "tracks": [],
                }
            )

        artwork = artist_card.content.controls[0]
        if not isinstance(artwork, ft.Stack):
            self.fail("Expected artist artwork to include an explicit placeholder")

        placeholder, image = artwork.controls
        self.assertEqual(placeholder.content.icon, ft.Icons.PERSON)
        self.assertFalse(image.visible)
        thread.assert_called_once()

    def test_artist_credit_separators_split_names_and_keep_unspaced_slashes(self):
        self.assertEqual(
            MusicView._split_artist_credits(
                "Alpha, Beta; Gamma feat. Delta ft Epsilon featuring Zeta "
                "& Eta + Theta / Iota with Kappa x Lambda vs. Mu and Nu AC/DC"
            ),
            [
                "Alpha",
                "Beta",
                "Gamma",
                "Delta",
                "Epsilon",
                "Zeta",
                "Eta",
                "Theta",
                "Iota",
                "Kappa",
                "Lambda",
                "Mu",
                "Nu AC/DC",
            ],
        )

    def test_artists_tab_lists_each_track_and_album_artist_credit(self):
        track = Track(
            id="collaboration",
            title="Song",
            artist="Alpha feat. Beta",
            album="Shared Album",
            album_artist="Album Artist",
        )
        view, _ = self._create_view([track])
        view.metadata_provider.get_cached_metadata = Mock(return_value=None)

        with patch("mytunes.ui.views.music_view.threading.Thread"):
            view._render_artists_tab([track])

        artist_names = [
            card.content.controls[1].value
            for card in view.content_area.content.controls
        ]
        self.assertEqual(artist_names, ["Album Artist", "Alpha", "Beta"])

    def test_artist_page_lists_guest_album_under_appears_on(self):
        tracks = [
            Track(
                id="album-owner-track",
                title="Lead song",
                artist="Album Artist",
                album="The Album",
                album_artist="Album Artist",
            ),
            Track(
                id="guest-track",
                title="Guest song",
                artist="Album Artist feat. Guest Artist",
                album="Other Artist Album",
                album_artist="Other Artist",
            ),
        ]
        view, _ = self._create_view(tracks)
        view.metadata_provider.get_cached_metadata = Mock(return_value=None)
        view._build_album_card = Mock(
            side_effect=lambda info: ft.Container(data=(info["name"], info["artist"]))
        )

        with patch("mytunes.ui.views.music_view.threading.Thread"):
            view._render_artist_page("Guest Artist")

        controls = view.content_area.content.controls
        section_index = next(
            index
            for index, control in enumerate(controls)
            if isinstance(control, ft.Text) and control.value == "APPEARS ON"
        )
        appeared_album = controls[section_index + 1].controls[0]
        self.assertEqual(appeared_album.data, ("Other Artist Album", "Other Artist"))
        self.assertNotIn(
            "ALBUMS",
            [control.value for control in controls if isinstance(control, ft.Text)],
        )

        with patch("mytunes.ui.views.music_view.threading.Thread"):
            view._render_artist_page("Album Artist")

        controls = view.content_area.content.controls
        section_labels = [
            control.value for control in controls if isinstance(control, ft.Text)
        ]
        self.assertIn("ALBUMS", section_labels)
        self.assertIn("APPEARS ON", section_labels)
        album_section_index = next(
            index
            for index, control in enumerate(controls)
            if isinstance(control, ft.Text) and control.value == "ALBUMS"
        )
        self.assertEqual(
            controls[album_section_index + 1].controls[0].data,
            ("The Album", "Album Artist"),
        )

    def test_collaborative_album_uses_primary_album_artist_for_ownership(self):
        track = Track(
            id="let-me-down-slowly",
            title="Let Me Down Slowly",
            artist="Alec Benjamin feat. Alessia Cara",
            album="Let Me Down Slowly",
            album_artist="Alec Benjamin + Alessia Cara",
        )
        view, _ = self._create_view([track])
        view.metadata_provider.get_cached_metadata = Mock(return_value=None)
        view._build_album_card = Mock(
            side_effect=lambda info: ft.Container(data=(info["name"], info["artist"]))
        )

        with patch("mytunes.ui.views.music_view.threading.Thread"):
            view._render_artist_page("Alessia Cara")

        controls = view.content_area.content.controls
        section_labels = [
            control.value for control in controls if isinstance(control, ft.Text)
        ]
        self.assertNotIn("ALBUMS", section_labels)
        self.assertIn("APPEARS ON", section_labels)
        appears_control_index = next(
            index for index, control in enumerate(controls)
            if isinstance(control, ft.Text) and control.value == "APPEARS ON"
        )
        self.assertEqual(
            controls[appears_control_index + 1].controls[0].data,
            ("Let Me Down Slowly", "Alec Benjamin"),
        )

        with patch("mytunes.ui.views.music_view.threading.Thread"):
            view._render_artist_page("Alec Benjamin")

        controls = view.content_area.content.controls
        section_labels = [
            control.value for control in controls if isinstance(control, ft.Text)
        ]
        self.assertIn("ALBUMS", section_labels)
        self.assertNotIn("APPEARS ON", section_labels)

    def test_play_all_shuffle_uses_a_shuffled_copy_of_displayed_tracks(self):
        tracks = [
            Track(id="a", title="Apple"),
            Track(id="b", title="Beta"),
            Track(id="c", title="Cherry"),
        ]
        view, play_track = self._create_view(tracks)

        with patch("mytunes.ui.views.music_view.random.shuffle", side_effect=lambda items: items.reverse()):
            view._play_songs_random(tracks)

        played_track, queued_tracks = play_track.call_args.args
        self.assertEqual(played_track.id, "c")
        self.assertEqual([track.id for track in queued_tracks], ["c", "b", "a"])
        self.assertEqual([track.id for track in tracks], ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
