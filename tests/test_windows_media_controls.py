import asyncio
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from mytunes.core.audio import AudioEngine
from mytunes.core.media_artwork import MediaArtworkCache
from mytunes.core.windows_media_controls import WindowsMediaControls
from mytunes.models.track import Track


class TestWindowsMediaControls(unittest.TestCase):
    def test_is_disabled_outside_windows(self):
        page = Mock()
        audio_engine = Mock()
        queue_manager = Mock()

        with patch(
            "mytunes.core.windows_media_controls.sys.platform", "linux"
        ):
            controls = WindowsMediaControls(page, audio_engine, queue_manager)

        self.assertIsNone(controls._controls)

    def test_updates_track_metadata_and_timeline(self):
        updater = Mock()
        updater.music_properties = SimpleNamespace()
        win_controls = Mock()
        timeline = SimpleNamespace()
        media_controls = object.__new__(WindowsMediaControls)
        media_controls._display_updater = updater
        media_controls._controls = win_controls
        media_controls._playback_status = SimpleNamespace(STOPPED="stopped")
        media_controls._playback_type = SimpleNamespace(MUSIC="music")
        media_controls._timeline_properties = Mock(return_value=timeline)
        media_controls.page = Mock()
        media_controls._track_generation = 0

        track = Track(
            id="track-1",
            title="Song",
            artist="Artist",
            album_artist="Album Artist",
            album="Album",
            duration=180,
            track_number=4,
        )
        media_controls.update_track(track)

        self.assertEqual(updater.type, "music")
        self.assertEqual(updater.music_properties.title, "Song")
        self.assertEqual(updater.music_properties.artist, "Artist")
        self.assertEqual(updater.music_properties.album_artist, "Album Artist")
        self.assertEqual(updater.music_properties.album_title, "Album")
        self.assertEqual(updater.music_properties.track_number, 4)
        updater.update.assert_called_once_with()
        win_controls.update_timeline_properties.assert_called_once_with(timeline)
        self.assertEqual(timeline.position, timedelta(0))
        self.assertEqual(timeline.end_time, timedelta(seconds=180))
        media_controls.page.run_task.assert_called_once_with(
            media_controls._update_artwork, 1, track
        )

    def test_routes_transport_buttons_to_shared_dispatcher(self):
        media_controls = object.__new__(WindowsMediaControls)
        media_controls.actions = Mock()
        media_controls._buttons = SimpleNamespace(
            PLAY="play",
            PAUSE="pause",
            STOP="stop",
            NEXT="next",
            PREVIOUS="previous",
        )

        for button in ("play", "pause", "stop", "next", "previous"):
            media_controls._on_button_pressed(None, SimpleNamespace(button=button))

        self.assertEqual(
            media_controls.actions.dispatch.call_args_list,
            [call("play"), call("pause"), call("stop"), call("next"), call("previous")],
        )

    def test_publishes_resolved_artwork_to_windows_media_session(self):
        media_controls = object.__new__(WindowsMediaControls)
        media_controls._track_generation = 2
        media_controls._display_updater = Mock()
        media_controls._storage_file = Mock()
        media_controls._stream_reference = Mock()
        media_controls._stream_reference.create_from_file.return_value = "stream-ref"
        media_controls.artwork_cache = MediaArtworkCache()
        track = Track(id="artwork", title="Artwork")

        with patch.object(
            media_controls.artwork_cache,
            "resolve",
            new=AsyncMock(return_value=Path("C:/covers/cover.jpg")),
        ):
            asyncio.run(media_controls._update_artwork(2, track))

        media_controls._storage_file.get_file_from_path_async.assert_called_once_with(
            "C:\\covers\\cover.jpg"
        )
        self.assertEqual(media_controls._display_updater.thumbnail, "stream-ref")
        media_controls._display_updater.update.assert_called_once_with()

    def test_ignores_artwork_from_superseded_track(self):
        media_controls = object.__new__(WindowsMediaControls)
        media_controls._track_generation = 3
        media_controls._display_updater = Mock()
        media_controls.artwork_cache = MediaArtworkCache()

        with patch.object(
            media_controls.artwork_cache,
            "resolve",
            new=AsyncMock(return_value=Path("C:/covers/stale.jpg")),
        ):
            asyncio.run(
                media_controls._update_artwork(
                    2, Track(id="old", title="Old track")
                )
            )

        media_controls._display_updater.update.assert_not_called()

    def test_audio_stop_notifies_the_system_media_session(self):
        audio_engine = object.__new__(AudioEngine)
        audio_engine.audio = Mock()
        audio_engine.is_playing = True
        audio_engine.current_position = 12
        audio_engine._stop_poll = Mock()
        audio_engine.on_state_changed = Mock()
        audio_engine.on_stopped = Mock()
        audio_engine.app_page = Mock()

        audio_engine.stop()

        audio_engine.on_state_changed.assert_called_once_with(False)
        audio_engine.on_stopped.assert_called_once_with()
        self.assertEqual(audio_engine.current_position, 0.0)

    def test_audio_volume_changes_notify_platform_controls(self):
        audio_engine = object.__new__(AudioEngine)
        audio_engine.volume = 1.0
        audio_engine.is_muted = False
        audio_engine.audio = Mock()
        audio_engine.app_page = Mock()
        audio_engine.on_volume_changed = Mock()

        audio_engine.set_volume(0.35)
        audio_engine.toggle_mute()

        self.assertEqual(audio_engine.on_volume_changed.call_args_list, [
            call(0.35),
            call(0.0),
        ])


if __name__ == "__main__":
    unittest.main()
