from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import os
import time

@dataclass
class Playlist:
    id: str
    name: str
    description: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    track_ids: List[str] = field(default_factory=list)
    is_smart: bool = False
    smart_rules: Optional[str] = None  # JSON string of filter rules

    @classmethod
    def from_m3u(cls, filepath: str, playlist_id: str) -> "Playlist":
        """Parses an .m3u or .m3u8 file into a Playlist object."""
        name = os.path.splitext(os.path.basename(filepath))[0]
        track_paths = []
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # If relative path, resolve relative to m3u location
                        if not os.path.isabs(line) and not "://" in line:
                            line = os.path.abspath(os.path.join(os.path.dirname(filepath), line))
                        track_paths.append(line)
        return cls(
            id=playlist_id,
            name=name,
            track_ids=track_paths
        )

    def export_m3u(self, filepath: str, track_paths: List[str]) -> None:
        """Exports the playlist to an .m3u file."""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            f.write(f"#PLAYLIST:{self.name}\n")
            for path in track_paths:
                f.write(f"{path}\n")
