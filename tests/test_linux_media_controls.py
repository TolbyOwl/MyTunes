import importlib
import importlib.util
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from mytunes.core.queue import QueueManager, RepeatMode
from mytunes.models.track import Track

_linux_controls = None
if importlib.util.find_spec("dbus_next") is not None:
    with patch.object(sys, "platform", "linux"):
        _linux_controls = importlib.reload(
            importlib.import_module("mytunes.core.linux_media_controls")
        )


@unittest.skipIf(_linux_controls is None, "dbus-next is not installed")
class TestLinuxMprisInterface(unittest.TestCase):
    def setUp(self):
        self.track = Track(
            id="track/one",
            title="Song",
            artist="Artist",
            album="Album",
            duration=180,
            track_number=3,
        )
        self.queue = QueueManager()
        self.queue.set_queue([self.track, Track(id="track/two", title="Next")])
        self.audio = Mock()
        self.audio.is_playing = True
        self.audio.is_muted = False
        self.audio.volume = 0.75
        self.audio.playback_rate = 1.0
        self.owner = SimpleNamespace(
            audio_engine=self.audio,
            queue_manager=self.queue,
            current_track_id="/org/mpris/MediaPlayer2/track/747261636b2f6f6e65",
            position_seconds=12.5,
            artwork_uri="file:///home/user/.mytunes/art_cache/cover.jpg",
            is_stopped=False,
            actions=Mock(),
            _emit_player_properties=Mock(),
            set_shuffle=Mock(),
        )
        self.player = getattr(_linux_controls, "_MprisPlayer")(self.owner)

    def test_exposes_mpris_metadata_and_transport_capabilities(self):
        metadata = self.player.Metadata
        members = self.player.introspect()
        properties = {prop.name: prop for prop in members.properties}

        self.assertEqual(self.player.PlaybackStatus, "Playing")
        self.assertEqual(metadata["xesam:title"].value, "Song")
        self.assertEqual(metadata["xesam:artist"].value, ["Artist"])
        self.assertEqual(metadata["mpris:artUrl"].value, self.owner.artwork_uri)
        self.assertEqual(metadata["mpris:length"].value, 180_000_000)
        self.assertTrue(self.player.CanGoNext)
        self.assertEqual(properties["Metadata"].signature, "a{sv}")
        self.assertEqual(properties["Volume"].access.value, "readwrite")
        self.assertEqual(properties["Shuffle"].access.value, "readwrite")

    def test_writable_mpris_properties_use_existing_player_state(self):
        self.player.LoopStatus = "Track"
        self.player.Rate = 1.5
        self.player.Volume = 0.4
        self.player.Shuffle = True

        self.assertEqual(self.queue.repeat_mode, RepeatMode.ONE)
        self.audio.set_playback_rate.assert_called_once_with(1.5)
        self.audio.set_volume.assert_called_once_with(0.4)
        self.owner.set_shuffle.assert_called_once_with(True)

    def test_native_transport_methods_dispatch_existing_actions(self):
        self.player.Next()
        self.player.Previous()
        self.player.PlayPause()
        self.player.Stop()

        self.assertEqual(
            self.owner.actions.dispatch.call_args_list,
            [
                call("next"),
                call("previous"),
                call("play_pause"),
                call("stop"),
            ],
        )

    def test_shuffle_toggles_preserve_current_track_and_original_order(self):
        tracks = [
            Track(id="first", title="First"),
            Track(id="current", title="Current"),
            Track(id="last", title="Last"),
        ]
        queue = QueueManager()
        queue.set_queue(tracks, start_index=1)
        owner = SimpleNamespace(
            queue_manager=queue,
            _emit_player_properties=Mock(),
        )

        adapter_class = getattr(_linux_controls, "LinuxMprisControls")
        adapter_class.set_shuffle(owner, True)

        self.assertIs(queue.current_track, tracks[1])
        self.assertTrue(queue.is_shuffled)
        adapter_class.set_shuffle(owner, False)
        self.assertEqual(queue.queue, tracks)
        self.assertIs(queue.current_track, tracks[1])
        self.assertFalse(queue.is_shuffled)


if __name__ == "__main__":
    unittest.main()
