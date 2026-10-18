from __future__ import annotations

import logging
import sys
from typing import Any, Protocol

from mytunes.core.audio import AudioEngine
from mytunes.core.queue import QueueManager
from mytunes.models.track import Track

logger = logging.getLogger(__name__)


class MediaControls(Protocol):
    def update_track(self, track: Track | None) -> None: ...

    def update_playback_state(self, is_playing: bool) -> None: ...

    def update_playback_stopped(self) -> None: ...

    def update_position(self, current_seconds: float, total_seconds: float) -> None: ...

    def update_volume(self, _volume: float) -> None: ...

    def close(self) -> None: ...


def create_media_controls(
    page: Any,
    audio_engine: AudioEngine,
    queue_manager: QueueManager,
) -> MediaControls:
    """Creates the native media-control adapter for the current platform."""
    if sys.platform == "win32":
        from mytunes.core.windows_media_controls import WindowsMediaControls

        return WindowsMediaControls(page, audio_engine, queue_manager)
    if sys.platform == "darwin":
        from mytunes.core.macos_media_controls import MacOSMediaControls

        return MacOSMediaControls(page, audio_engine, queue_manager)
    if sys.platform.startswith("linux"):
        try:
            from mytunes.core.linux_media_controls import LinuxMprisControls
        except ImportError:
            logger.exception(
                "Linux media controls need dbus-next; install project "
                "dependencies from requirements.txt."
            )
            return _UnsupportedMediaControls()

        return LinuxMprisControls(page, audio_engine, queue_manager)
    return _UnsupportedMediaControls()


class _UnsupportedMediaControls:
    """No-op adapter for platforms without a native integration."""

    def update_track(self, _track: Track | None) -> None:
        return

    def update_playback_state(self, _is_playing: bool) -> None:
        return

    def update_playback_stopped(self) -> None:
        return

    def update_position(self, current_seconds: float, total_seconds: float) -> None:
        return

    def update_volume(self, _volume: float) -> None:
        return

    def close(self) -> None:
        return
