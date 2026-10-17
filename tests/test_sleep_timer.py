import unittest
from unittest.mock import MagicMock
from mytunes.core.audio import SleepTimerState, AudioEngine
from mytunes.core.queue import QueueManager
from mytunes.models.track import Track

class TestSleepTimer(unittest.TestCase):

    def test_sleep_timer_state_finish_song(self):
        state = SleepTimerState()
        self.assertFalse(state.is_active)
        self.assertFalse(state.finish_current_song)
        self.assertFalse(state.pending_finish)

        # Set finish_current_song mode
        state.is_active = True
        state.finish_current_song = True
        state.remaining_seconds = 0
        state.pending_finish = True

        self.assertTrue(state.pending_finish)

    def test_handle_track_finished_stops_when_pending_finish(self):
        qm = QueueManager()
        track1 = Track(id="1", title="Track 1", file_path="C:/1.mp3")
        track2 = Track(id="2", title="Track 2", file_path="C:/2.mp3")
        qm.set_queue([track1, track2], 0)

        # Mock page and audio engine
        mock_page = MagicMock()
        mock_page.overlay = []
        engine = AudioEngine(mock_page, qm)
        engine.audio = MagicMock()

        # Set sleep timer in 'pending_finish' state
        engine.sleep_state.is_active = True
        engine.sleep_state.finish_current_song = True
        engine.sleep_state.pending_finish = True

        sleep_triggered = []
        engine.on_sleep_triggered = lambda: sleep_triggered.append(True)

        # Track finishes
        engine._handle_track_finished()

        # Audio should be stopped, not advancing to track 2!
        self.assertFalse(engine.is_playing)
        self.assertFalse(engine.sleep_state.is_active)
        self.assertEqual(len(sleep_triggered), 1)
        # Queue should not have advanced to track 2
        self.assertEqual(qm.current_track.id, "1")

if __name__ == "__main__":
    unittest.main()
