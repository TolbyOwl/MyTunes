import asyncio
import threading
import unittest
from unittest.mock import MagicMock, Mock
from unittest.mock import AsyncMock, patch
from mytunes.core.audio import (
    POSITION_POLL_INTERVAL_SECONDS,
    SleepTimerState,
    AudioEngine,
)
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

    def test_vlc_track_finished_dispatches_queue_advance_to_page_loop(self):
        qm = QueueManager()
        track1 = Track(id="1", title="Track 1", file_path="C:/1.mp3")
        track2 = Track(id="2", title="Track 2", file_path="C:/2.mp3")
        qm.set_queue([track1, track2], 0)

        mock_page = MagicMock()
        engine = AudioEngine(mock_page, qm)
        engine.play_track = Mock()

        engine._on_vlc_track_finished(None)

        mock_page.run_task.assert_called_once_with(engine._handle_track_finished_on_page)
        asyncio.run(mock_page.run_task.call_args.args[0]())
        engine.play_track.assert_called_once_with(track2)
        self.assertEqual(qm.current_track, track2)

    def test_position_poll_is_scheduled_on_the_page_event_loop(self):
        page = MagicMock()
        engine = AudioEngine(page, QueueManager())

        async def schedule_poll():
            engine._start_poll()

        asyncio.run(schedule_poll())

        page.run_task.assert_called_once_with(engine._poll_position)
        page.run_task.return_value.cancel.assert_not_called()

    def test_play_track_updates_playback_state_without_full_page_refresh(self):
        page = MagicMock()
        queue = QueueManager()
        engine = AudioEngine(page, queue)
        engine.audio = MagicMock()
        state_changed = Mock()
        engine.on_state_changed = state_changed

        engine.play_track(Track(id="track", title="Song", file_path="song.mp3"))

        state_changed.assert_called_once_with(True)
        page.run_task.assert_called_once_with(
            engine._start_audio,
            engine._playback_generation,
            "song.mp3",
            False,
        )
        page.update.assert_not_called()

    def test_restored_track_is_loaded_paused_before_seeking(self):
        page = MagicMock()
        engine = AudioEngine(page, QueueManager())
        engine.audio = MagicMock()
        track = Track(id="track", title="Song", file_path="song.mp3")

        engine.restore_paused_track(track, 12.0)

        self.assertFalse(engine.is_playing)
        page.run_task.assert_any_call(
            engine._start_audio,
            engine._playback_generation,
            "song.mp3",
            True,
        )
        engine.audio.pause.assert_not_called()

    def test_audio_start_runs_in_worker_before_position_polling(self):
        engine = AudioEngine(MagicMock(), QueueManager())
        engine.audio = MagicMock()
        engine.is_playing = True
        engine._playback_generation = 1
        engine._start_poll = Mock()

        asyncio.run(engine._start_audio(1, "song.mp3"))

        engine.audio.play.assert_called_once_with()
        engine._start_poll.assert_called_once_with()

    def test_audio_start_failure_stops_playback_and_notifies_user(self):
        engine = AudioEngine(MagicMock(), QueueManager())
        engine.audio = MagicMock()
        engine.audio.play.side_effect = RuntimeError("VLC startup failed")
        engine.is_playing = True
        engine._playback_generation = 1
        engine._stop_poll = Mock()
        engine._start_poll = Mock()
        state_changed = Mock()
        playback_error = Mock()
        engine.on_state_changed = state_changed
        engine.on_playback_error = playback_error

        with self.assertLogs("mytunes.core.audio", level="ERROR"):
            asyncio.run(engine._start_audio(1, "song.mp3"))

        self.assertFalse(engine.is_playing)
        engine._stop_poll.assert_called_once_with()
        engine._start_poll.assert_not_called()
        state_changed.assert_called_once_with(False)
        playback_error.assert_called_once()

    def test_position_poll_is_half_second_and_reads_vlc_off_event_loop(self):
        engine = AudioEngine(MagicMock(), QueueManager())
        engine.audio = MagicMock()
        engine.audio.get_duration.return_value = 180.0
        engine.is_playing = True
        owner_thread = threading.get_ident()
        reader_threads = []
        position_values = iter([1.2, 1.8, 2.1])

        def read_position():
            reader_threads.append(threading.get_ident())
            return next(position_values)

        engine.audio.get_position.side_effect = read_position
        position_updates = []

        def on_position_changed(position, duration):
            position_updates.append((position, duration))
            if position >= 2:
                engine.is_playing = False

        engine.on_position_changed = on_position_changed
        with patch(
            "mytunes.core.audio.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep:
            asyncio.run(engine._poll_position())

        self.assertEqual(POSITION_POLL_INTERVAL_SECONDS, 0.5)
        self.assertEqual(
            position_updates,
            [(1.2, 180.0), (2.1, 180.0)],
        )
        self.assertEqual(sleep.await_args_list[0].args, (0.5,))
        self.assertTrue(all(thread_id != owner_thread for thread_id in reader_threads))

if __name__ == "__main__":
    unittest.main()
