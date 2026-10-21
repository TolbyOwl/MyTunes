from __future__ import annotations
from typing import List, Optional, Callable, TYPE_CHECKING
from enum import Enum
from mytunes.models.track import Track

if TYPE_CHECKING:
    from mytunes.core.shuffle import ShuffleEngine

class RepeatMode(str, Enum):
    OFF = "off"
    ALL = "all"
    ONE = "one"

class QueueManager:
    """Manages the current playback queue, history, and next/prev progression."""

    def __init__(self, on_track_changed: Optional[Callable[[Optional[Track]], None]] = None):
        self.queue: List[Track] = []
        self.history: List[Track] = []
        self.current_index: int = -1
        self.repeat_mode: RepeatMode = RepeatMode.OFF
        self.is_shuffled: bool = False
        self.original_queue: List[Track] = []
        self.on_track_changed = on_track_changed
        self.on_queue_changed: Optional[Callable[[], None]] = None

    def _notify_queue_changed(self) -> None:
        if self.on_queue_changed:
            self.on_queue_changed()

    @property
    def current_track(self) -> Optional[Track]:
        if 0 <= self.current_index < len(self.queue):
            return self.queue[self.current_index]
        return None

    def set_queue(
        self,
        tracks: List[Track],
        start_index: int = 0,
        *,
        notify: bool = True,
    ) -> Optional[Track]:
        """Sets a new queue and optionally notifies listeners immediately."""
        self.queue = list(tracks)
        self.original_queue = list(tracks)
        self.history.clear()
        if 0 <= start_index < len(self.queue):
            self.current_index = start_index
        else:
            self.current_index = 0 if self.queue else -1

        if notify:
            self.notify_queue_state_changed()
        current = self.current_track
        return current

    def notify_queue_state_changed(self) -> None:
        """Notify listeners after a queue and its current track have changed."""
        if self.on_track_changed:
            self.on_track_changed(self.current_track)
        self._notify_queue_changed()

    def play_next(self, track: Track) -> None:
        """Inserts a track immediately after the currently playing song."""
        if not self.queue:
            self.set_queue([track], 0)
            return

        insert_pos = self.current_index + 1
        self.queue.insert(insert_pos, track)
        self._notify_queue_changed()

    def add_to_queue(self, track: Track) -> None:
        """Appends a track to the end of the queue."""
        if not self.queue:
            self.set_queue([track], 0)
            return
        self.queue.append(track)
        self._notify_queue_changed()

    def play_at(self, index: int) -> Optional[Track]:
        """Selects a queue entry and notifies listeners without replacing the queue."""
        if not 0 <= index < len(self.queue):
            return None

        self.current_index = index
        current = self.current_track
        if self.on_track_changed:
            self.on_track_changed(current)
        self._notify_queue_changed()
        return current

    def reorder_at(self, old_index: int, new_index: int) -> bool:
        """Moves a queue entry while keeping the current track selected."""
        if not (
            0 <= old_index < len(self.queue)
            and 0 <= new_index < len(self.queue)
        ):
            return False
        if old_index == new_index:
            return True

        self.queue.insert(new_index, self.queue.pop(old_index))
        if self.current_index == old_index:
            self.current_index = new_index
        elif old_index < self.current_index <= new_index:
            self.current_index -= 1
        elif new_index <= self.current_index < old_index:
            self.current_index += 1

        self.original_queue = list(self.queue)
        self._notify_queue_changed()
        return True

    def next_track(self) -> Optional[Track]:
        """Advances to the next track according to repeat mode."""
        if not self.queue:
            return None

        if self.repeat_mode == RepeatMode.ONE:
            # Replay current track
            return self.current_track

        if self.current_track:
            self.history.append(self.current_track)

        if self.current_index + 1 < len(self.queue):
            self.current_index += 1
        elif self.repeat_mode == RepeatMode.ALL:
            self.current_index = 0
        else:
            # End of queue reached and repeat is OFF
            self.current_index = -1

        current = self.current_track
        if self.on_track_changed:
            self.on_track_changed(current)
        self._notify_queue_changed()
        return current

    def prev_track(self) -> Optional[Track]:
        """Moves to the previous track in history or queue."""
        if not self.queue:
            return None

        if self.current_index > 0:
            self.current_index -= 1
        elif self.history:
            prev = self.history.pop()
            # If in current queue, set index
            if prev in self.queue:
                self.current_index = self.queue.index(prev)
        elif self.repeat_mode == RepeatMode.ALL:
            self.current_index = len(self.queue) - 1

        current = self.current_track
        if self.on_track_changed:
            self.on_track_changed(current)
        self._notify_queue_changed()
        return current

    def remove_at(self, index: int) -> None:
        """Removes a track from the queue at a specific index."""
        if 0 <= index < len(self.queue):
            self.queue.pop(index)
            if index < self.current_index:
                self.current_index -= 1
            elif index == self.current_index:
                if self.current_index >= len(self.queue):
                    self.current_index = len(self.queue) - 1
                if self.on_track_changed:
                    self.on_track_changed(self.current_track)
            self._notify_queue_changed()

    def clear(self) -> None:
        """Clears the queue."""
        self.queue.clear()
        self.history.clear()
        self.current_index = -1
        if self.on_track_changed:
            self.on_track_changed(None)
        self._notify_queue_changed()
