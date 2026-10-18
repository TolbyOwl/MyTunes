from __future__ import annotations

import logging
from typing import Any, Literal

from mytunes.core.audio import AudioEngine
from mytunes.core.queue import QueueManager

logger = logging.getLogger(__name__)
MediaAction = Literal["play", "pause", "play_pause", "stop", "next", "previous"]


class MediaControlActions:
    """Dispatches native media-control actions through the existing player."""

    def __init__(
        self,
        page: Any,
        audio_engine: AudioEngine,
        queue_manager: QueueManager,
    ) -> None:
        self.page = page
        self.audio_engine = audio_engine
        self.queue_manager = queue_manager

    def dispatch(self, action: MediaAction) -> None:
        try:
            self.page.run_task(self._handle, action)
        except Exception:
            logger.exception("Failed to dispatch media action %s.", action)

    def seek(self, position_seconds: float) -> None:
        try:
            self.page.run_task(self._seek, position_seconds)
        except Exception:
            logger.exception("Failed to dispatch media seek.")

    async def _handle(self, action: MediaAction) -> None:
        if action == "play":
            if not self.audio_engine.is_playing:
                self.audio_engine.toggle_play_pause()
        elif action == "pause":
            if self.audio_engine.is_playing:
                self.audio_engine.pause()
        elif action == "play_pause":
            self.audio_engine.toggle_play_pause()
        elif action == "stop":
            self.audio_engine.stop()
        elif action in ("next", "previous"):
            track = (
                self.queue_manager.next_track()
                if action == "next"
                else self.queue_manager.prev_track()
            )
            if track is not None:
                self.audio_engine.play_track(track)

    async def _seek(self, position_seconds: float) -> None:
        self.audio_engine.seek(position_seconds)
