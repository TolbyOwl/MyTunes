from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json

@dataclass
class Track:
    id: str
    title: str
    artist: str = "Unknown Artist"
    album: str = "Unknown Album"
    album_artist: str = ""
    genre: str = "Unknown Genre"
    year: Optional[int] = None
    duration: float = 0.0  # seconds
    track_number: Optional[int] = None
    disc_number: Optional[int] = 1
    file_path: str = ""  # Local path or cloud URI
    source: str = "local"  # "local", "gdrive", "onedrive", "dropbox", "stream"
    artwork_path: Optional[str] = None  # Local cached thumbnail path
    artwork_url: Optional[str] = None   # Remote cover art URL
    bitrate: Optional[int] = None
    play_count: int = 0
    last_played: Optional[float] = None # Unix timestamp
    is_favorite: bool = False
    rating: int = 0  # 0 to 5
    bpm: Optional[float] = None
    date_added: float = 0.0

    @property
    def formatted_duration(self) -> str:
        mins = int(self.duration // 60)
        secs = int(self.duration % 60)
        return f"{mins}:{secs:02d}"

@dataclass
class Album:
    id: str
    title: str
    artist: str
    year: Optional[int] = None
    genre: Optional[str] = None
    artwork_path: Optional[str] = None
    track_count: int = 0

@dataclass
class Artist:
    name: str
    album_count: int = 0
    track_count: int = 0
