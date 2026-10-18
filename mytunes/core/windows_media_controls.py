from __future__ import annotations

import logging
import sys
from datetime import timedelta
from typing import Any

from mytunes.core.audio import AudioEngine
from mytunes.core.queue import QueueManager
from mytunes.core.media_artwork import MediaArtworkCache
from mytunes.core.media_control_actions import MediaControlActions
from mytunes.models.track import Track

logger = logging.getLogger(__name__)


class WindowsMediaControls:
    """Bridges the app's VLC playback state to Windows media controls."""

    def __init__(
        self,
        page: Any,
        audio_engine: AudioEngine,
        queue_manager: QueueManager,
    ) -> None:
        self.page = page
        self.audio_engine = audio_engine
        self.queue_manager = queue_manager
        self.actions = MediaControlActions(page, audio_engine, queue_manager)
        self.artwork_cache = MediaArtworkCache()
        self._track_generation = 0
        self._player: Any = None
        self._controls: Any = None
        self._display_updater: Any = None
        self._stream_reference: Any = None
        self._storage_file: Any = None
        self._buttons: Any = None
        self._playback_status: Any = None
        self._playback_type: Any = None
        self._timeline_properties: Any = None
        self._button_pressed_token: Any = None

        if sys.platform != "win32":
            return

        try:
            from winrt.windows.media import (
                MediaPlaybackStatus,
                MediaPlaybackType,
                SystemMediaTransportControlsButton,
                SystemMediaTransportControlsTimelineProperties,
            )
            from winrt.windows.media.playback import MediaPlayer
            from winrt.windows.storage import StorageFile
            from winrt.windows.storage.streams import RandomAccessStreamReference

            self._buttons = SystemMediaTransportControlsButton
            self._playback_status = MediaPlaybackStatus
            self._playback_type = MediaPlaybackType
            self._timeline_properties = SystemMediaTransportControlsTimelineProperties
            self._storage_file = StorageFile
            self._stream_reference = RandomAccessStreamReference
            self._player = MediaPlayer()
            self._controls = self._player.system_media_transport_controls
            self._display_updater = self._controls.display_updater
            self._controls.is_enabled = True
            self._controls.is_play_enabled = True
            self._controls.is_pause_enabled = True
            self._controls.is_stop_enabled = True
            self._controls.is_previous_enabled = True
            self._controls.is_next_enabled = True
            self._controls.playback_status = MediaPlaybackStatus.STOPPED
            self._button_pressed_token = self._controls.add_button_pressed(
                self._on_button_pressed
            )
        except ImportError:
            logger.warning(
                "Windows media controls are unavailable; install the Windows "
                "PyWinRT dependencies from requirements.txt.",
                exc_info=True,
            )
            self.close()
        except Exception:
            logger.exception("Failed to initialize Windows media controls.")
            self.close()

    def update_track(self, track: Track | None) -> None:
        if self._display_updater is None:
            return

        self._track_generation += 1
        generation = self._track_generation
        try:
            if track is None:
                self._display_updater.clear_all()
                self._controls.playback_status = self._playback_status.STOPPED
                self._display_updater.update()
                return

            self._display_updater.clear_all()
            self._display_updater.type = self._playback_type.MUSIC
            properties = self._display_updater.music_properties
            properties.title = track.title
            properties.artist = track.artist
            properties.album_artist = track.album_artist or track.artist
            properties.album_title = track.album
            if track.track_number is not None:
                properties.track_number = track.track_number
            self._display_updater.update()
            self.update_position(0.0, track.duration)
            self.page.run_task(self._update_artwork, generation, track)
        except Exception:
            logger.exception("Failed to update Windows media metadata.")

    async def _update_artwork(self, generation: int, track: Track) -> None:
        artwork_path = await self.artwork_cache.resolve(track)
        if generation != self._track_generation or self._display_updater is None:
            return

        try:
            if artwork_path is None:
                self._display_updater.thumbnail = None
            else:
                storage_file = self._storage_file.get_file_from_path_async(
                    str(artwork_path)
                ).get()
                self._display_updater.thumbnail = (
                    self._stream_reference.create_from_file(storage_file)
                )
            self._display_updater.update()
        except Exception:
            logger.exception("Failed to publish Windows media artwork.")

    def update_playback_state(self, is_playing: bool) -> None:
        if self._controls is None:
            return

        try:
            self._controls.playback_status = (
                self._playback_status.PLAYING
                if is_playing
                else self._playback_status.PAUSED
            )
        except Exception:
            logger.exception("Failed to update Windows media playback state.")

    def update_playback_stopped(self) -> None:
        if self._controls is None:
            return

        try:
            self._controls.playback_status = self._playback_status.STOPPED
        except Exception:
            logger.exception("Failed to update Windows media playback state.")

    def update_position(self, current_seconds: float, total_seconds: float) -> None:
        if self._controls is None or total_seconds <= 0:
            return

        try:
            duration = max(0.0, total_seconds)
            position = min(max(0.0, current_seconds), duration)
            timeline = self._timeline_properties()
            timeline.start_time = timedelta(0)
            timeline.end_time = timedelta(seconds=duration)
            timeline.min_seek_time = timedelta(0)
            timeline.max_seek_time = timedelta(seconds=duration)
            timeline.position = timedelta(seconds=position)
            self._controls.update_timeline_properties(timeline)
        except Exception:
            logger.exception("Failed to update Windows media timeline.")

    def update_volume(self, _volume: float) -> None:
        return

    def _on_button_pressed(self, _sender: Any, args: Any) -> None:
        button = args.button
        if button == self._buttons.PLAY:
            self.actions.dispatch("play")
        elif button == self._buttons.PAUSE:
            self.actions.dispatch("pause")
        elif button == self._buttons.STOP:
            self.actions.dispatch("stop")
        elif button == self._buttons.NEXT:
            self.actions.dispatch("next")
        elif button == self._buttons.PREVIOUS:
            self.actions.dispatch("previous")

    def close(self) -> None:
        if self._controls is not None and self._button_pressed_token is not None:
            try:
                self._controls.remove_button_pressed(self._button_pressed_token)
            except Exception:
                logger.exception("Failed to unregister Windows media button handler.")
            self._button_pressed_token = None

        if self._player is not None:
            try:
                self._player.close()
            except Exception:
                logger.exception("Failed to close the Windows media player.")
            self._player = None
            self._controls = None
            self._display_updater = None
