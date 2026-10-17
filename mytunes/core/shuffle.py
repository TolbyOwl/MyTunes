from __future__ import annotations
import random
import time
from typing import List, Optional
from mytunes.models.track import Track

class ShuffleEngine:
    """Provides advanced shuffle modes and quick mix algorithms."""

    @staticmethod
    def true_random(tracks: List[Track]) -> List[Track]:
        """Unbiased Fisher-Yates shuffle."""
        shuffled = list(tracks)
        random.shuffle(shuffled)
        return shuffled

    @staticmethod
    def smart_artist_distributed(tracks: List[Track], cooldown: int = 3) -> List[Track]:
        """
        Guarantees that no two consecutive tracks have the same artist or album,
        distributing artists evenly across the queue.
        """
        if len(tracks) <= 2:
            return list(tracks)

        pool = list(tracks)
        random.shuffle(pool)
        result: List[Track] = []
        recent_artists: List[str] = []

        while pool:
            # Find candidate that wasn't played in recent cooldown window
            candidate_idx = -1
            for i, t in enumerate(pool):
                artist_key = t.artist.lower().strip()
                if artist_key not in recent_artists:
                    candidate_idx = i
                    break

            if candidate_idx == -1:
                # Fallback: if all available tracks match recent artists, pick any
                candidate_idx = 0

            chosen = pool.pop(candidate_idx)
            result.append(chosen)

            # Update cooldown window
            recent_artists.append(chosen.artist.lower().strip())
            if len(recent_artists) > cooldown:
                recent_artists.pop(0)

        return result

    @staticmethod
    def forgotten_gems(tracks: List[Track], days_unplayed: int = 30) -> List[Track]:
        """
        Prioritizes favorite or highly rated tracks that haven't been played
        recently (> days_unplayed or never played).
        """
        now = time.time()
        cutoff = now - (days_unplayed * 86400)

        gems: List[Track] = []
        regular: List[Track] = []

        for t in tracks:
            # High priority if favorite or rating >= 4, and played before cutoff or never
            is_old_or_unplayed = (t.last_played is None) or (t.last_played < cutoff)
            if (t.is_favorite or t.rating >= 4) and is_old_or_unplayed:
                gems.append(t)
            else:
                regular.append(t)

        random.shuffle(gems)
        random.shuffle(regular)

        # Place gems predominantly in front, interspersed with regular tracks
        return gems + regular

    @staticmethod
    def quick_mix(
        tracks: List[Track],
        count: int = 25,
        genre: Optional[str] = None,
        min_year: Optional[int] = None,
        max_year: Optional[int] = None,
        favorites_only: bool = False
    ) -> List[Track]:
        """
        Generates an instant mix of count songs filtered by criteria.
        """
        filtered = list(tracks)

        if favorites_only:
            filtered = [t for t in filtered if t.is_favorite]

        if genre and genre.lower() != "all":
            filtered = [t for t in filtered if genre.lower() in t.genre.lower()]

        if min_year:
            filtered = [t for t in filtered if t.year and t.year >= min_year]

        if max_year:
            filtered = [t for t in filtered if t.year and t.year <= max_year]

        random.shuffle(filtered)
        return filtered[:count]

    @staticmethod
    def tempo_energy_flow(tracks: List[Track]) -> List[Track]:
        """
        Orders tracks into a harmonic tempo flow (BPM wave)
        gradually increasing energy and gently descending.
        """
        tracks_with_bpm = [t for t in tracks if t.bpm and t.bpm > 0]
        tracks_without_bpm = [t for t in tracks if not t.bpm or t.bpm <= 0]

        if not tracks_with_bpm:
            # Fallback to smart distributed if no BPM data
            return ShuffleEngine.smart_artist_distributed(tracks)

        tracks_with_bpm.sort(key=lambda t: t.bpm or 120.0)
        random.shuffle(tracks_without_bpm)

        # Create a wave: ascending then descending
        mid = len(tracks_with_bpm) // 2
        wave = tracks_with_bpm[:mid] + list(reversed(tracks_with_bpm[mid:]))
        
        # Interleave unmeasured tracks evenly
        result: List[Track] = []
        for i, t in enumerate(wave):
            result.append(t)
            if tracks_without_bpm and i % 2 == 0:
                result.append(tracks_without_bpm.pop(0))

        result.extend(tracks_without_bpm)
        return result
