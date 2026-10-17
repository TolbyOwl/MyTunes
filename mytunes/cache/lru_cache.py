from __future__ import annotations
import os
import hashlib
import time
import httpx
from typing import Dict, Optional, Callable

DEFAULT_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".mytunes", "audio_cache")
OFFLINE_DIR = os.path.join(os.path.expanduser("~"), ".mytunes", "offline_downloads")

class CacheManager:
    """
    Hybrid streaming & LRU cache manager.
    Streams audio files directly, caches them locally for instant replay,
    and supports explicit offline pinning.
    """

    def __init__(self, max_cache_bytes: int = 2 * 1024 * 1024 * 1024):  # 2 GB default
        self.cache_dir = DEFAULT_CACHE_DIR
        self.offline_dir = OFFLINE_DIR
        self.max_cache_bytes = max_cache_bytes
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.offline_dir, exist_ok=True)
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def _get_cache_path(self, url: str) -> str:
        ext = os.path.splitext(url.split("?")[0])[1] or ".mp3"
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{url_hash}{ext}")

    def _get_offline_path(self, track_id: str, title: str) -> str:
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-')).strip()
        return os.path.join(self.offline_dir, f"{safe_title}_{track_id}.mp3")

    def is_cached_or_offline(self, url: str, track_id: Optional[str] = None, title: Optional[str] = None) -> Optional[str]:
        """Returns the local path if track is downloaded or cached."""
        if track_id and title:
            offline_file = self._get_offline_path(track_id, title)
            if os.path.exists(offline_file):
                return offline_file

        cache_file = self._get_cache_path(url)
        if os.path.exists(cache_file):
            # Touch access time for LRU
            os.utime(cache_file, None)
            return cache_file
        return None

    def download_for_offline(
        self,
        url: str,
        track_id: str,
        title: str,
        on_progress: Optional[Callable[[float], None]] = None
    ) -> Optional[str]:
        """Explicitly downloads track for permanent offline playback."""
        target_path = self._get_offline_path(track_id, title)
        if os.path.exists(target_path):
            return target_path

        temp_path = f"{target_path}.tmp"
        try:
            with self.client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    return None
                total_bytes = int(resp.headers.get("Content-Length", 0))
                downloaded = 0

                with open(temp_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=32768):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if on_progress and total_bytes > 0:
                                on_progress(downloaded / total_bytes)

            os.rename(temp_path, target_path)
            return target_path
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return None

    def cache_stream_chunk(self, url: str) -> Optional[str]:
        """Downloads stream in background to LRU cache."""
        cache_path = self._get_cache_path(url)
        if os.path.exists(cache_path):
            return cache_path

        self._enforce_lru_limit()
        temp_path = f"{cache_path}.tmp"
        try:
            with self.client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    return None
                with open(temp_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        if chunk:
                            f.write(chunk)

            os.rename(temp_path, cache_path)
            return cache_path
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return None

    def _enforce_lru_limit(self) -> None:
        """Evicts oldest accessed cached files if cache exceeds maximum allowed size."""
        try:
            cached_files = []
            total_size = 0
            for entry in os.scandir(self.cache_dir):
                if entry.is_file():
                    stat = entry.stat()
                    total_size += stat.st_size
                    cached_files.append((stat.st_atime, stat.st_size, entry.path))

            if total_size <= self.max_cache_bytes:
                return

            # Sort by least recently accessed
            cached_files.sort(key=lambda x: x[0])
            for atime, size, fpath in cached_files:
                try:
                    os.remove(fpath)
                    total_size -= size
                    if total_size <= self.max_cache_bytes * 0.8:
                        break
                except Exception:
                    pass
        except Exception:
            pass
