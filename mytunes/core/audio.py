from __future__ import annotations
import asyncio
from concurrent.futures import Future
import inspect
import logging
import threading
import time
from typing import Optional, Callable, Dict, Any
try:
    import flet as ft
except ImportError:
    # Minimal stub for testing environments without flet installed.
    class _DummyIcons:
        PLAY_ARROW = "play_arrow"
        QUEUE_MUSIC = "queue_music"
        FAVORITE_BORDER = "favorite_border"
        MORE_VERT = "more_vert"
        # Add any other icons referenced elsewhere as needed.
        
    class _DummyColors:
        GREY_400 = "#B0B0B0"
        GREY_500 = "#9E9E9E"
        RED_400 = "#EF5350"
        
    class _DummyFT:
        Icons = _DummyIcons()
        Colors = _DummyColors()
        # Define placeholder classes used in type hints if necessary.
        class Page: pass
        class Service: pass
        class Audio:
            def __init__(self, **kwargs):
                # Store provided kwargs for potential inspection.
                for k, v in kwargs.items():
                    setattr(self, k, v)
                # Ensure src attribute exists.
                self.src = kwargs.get('src')
            def play(self, *args, **kwargs):
                pass
            def resume(self, *args, **kwargs):
                pass
            def pause(self, *args, **kwargs):
                pass
            def seek(self, *args, **kwargs):
                pass
        class Image: pass
        class IconButton: pass
        class Icon: pass
        class Slider: pass
        class Text: pass
        class Container: pass
        class Row: pass
        class Column: pass
        class ProgressRing: pass
        class TextField: pass
        class FilledButton: pass
        class OutlinedButton: pass
        class AlertDialog: pass
        class TextButton: pass
        class Chip: pass
        class GridView: pass
        class Border: pass
        class BorderSide: pass
        class Padding: pass
        class Alignment: CENTER = None
        class CrossAxisAlignment: CENTER = None
        class MainAxisAlignment: CENTER = None
        class ScrollMode: AUTO = None
        class BoxFit: COVER = None
        class FontWeight:
            BOLD = None
            W_500 = None
        # Stub for FilePicker control
        class FilePicker:
            def __init__(self, on_result=None):
                self.on_result = on_result
            async def get_directory_path(self, *args, **kwargs):
                return None
    ft = _DummyFT()


# Force VLC as the audio backend (skip flet_audio which causes timeouts)
try:
    import vlc  # pip install python-vlc
except Exception as e:
    raise RuntimeError("VLC is required for audio playback. Install python-vlc.") from e

class _VLCPlayer:
    """Minimal VLC wrapper exposing the methods used by AudioEngine."""

    def __init__(self, **kwargs):
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()
        self.src = None
        self._volume: float = kwargs.get("volume", 1.0)
        self._playback_rate: float = kwargs.get("playback_rate", 1.0)

    # --- volume property: writing it immediately applies to VLC ---
    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, value))
        try:
            self.player.audio_set_volume(int(self._volume * 100))
        except Exception:
            pass

    # --- playback_rate property: writing it immediately applies to VLC ---
    @property
    def playback_rate(self) -> float:
        return self._playback_rate

    @playback_rate.setter
    def playback_rate(self, value: float) -> None:
        self._playback_rate = max(0.25, min(4.0, value))
        try:
            self.player.set_rate(self._playback_rate)
        except Exception:
            pass

    def play(self) -> None:
        if not self.src:
            return
        media = self.instance.media_new(self.src)
        self.player.set_media(media)
        self.player.audio_set_volume(int(self._volume * 100))
        self.player.set_rate(self._playback_rate)
        if self.player.play() == -1:
            raise RuntimeError("VLC could not start the selected media.")

    def pause(self) -> None:
        """Pause without losing position."""
        self.player.set_pause(1)

    def resume(self) -> None:
        """Resume from where we paused — does NOT restart the track."""
        self.player.set_pause(0)

    def stop(self) -> None:
        self.player.stop()

    def seek(self, ms: int) -> None:
        """Seek to position in milliseconds."""
        try:
            self.player.set_time(int(ms))
        except Exception:
            pass

    def get_position(self) -> float:
        """Return current playback position in seconds (0.0 if nothing loaded)."""
        try:
            ms = self.player.get_time()
            return max(0.0, ms / 1000.0) if ms >= 0 else 0.0
        except Exception:
            return 0.0

    def get_duration(self) -> float:
        """Return total track duration in seconds (0.0 if unknown)."""
        try:
            ms = self.player.get_length()
            return max(0.0, ms / 1000.0) if ms > 0 else 0.0
        except Exception:
            return 0.0

