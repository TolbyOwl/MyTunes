from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import time

@dataclass
class Episode:
    id: str
    podcast_id: str
    title: str
    description: str = ""
    audio_url: str = ""
    duration: float = 0.0
    published_at: Optional[float] = None
    playback_position: float = 0.0  # Resume timestamp in seconds
    is_played: bool = False
    is_downloaded: bool = False
    download_path: Optional[str] = None

@dataclass
class PodcastShow:
    id: str
    title: str
    author: str = ""
    description: str = ""
    feed_url: str = ""
    artwork_url: Optional[str] = None
    episodes: List[Episode] = field(default_factory=list)
    date_subscribed: float = field(default_factory=time.time)
