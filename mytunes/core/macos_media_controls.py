from __future__ import annotations

import logging
import sys
from typing import Any

from mytunes.core.audio import AudioEngine
from mytunes.core.media_artwork import MediaArtworkCache
from mytunes.core.media_control_actions import MediaAction, MediaControlActions
from mytunes.core.queue import QueueManager
from mytunes.models.track import Track

logger = logging.getLogger(__name__)


class MacOSMediaControls:
    """Publishes Now Playing metadata and handles macOS remote commands."""

    def __init__(
        self,
        page: Any,
        audio_engine: AudioEngine,
        queue_manager: QueueManager,
    ) -> None:
        self.page = page
        self.actions = MediaControlActions(page, audio_engine, queue_manager)
        self.artwork_cache = MediaArtworkCache()
        self._track_generation = 0
        self._now_playing_center: Any = None
        self._remote_commands: Any = None
        self._command_targets: list[tuple[Any, Any]] = []
        self._appkit: Any = None
        self._media_player: Any = None

        if sys.platform != "darwin":
            return

        try:
            import AppKit
            import MediaPlayer

            self._appkit = AppKit
            self._media_player = MediaPlayer
            self._now_playing_center = MediaPlayer.MPNowPlayingInfoCenter.defaultCenter()
            self._remote_commands = MediaPlayer.MPRemoteCommandCenter.sharedCommandCenter()
            self._now_playing_center.setNowPlayingInfo_(None)
            for command_name, action in (
                ("playCommand", "play"),
                ("pauseCommand", "pause"),
                ("togglePlayPauseCommand", "play_pause"),
                ("stopCommand", "stop"),
                ("nextTrackCommand", "next"),
                ("previousTrackCommand", "previous"),
            ):
                command = getattr(self._remote_commands, command_name)
                target = command.addTargetWithHandler_(
                    self._make_command_handler(action)
                )
                self._command_targets.append((command, target))
                command.setEnabled_(True)
        except ImportError:
            logger.warning(
                "macOS media controls are unavailable; install the macOS "
                "PyObjC dependencies from requirements.txt.",
                exc_info=True,
            )
            self.close()
        except Exception:
            logger.exception("Failed to initialize macOS media controls.")
            self.close()

    def _make_command_handler(self, action: MediaAction):
        def handle(_event: Any) -> Any:
            self.actions.dispatch(action)
            return self._media_player.MPRemoteCommandHandlerStatusSuccess

        return handle

    def update_track(self, track: Track | None) -> None:
        if self._now_playing_center is None:
            return

        self._track_generation += 1
        generation = self._track_generation
        if track is None:
            self._now_playing_center.setNowPlayingInfo_(None)
            return

        info = {
            self._media_player.MPMediaItemPropertyTitle: track.title,
            self._media_player.MPMediaItemPropertyArtist: track.artist,
            self._media_player.MPMediaItemPropertyAlbumTitle: track.album,
            self._media_player.MPMediaItemPropertyPlaybackDuration: track.duration,
            self._media_player.MPMediaItemPropertyElapsedPlaybackTime: 0.0,
            self._media_player.MPMediaItemPropertyPlaybackRate: 1.0,
        }
        if track.track_number is not None:
            info[self._media_player.MPMediaItemPropertyAlbumTrackNumber] = (
                track.track_number
            )
        if track.album_artist:
            info[self._media_player.MPMediaItemPropertyAlbumArtist] = track.album_artist

        self._now_playing_center.setNowPlayingInfo_(info)
        self.page.run_task(self._update_artwork, generation, track)

    async def _update_artwork(self, generation: int, track: Track) -> None:
        artwork_path = await self.artwork_cache.resolve(track)
        if generation != self._track_generation or self._now_playing_center is None:
            return
        if artwork_path is None:
            return

        try:
            image = self._appkit.NSImage.alloc().initWithContentsOfFile_(
                str(artwork_path)
            )
            if image is None:
                logger.warning(
                    "Could not load artwork image for track %s.", track.id
                )
                return
            size = self._appkit.NSMakeSize(600, 600)
            artwork = (
                self._media_player.MPMediaItemArtwork.alloc()
                .initWithBoundsSize_requestHandler_(size, lambda _size: image)
            )
            info = dict(self._now_playing_center.nowPlayingInfo() or {})
            info[self._media_player.MPMediaItemPropertyArtwork] = artwork
            self._now_playing_center.setNowPlayingInfo_(info)
        except Exception:
            logger.exception("Failed to publish macOS media artwork.")

    def update_playback_state(self, is_playing: bool) -> None:
        if self._media_player is None:
            return
        self._update_info_value(
            self._media_player.MPMediaItemPropertyPlaybackRate,
            1.0 if is_playing else 0.0,
        )

    def update_playback_stopped(self) -> None:
        if self._now_playing_center is not None:
            self._now_playing_center.setNowPlayingInfo_(None)

    def update_position(self, current_seconds: float, _total_seconds: float) -> None:
        if self._media_player is None:
            return
        self._update_info_value(
            self._media_player.MPMediaItemPropertyElapsedPlaybackTime,
            max(0.0, current_seconds),
        )

    def update_volume(self, _volume: float) -> None:
        return

    def _update_info_value(self, key: Any, value: Any) -> None:
        if self._now_playing_center is None:
            return

        try:
            info = dict(self._now_playing_center.nowPlayingInfo() or {})
            if info:
                info[key] = value
                self._now_playing_center.setNowPlayingInfo_(info)
        except Exception:
            logger.exception("Failed to update macOS Now Playing metadata.")

    def close(self) -> None:
        for command, target in self._command_targets:
            try:
                command.removeTarget_(target)
            except Exception:
                logger.exception("Failed to unregister a macOS media command.")
        self._command_targets.clear()
        if self._now_playing_center is not None:
            try:
                self._now_playing_center.setNowPlayingInfo_(None)
            except Exception:
                logger.exception("Failed to clear macOS Now Playing metadata.")
            self._now_playing_center = None
