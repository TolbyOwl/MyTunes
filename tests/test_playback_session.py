import asyncio
import json
import unittest
from unittest.mock import Mock, patch

from mytunes.core.audio import AudioEngine
from mytunes.core.playback_session import PlaybackSessionStore
from mytunes.core.queue import QueueManager
from mytunes.models.schema import init_db
from mytunes.models.track import Track


class TestPlaybackSessionStore(unittest.TestCase):
    def setUp(self):
        self.connection = init_db(":memory:")
        self.tracks = [
            Track(id="one", title="First", file_path="first.mp3"),
            Track(id="two", title="Second", file_path="second.mp3"),
            Track(id="three", title="Third", file_path="third.mp3"),
        ]
        self.queue = QueueManager()
        self.queue.set_queue(self.tracks, start_index=1)
        self.store = PlaybackSessionStore(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_saved_queue_position_and_volume_restore(self):
        self.store.save(
            self.queue,
            position_seconds=42.5,
            volume=0.35,
            is_muted=True,
            force_position=True,
        )

        restored = self.store.load(self.tracks)

        self.assertIsNotNone(restored)
        self.assertEqual([track.id for track in restored.tracks], ["one", "two", "three"])
        self.assertEqual(restored.current_index, 1)
        self.assertEqual(restored.position_seconds, 42.5)
        self.assertEqual(restored.volume, 0.35)
        self.assertTrue(restored.is_muted)

    def test_missing_library_tracks_are_not_restored(self):
        self.store.save(
            self.queue,
            position_seconds=12,
            volume=1,
            is_muted=False,
            force_position=True,
        )

        restored = self.store.load([self.tracks[0], self.tracks[2]])

        self.assertEqual([track.id for track in restored.tracks], ["one", "three"])
        self.assertEqual(restored.current_index, -1)

    def test_position_is_saved_periodically_and_queue_changes_immediately(self):
        self.queue.play_at(0)
        with patch("mytunes.core.playback_session.time.monotonic", return_value=10):
            self.store.save(self.queue, 10, 0.8, False)
        with patch("mytunes.core.playback_session.time.monotonic", return_value=12):
            self.store.save(self.queue, 12, 0.8, False)

        saved_value = self.connection.execute(
            "SELECT value FROM settings WHERE key = 'playback_session'"
        ).fetchone()["value"]
        self.assertEqual(json.loads(saved_value)["position_seconds"], 10)

        with patch("mytunes.core.playback_session.time.monotonic", return_value=15):
            self.store.save(self.queue, 15, 0.8, False)
        self.queue.reorder_at(0, 2)
        with patch("mytunes.core.playback_session.time.monotonic", return_value=16):
            self.store.save(self.queue, 15, 0.8, False)

        restored = self.store.load(self.tracks)
        self.assertEqual([track.id for track in restored.tracks], ["two", "three", "one"])
        self.assertEqual(restored.current_index, 2)
        self.assertEqual(restored.position_seconds, 15)

    def test_restore_seek_waits_for_media_duration_and_clamps_position(self):
        engine = AudioEngine.__new__(AudioEngine)
        engine.audio = Mock()
        engine.audio.get_duration.side_effect = [0.0, 75.0]
        engine.total_duration = 100.0
        engine.seek = Mock()
        engine.pause = Mock()
        position_updates = []
        engine.on_position_changed = lambda position, duration: position_updates.append(
            (position, duration)
        )

        asyncio.run(engine._seek_after_restore_load(100.0, 100.0))

        engine.seek.assert_called_once_with(74.9)
        engine.pause.assert_called_once_with()
        self.assertEqual(position_updates, [(74.9, 75.0)])


if __name__ == "__main__":
    unittest.main()
