from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

@dataclass
class RadioStation:
    id: str
    name: str
    stream_url: str
    homepage: str = ""
    favicon: Optional[str] = None
    country: str = ""
    language: str = ""
    tags: str = ""
    codec: str = ""
    bitrate: int = 0
    is_favorite: bool = False
