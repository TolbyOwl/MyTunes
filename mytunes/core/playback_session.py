from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from dataclasses import dataclass

from mytunes.core.queue import QueueManager
from mytunes.models.track import Track

logger = logging.getLogger(__name__)
_SESSION_SETTING_KEY = "playback_session"
_POSITION_SAVE_INTERVAL_SECONDS = 5.0


@dataclass(frozen=True)
class SavedPlaybackSession:
    tracks: list[Track]
    current_index: int
    position_seconds: float
    volume: float
    is_muted: bool


class PlaybackSessionStore:
    """Persists the queue and playback position in the existing settings table."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self._last_position_saved_at = 0.0
        self._last_saved_position = 0.0
        self._last_current_track_id: str | None = None
        self._last_saved_payload: dict[str, object] | None = None

    def load(self, library_tracks: list[Track]) -> SavedPlaybackSession | None:
        row = self.connection.execute(
            "SELECT value FROM settings WHERE key = ?",
            (_SESSION_SETTING_KEY,),
        ).fetchone()
        if row is None:
            return None

        try:
            payload = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            logger.warning("Saved playback session is invalid JSON; ignoring it.")
            return None
        if not isinstance(payload, dict):
            logger.warning("Saved playback session has an invalid shape; ignoring it.")
            return None

        track_ids = payload.get("track_ids")
        if not isinstance(track_ids, list) or not all(
            isinstance(track_id, str) for track_id in track_ids
        ):
            logger.warning("Saved playback queue is invalid; ignoring it.")
            return None

        tracks_by_id = {track.id: track for track in library_tracks}
        tracks = [
            tracks_by_id[track_id]
            for track_id in track_ids
            if track_id in tracks_by_id
        ]
        current_track_id = payload.get("current_track_id")
        current_index = next(
            (
                index
                for index, track in enumerate(tracks)
                if track.id == current_track_id
            ),
            -1,
        )
        position = self._valid_number(payload.get("position_seconds"), 0.0)
        position = max(0.0, position)
        volume = self._valid_number(payload.get("volume"), 1.0)
        is_muted = payload.get("is_muted")

        self._last_saved_position = position
        self._last_position_saved_at = time.monotonic()
        self._last_current_track_id = (
            tracks[current_index].id if current_index >= 0 else None
        )
        self._last_saved_payload = {
            "track_ids": [track.id for track in tracks],
            "current_track_id": self._last_current_track_id,
            "position_seconds": position,
            "volume": max(0.0, min(1.0, volume)),
            "is_muted": is_muted if isinstance(is_muted, bool) else False,
        }
        return SavedPlaybackSession(
            tracks=tracks,
            current_index=current_index,
            position_seconds=position,
            volume=max(0.0, min(1.0, volume)),
            is_muted=is_muted if isinstance(is_muted, bool) else False,
        )

    def save(
        self,
        queue: QueueManager,
        position_seconds: float,
        volume: float,
        is_muted: bool,
        *,
        force_position: bool = False,
    ) -> None:
        current_track = queue.current_track
        current_track_id = current_track.id if current_track else None
        if (
            self._last_saved_payload is not None
            and current_track_id != self._last_current_track_id
        ):
            position_seconds = 0.0
        position = max(0.0, position_seconds) if math.isfinite(position_seconds) else 0.0
        now = time.monotonic()
        should_save_position = (
            force_position
            or (
                self._last_saved_payload is not None
                and current_track_id != self._last_current_track_id
            )
            or now - self._last_position_saved_at >= _POSITION_SAVE_INTERVAL_SECONDS
            or abs(position - self._last_saved_position) >= _POSITION_SAVE_INTERVAL_SECONDS
        )
        if should_save_position:
            self._last_saved_position = position
            self._last_position_saved_at = now
        saved_position = self._last_saved_position

        payload = {
            "track_ids": [track.id for track in queue.queue],
            "current_track_id": current_track_id,
            "position_seconds": saved_position,
            "volume": max(0.0, min(1.0, volume)),
            "is_muted": is_muted,
        }
        if payload == self._last_saved_payload:
            return
        self.connection.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (_SESSION_SETTING_KEY, json.dumps(payload)),
        )
        self.connection.commit()
        self._last_current_track_id = current_track_id
        self._last_saved_payload = payload

    @staticmethod
    def _valid_number(value: object, fallback: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return fallback
        number = float(value)
        return number if math.isfinite(number) else fallback