AudioControl = _VLCPlayer

from mytunes.models.track import Track
from mytunes.core.queue import QueueManager, RepeatMode

logger = logging.getLogger(__name__)
POSITION_POLL_INTERVAL_SECONDS = 0.5

class SleepTimerState:
    """Tracks sleep timer countdown and finish-song state."""
    def __init__(self):
        self.is_active: bool = False
        self.duration_seconds: int = 0
        self.remaining_seconds: int = 0
        self.finish_current_song: bool = False
        self.pending_finish: bool = False
        self._task: Optional[asyncio.Task] = None

class AudioEngine:
    """
    Coordinates audio playback, Flet Audio control, volume,
    playback speed, sleep timer with finish-last-song, and track events.
    """

    def __init__(self, page: ft.Page, queue_manager: QueueManager):
        self.app_page = page
        self.queue = queue_manager
        self.audio: Optional[Any] = None
        self.is_playing: bool = False
        self.volume: float = 1.0
        self.is_muted: bool = False
        self.playback_rate: float = 1.0
        self.current_position: float = 0.0
        self.total_duration: float = 0.0

        # Task that polls VLC position every second to drive the progress bar
        self._poll_task: Optional[Future[None]] = None
        self._playback_generation = 0
        self._audio_start_lock = threading.Lock()
        self._current_source_url: Optional[str] = None

        # Sleep timer
        self.sleep_state = SleepTimerState()

        # Callbacks for UI updates
        self.on_state_changed: Optional[Callable[[bool], None]] = None
        self.on_stopped: Optional[Callable[[], None]] = None
        self.on_volume_changed: Optional[Callable[[float], None]] = None
        self.on_position_changed: Optional[Callable[[float, float], None]] = None
        self.on_playback_error: Optional[Callable[[str], None]] = None
        self.on_seeked: Optional[Callable[[float], None]] = None
        self.on_sleep_tick: Optional[Callable[[int, bool], None]] = None
        self.on_sleep_triggered: Optional[Callable[[], None]] = None

        self._init_audio_control()

    def _init_audio_control(self) -> None:
        """Initializes the Flet Audio control without a source.
        The audio control must have a valid `src` before playback; creating it with an empty
        source raises a Dart exception and aborts the session. We therefore defer setting
        `src` until a track is actually played.
        """
        if AudioControl is None:
            return
        # Determine if AudioControl is the VLC wrapper (has a 'player' attribute when instantiated)
        if hasattr(AudioControl, '__call__') and AudioControl.__name__ == '_VLCPlayer':
            # VLC wrapper expects no arguments; instantiate directly
            self.audio = AudioControl()
            # Attach end‑of‑track event if VLC is available
            if vlc is not None and hasattr(self.audio, 'player'):
                try:
                    ev = self.audio.player.event_manager()
                    ev.event_attach(vlc.EventType.MediaPlayerEndReached,
                                    self._on_vlc_track_finished)
                except Exception:
                    pass
        else:
            # Assume Flet Audio control with the standard signature
            self.audio = AudioControl(
                src=None,
                autoplay=False,
                volume=self.volume,
                playback_rate=self.playback_rate,
                on_loaded=self._on_loaded,
                on_duration_change=self._on_duration_change,
                on_position_change=self._on_position_change,
                on_state_change=self._on_audio_state_change,
            )

    def _run_async(self, coro_fn, *args) -> None:
        """Schedules an async coroutine on Flet's page event loop."""
        try:
            if hasattr(self.app_page, "run_task") and callable(self.app_page.run_task):
                self.app_page.run_task(coro_fn, *args)
            elif inspect.iscoroutinefunction(coro_fn):
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(coro_fn(*args))
                else:
                    loop.run_until_complete(coro_fn(*args))
            elif callable(coro_fn):
                coro_fn(*args)
        except Exception:
            pass

    def _on_loaded(self, e=None) -> None:
        pass

    def _on_duration_change(self, e) -> None:
        try:
            dur = getattr(e, "duration", None)
            if dur is not None:
                if hasattr(dur, "total_seconds"):
                    self.total_duration = dur.total_seconds()
                elif hasattr(dur, "milliseconds"):
                    self.total_duration = dur.milliseconds / 1000.0
                elif isinstance(dur, (int, float)):
                    self.total_duration = float(dur) / 1000.0
        except Exception:
            pass

    def _on_position_change(self, e) -> None:
        try:
            pos = getattr(e, "position", None)
            if pos is not None:
                if hasattr(pos, "total_seconds"):
                    self.current_position = pos.total_seconds()
                elif hasattr(pos, "milliseconds"):
                    self.current_position = pos.milliseconds / 1000.0
                elif isinstance(pos, (int, float)):
                    self.current_position = float(pos) / 1000.0

                if self.on_position_changed:
                    self.on_position_changed(self.current_position, self.total_duration)
        except Exception:
            pass

    def _on_audio_state_change(self, e) -> None:
        state = getattr(e, "state", None)
        state_str = str(state.value if hasattr(state, "value") else state).lower()

        if "completed" in state_str:
            self._handle_track_finished()
        elif "playing" in state_str:
            self.is_playing = True
            if self.on_state_changed:
                self.on_state_changed(True)
        elif "paused" in state_str:
            self.is_playing = False
            if self.on_state_changed:
                self.on_state_changed(False)
        elif "stopped" in state_str:
            self._notify_stopped()

    def _notify_stopped(self) -> None:
        self.is_playing = False
        if self.on_state_changed:
            self.on_state_changed(False)
        if self.on_stopped:
            self.on_stopped()

    def _on_vlc_track_finished(self, _event: Any) -> None:
        """Dispatch VLC's native-thread callback to the page event loop."""
        self.app_page.run_task(self._handle_track_finished_on_page)

    async def _handle_track_finished_on_page(self) -> None:
        self._handle_track_finished()

    def _on_seek_complete(self, e=None) -> None:
        pass

    def _handle_track_finished(self) -> None:
        """Called when audio reaches end of track."""
        # Check if sleep timer is waiting for track to finish
        if self.sleep_state.pending_finish or (self.sleep_state.is_active and self.sleep_state.finish_current_song and self.sleep_state.remaining_seconds <= 0):
            self.stop()
            self.cancel_sleep_timer()
            if self.on_sleep_triggered:
                self.on_sleep_triggered()
            return

        # Advance to next song in queue
        next_track = self.queue.next_track()
        if next_track:
            self.play_track(next_track)
        else:
            self._notify_stopped()

    def play_track(
        self,
        track: Track,
        *,
        count_play: bool = True,
        start_paused: bool = False,
    ) -> None:
        """Loads and plays a track."""
        if not self.audio:
            return

        source_url = track.file_path
        # VLC requires a proper file:// URI for local paths.
        # A raw Windows path like D:\Music\song.mp3 can fail with spaces/Unicode.
        if track.source == "local" and source_url:
            import pathlib
            try:
                source_url = pathlib.Path(source_url).as_uri()
            except Exception:
                pass  # keep original path as fallback

        self._playback_generation += 1
        generation = self._playback_generation
        self._current_source_url = source_url
        self.current_position = 0.0
        self.total_duration = track.duration
        self.is_playing = not start_paused

        try:
            self.app_page.run_task(
                self._start_audio,
                generation,
                source_url,
                start_paused,
            )
        except Exception:
            logger.exception("Could not schedule playback for %r", source_url)
            self.is_playing = False
            self._current_source_url = None
            if self.on_state_changed:
                self.on_state_changed(False)
            if self.on_playback_error:
                self.on_playback_error(
                    "Could not start playback. Check the file and VLC installation."
                )
            return

        if count_play:
            track.play_count += 1
            track.last_played = time.time()

        if self.on_position_changed:
            self.on_position_changed(self.current_position, self.total_duration)
        if self.on_state_changed:
            self.on_state_changed(True)

    def _play_audio_in_worker(
        self,
        generation: int,
        source_url: str,
        start_paused: bool,
    ) -> None:
        with self._audio_start_lock:
            if generation != self._playback_generation or (
                not self.is_playing and not start_paused
            ):
                return
            audio = self.audio
            if not audio:
                return
            audio.src = source_url
            audio.playback_rate = self.playback_rate
            audio.volume = 0.0 if self.is_muted else self.volume
            audio.play()
            if start_paused or (
                generation == self._playback_generation and not self.is_playing
            ):
                audio.pause()

    async def _start_audio(
        self,
        generation: int,
        source_url: str,
        start_paused: bool = False,
    ) -> None:
        try:
            await asyncio.to_thread(
                self._play_audio_in_worker,
                generation,
                source_url,
                start_paused,
            )
        except Exception:
            if generation != self._playback_generation:
                return
            logger.exception("Could not start playback for %r", source_url)
            self.is_playing = False
            self._current_source_url = None
            self._stop_poll()
            if self.on_state_changed:
                self.on_state_changed(False)
            if self.on_playback_error:
                self.on_playback_error(
                    "Could not start playback. Check the file and VLC installation."
                )
            return

        if (
            generation == self._playback_generation
            and self.is_playing
            and not start_paused
        ):
            self._start_poll()

    def restore_paused_track(self, track: Track, position_seconds: float) -> None:
        """Loads a saved track, leaves it paused, and seeks once VLC has media metadata."""
        if not self.audio:
            return

        self.play_track(track, count_play=False, start_paused=True)
        self.current_position = max(0.0, position_seconds)
        self._run_async(self._seek_after_restore_load, self.current_position, track.duration)

    async def _seek_after_restore_load(
        self,
        position_seconds: float,
        fallback_duration: float,
    ) -> None:
        for _ in range(50):
            if not self.audio:
                return
            has_duration_api = hasattr(self.audio, "get_duration")
            duration = (
                self.audio.get_duration()
                if has_duration_api
                else self.total_duration or fallback_duration
            )
            if duration > 0:
                target = min(position_seconds, max(0.0, duration - 0.1))
                self.seek(target)
                self.pause()
                if self.on_position_changed:
                    self.on_position_changed(target, duration)
                return
            await asyncio.sleep(0.1)

        logger.warning("Could not seek to the saved position because track duration did not load.")

    # --- Position polling (drives progress bar for VLC backend) ---

    def _start_poll(self) -> None:
        """Start the position-polling loop if it isn't already running."""
        self._stop_poll()
        self._poll_task = self.app_page.run_task(self._poll_position)

    def _stop_poll(self) -> None:
        """Cancel any active polling task."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        self._poll_task = None

    async def _poll_position(self) -> None:
        """Poll VLC without blocking the page loop; publish only visible changes."""
        try:
            while self.is_playing:
                generation = self._playback_generation
                await asyncio.sleep(POSITION_POLL_INTERVAL_SECONDS)
                if not self.audio or not self.is_playing:
                    break
                if generation != self._playback_generation:
                    continue

                pos, dur = await asyncio.to_thread(self._read_audio_position)
                if generation != self._playback_generation or not self.is_playing:
                    continue

                previous_position = self.current_position
                previous_duration = self.total_duration
                self.current_position = pos
                if dur > 0:
                    self.total_duration = dur

                if self.on_position_changed and (
                    int(pos) != int(previous_position)
                    or self.total_duration != previous_duration
                ):
                    self.on_position_changed(self.current_position, self.total_duration)
        except asyncio.CancelledError:
            pass

    def _read_audio_position(self) -> tuple[float, float]:
        if not self.audio:
            return self.current_position, self.total_duration

        position = (
            self.audio.get_position()
            if hasattr(self.audio, "get_position")
            else self.current_position
        )
        duration = (
            self.audio.get_duration()
            if hasattr(self.audio, "get_duration")
            else self.total_duration
        )
        return position, duration

    def toggle_play_pause(self) -> None:
        if not self.audio:
            return

        if self.is_playing:
            self.pause()
        else:
            if not self._current_source_url and self.queue.current_track:
                self.play_track(self.queue.current_track)
            else:
                self.resume()

    def resume(self) -> None:
        if self.audio:
            self.audio.resume()
            self.is_playing = True
            self._start_poll()
            if self.on_state_changed:
                self.on_state_changed(True)

    def pause(self) -> None:
        if self.audio:
            self.audio.pause()
            self.is_playing = False
            self._stop_poll()
            if self.on_state_changed:
                self.on_state_changed(False)

    def stop(self) -> None:
        if self.audio:
            self.audio.stop()
            self.is_playing = False
            self._stop_poll()
            self.current_position = 0.0
            self._notify_stopped()

    def seek(self, position_seconds: float) -> None:
        if self.audio:
            self.audio.seek(int(position_seconds * 1000))
            self.current_position = position_seconds
            if self.on_seeked:
                self.on_seeked(position_seconds)

    def set_volume(self, vol: float) -> None:
        self.volume = max(0.0, min(1.0, vol))
        if self.audio and not self.is_muted:
            self.audio.volume = self.volume
        if self.on_volume_changed:
            self.on_volume_changed(0.0 if self.is_muted else self.volume)

    def toggle_mute(self) -> None:
        self.is_muted = not self.is_muted
        if self.audio:
            self.audio.volume = 0.0 if self.is_muted else self.volume
        if self.on_volume_changed:
            self.on_volume_changed(0.0 if self.is_muted else self.volume)

    def set_playback_rate(self, rate: float) -> None:
        self.playback_rate = max(0.5, min(2.5, rate))
        if self.audio:
            self.audio.playback_rate = self.playback_rate

    # --- Sleep Timer with 'Finish Current Song' ---

    def start_sleep_timer(self, minutes: int, finish_current_song: bool = False) -> None:
        """Starts a sleep timer with optional finish-current-song behavior."""
        self.cancel_sleep_timer()

        self.sleep_state.is_active = True
        self.sleep_state.duration_seconds = minutes * 60
        self.sleep_state.remaining_seconds = minutes * 60
        self.sleep_state.finish_current_song = finish_current_song
        self.sleep_state.pending_finish = False

        self.sleep_state._task = asyncio.create_task(self._sleep_countdown())

    def cancel_sleep_timer(self) -> None:
        if self.sleep_state._task and not self.sleep_state._task.done():
            self.sleep_state._task.cancel()
        self.sleep_state.is_active = False
        self.sleep_state.pending_finish = False
        self.sleep_state.remaining_seconds = 0
        if self.on_sleep_tick:
            self.on_sleep_tick(0, False)

    async def _sleep_countdown(self) -> None:
        try:
            while self.sleep_state.remaining_seconds > 0:
                await asyncio.sleep(1)
                self.sleep_state.remaining_seconds -= 1
                if self.on_sleep_tick:
                    self.on_sleep_tick(
                        self.sleep_state.remaining_seconds,
                        self.sleep_state.finish_current_song
                    )

            # Timer reached zero
            if self.sleep_state.finish_current_song:
                # Keep playing until track finishes
                self.sleep_state.pending_finish = True
                if self.on_sleep_tick:
                    self.on_sleep_tick(0, True)
            else:
                # Stop immediately
                self.stop()
                self.cancel_sleep_timer()
                if self.on_sleep_triggered:
                    self.on_sleep_triggered()

        except asyncio.CancelledError:
            pass
