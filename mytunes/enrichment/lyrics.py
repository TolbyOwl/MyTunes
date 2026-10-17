from __future__ import annotations
try:
    import httpx
except ImportError:
    class _DummyResponse:
        def __init__(self, status_code=404):
            self.status_code = status_code
        def json(self):
            return {}
    class _DummyClient:
        def __init__(self, *args, **kwargs):
            pass
        def get(self, *args, **kwargs):
            return _DummyResponse()
    httpx = type('httpx', (), {'Client': _DummyClient})
import re
from typing import List, Tuple, Optional

class LyricsLine:
    def __init__(self, time_seconds: float, text: str):
        self.time_seconds = time_seconds
        self.text = text

class LyricsEngine:
    """Fetches synced and plain-text lyrics from LRCLIB API and parses timestamps."""

    def __init__(self):
        self.client = httpx.Client(timeout=8.0, headers={"User-Agent": "MyTunes/1.0"})

    def fetch_lyrics(
        self,
        track_title: str,
        artist: str,
        album: str = "",
        duration: float = 0.0
    ) -> Tuple[List[LyricsLine], str]:
        """
        Fetches lyrics from LRCLIB.
        Returns:
            Tuple of (parsed_synced_lines, plain_text_fallback)
        """
        url = "https://lrclib.net/api/get"
        params = {
            "track_name": track_title,
            "artist_name": artist,
        }
        if album and album != "Unknown Album":
            params["album_name"] = album
        if duration > 0:
            params["duration"] = int(duration)

        try:
            resp = self.client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                synced = data.get("syncedLyrics")
                plain = data.get("plainLyrics") or ""
                if synced:
                    lines = self.parse_synced_lrc(synced)
                    return lines, plain
                return [], plain
        except Exception:
            pass

        # Try fallback search if exact match returned 404
        try:
            search_url = "https://lrclib.net/api/search"
            resp = self.client.get(search_url, params={"q": f"{artist} {track_title}"})
            if resp.status_code == 200:
                results = resp.json()
                if results and isinstance(results, list):
                    first = results[0]
                    synced = first.get("syncedLyrics")
                    plain = first.get("plainLyrics") or ""
                    if synced:
                        return self.parse_synced_lrc(synced), plain
                    return [], plain
        except Exception:
            pass

        return [], ""

    @staticmethod
    def parse_synced_lrc(lrc_text: str) -> List[LyricsLine]:
        """Parses standard LRC format [mm:ss.xx] line."""
        lines: List[LyricsLine] = []
        pattern = re.compile(r"\[(\d{2}):(\d{2}(?:\.\d{2,3})?)\](.*)")

        for raw_line in lrc_text.splitlines():
            match = pattern.match(raw_line.strip())
            if match:
                mins = int(match.group(1))
                secs = float(match.group(2))
                text = match.group(3).strip()
                total_sec = mins * 60 + secs
                lines.append(LyricsLine(total_sec, text))

        lines.sort(key=lambda l: l.time_seconds)
        return lines

    @staticmethod
    def get_active_line_index(lines: List[LyricsLine], current_time: float) -> int:
        """Finds the index of the line that should currently be highlighted."""
        if not lines:
            return -1
        idx = -1
        for i, line in enumerate(lines):
            if line.time_seconds <= current_time:
                idx = i
            else:
                break
        return idx
