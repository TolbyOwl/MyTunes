import unittest
from unittest.mock import MagicMock, Mock

import flet as ft

from mytunes.models.track import Track
from mytunes.core.queue import RepeatMode
from mytunes.ui.theme import MetroTheme
from mytunes.ui.views.now_playing_view import NowPlayingView


class TestNowPlayingView(unittest.TestCase):
    def setUp(self):
        self.metadata_provider = Mock()
        self.metadata_provider.get_cached_metadata.return_value = {
            "picture_url": "https://example.com/artist.jpg",
            "picture_medium": None,
        }
        self.metadata_provider.fetch_and_cache.return_value = {
            "picture_url": "https://example.com/artist.jpg",
            "picture_medium": None,
        }
        self.on_favorite = Mock()
        self.on_mix = Mock()
        self.on_repeat = Mock(return_value=RepeatMode.ALL)
        self.on_artist_click = Mock()
        self.on_album_click = Mock()
        self.view = NowPlayingView(
            MagicMock(),
            MetroTheme(),
            self.metadata_provider,
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            self.on_favorite,
            self.on_mix,
            self.on_repeat,
            lambda: RepeatMode.OFF,
            Mock(),
            Mock(return_value="1.25x"),
            Mock(),
            Mock(),
            Mock(),
            Mock(),
            Mock(return_value=False),
            self.on_artist_click,
            self.on_album_click,
        )

    def test_uses_cached_artist_portrait_and_track_artwork(self):
        track = Track(
            id="track-1",
            title="Song",
            artist="Artist",
            album="Album",
            duration=180,
            artwork_path="C:\\music\\cover.jpg",
        )

        self.view.update_track(track)

        self.assertEqual(
            self.view.background_image.image.src,
            "https://example.com/artist.jpg",
        )
        self.assertEqual(
            self.view.background_image.image.fit,
            ft.BoxFit.COVER,
        )
        self.assertEqual(self.view.album_image.src, "C:\\music\\cover.jpg")
        self.assertEqual(self.view.title_text.value, "Song")
        self.assertEqual(self.view.artist_text.value, "Artist")
        self.assertEqual(self.view.album_text.value, "Album")

    def test_radio_track_uses_station_art_without_seeking(self):
        self.metadata_provider.get_cached_metadata.reset_mock()
        track = Track(
            id="radio_station",
            title="Station",
            artist="Radio (Global)",
            source="stream",
            artwork_url="https://example.com/station.png",
        )

        self.view.update_track(track)

        self.assertEqual(
            self.view.background_image.image.src,
            "https://example.com/station.png",
        )
        self.assertEqual(self.view.album_image.src, "https://example.com/station.png")
        self.assertTrue(self.view.progress_slider.disabled)
        self.metadata_provider.get_cached_metadata.assert_not_called()

    def test_playback_state_and_position_update_controls(self):
        self.view.update_playback_state(True)
        self.view.update_position(65, 180)

        self.assertEqual(self.view.play_button.icon, ft.Icons.PAUSE_CIRCLE_FILLED)
        self.assertEqual(self.view.time_current.value, "1:05")
        self.assertEqual(self.view.time_total.value, "3:00")
        self.assertEqual(self.view.progress_slider.value, 65)

    def test_artist_and_album_buttons_navigate_to_current_track(self):
        track = Track(
            id="track-1",
            title="Song",
            artist="Primary Artist feat. Guest Artist",
            album="Album",
            album_artist="Album Artist",
        )
        self.view.update_track(track)

        self.view.artist_button.on_click(None)
        self.view.album_button.on_click(None)

        self.on_artist_click.assert_called_once_with("Primary Artist")
        self.on_album_click.assert_called_once_with("Album", "Album Artist")

    def test_favorite_and_repeat_controls_invoke_callbacks(self):
        track = Track(id="track-1", title="Song", is_favorite=False)
        self.view.update_track(track)
        self.on_favorite.side_effect = lambda: setattr(track, "is_favorite", True)
        self.view.on_repeat_mode = lambda: RepeatMode.ALL

        self.view.favorite_button.on_click(None)
        self.view._toggle_repeat(None)

        self.on_favorite.assert_called_once_with()
        self.on_repeat.assert_called_once_with()
        self.assertEqual(self.view.favorite_button.icon, ft.Icons.FAVORITE)
        self.assertEqual(self.view.repeat_button.icon_color, self.view._mt.current_accent)

    def test_speed_control_updates_its_label(self):
        self.view.speed_button.on_click(None)

        self.assertEqual(self.view.speed_button.content, "1.25x")

    def test_controller_focus_highlights_buttons_and_restores_original_style(self):
        track = Track(id="track-1", title="Song")
        self.view.update_track(track)
        focusables = self.view.controller_focusables()
        play_button_index = focusables.index(self.view.play_button)
        original_style = self.view.play_button.style
        original_color = self.view.play_button.icon_color

        self.view.set_controller_focus(play_button_index)

        self.assertEqual(
            self.view.play_button.style.side.color,
            self.view._mt.current_accent,
        )
        self.assertEqual(self.view.play_button.icon_color, self.view._mt.current_accent)

        self.view.set_controller_focus(-1)

        self.assertIs(self.view.play_button.style, original_style)
        self.assertEqual(self.view.play_button.icon_color, original_color)

    def test_controller_focus_highlights_slider_and_restores_original_colors(self):
        track = Track(id="track-1", title="Song", duration=180)
        self.view.update_track(track)
        focusables = self.view.controller_focusables()
        slider_index = focusables.index(self.view.progress_slider)
        original_colors = (
            self.view.progress_slider.active_color,
            self.view.progress_slider.inactive_color,
            self.view.progress_slider.thumb_color,
            self.view.progress_slider.overlay_color,
        )

        self.view.set_controller_focus(slider_index)

        self.assertEqual(self.view.progress_slider.active_color, ft.Colors.WHITE)
        self.assertEqual(
            self.view.progress_slider.inactive_color,
            self.view._mt.current_accent,
        )
        self.assertEqual(
            self.view.progress_slider.thumb_color,
            self.view._mt.current_accent,
        )

        self.view.set_controller_focus(-1)

        self.assertEqual(
            (
                self.view.progress_slider.active_color,
                self.view.progress_slider.inactive_color,
                self.view.progress_slider.thumb_color,
                self.view.progress_slider.overlay_color,
            ),
            original_colors,
        )


if __name__ == "__main__":
    unittest.main()
