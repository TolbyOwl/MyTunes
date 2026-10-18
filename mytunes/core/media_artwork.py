from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path

import httpx

from mytunes.models.track import Track

logger = logging.getLogger(__name__)

ARTWORK_CACHE_DIR = Path.home() / ".mytunes" / "art_cache"
MAX_ARTWORK_BYTES = 10 * 1024 * 1024
ARTWORK_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}


class MediaArtworkCache:
    """Resolves embedded/local artwork and caches remote cover images."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or ARTWORK_CACHE_DIR

    async def resolve(self, track: Track) -> Path | None:
        if track.artwork_path:
            local_path = Path(track.artwork_path).expanduser()
            if local_path.is_file():
                return local_path.resolve()

        if not track.artwork_url:
            return None

        digest = hashlib.sha256(track.artwork_url.encode("utf-8")).hexdigest()
        for extension in ARTWORK_EXTENSIONS.values():
            cached_path = self.cache_dir / f"{digest}{extension}"
            if cached_path.is_file():
                return cached_path

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                async with client.stream("GET", track.artwork_url) as response:
                    response.raise_for_status()
                    content_type = response.headers.get(
                        "content-type", ""
                    ).split(";", maxsplit=1)[0].strip().lower()
                    extension = ARTWORK_EXTENSIONS.get(content_type)
                    if extension is None:
                        logger.warning(
                            "Unsupported artwork type %r for track %s.",
                            content_type,
                            track.id,
                        )
                        return None

                    cached_path = self.cache_dir / f"{digest}{extension}"
                    if cached_path.is_file():
                        return cached_path

                    with tempfile.NamedTemporaryFile(
                        dir=self.cache_dir,
                        prefix=f"{digest}.",
                        suffix=".tmp",
                        delete=False,
                    ) as temp_file:
                        temporary_path = Path(temp_file.name)
                        downloaded = 0
                        async for chunk in response.aiter_bytes():
                            downloaded += len(chunk)
                            if downloaded > MAX_ARTWORK_BYTES:
                                raise ValueError(
                                    f"Artwork exceeds {MAX_ARTWORK_BYTES} bytes"
                                )
                            temp_file.write(chunk)
                        if downloaded == 0:
                            raise ValueError("Artwork response was empty")

            os.replace(temporary_path, cached_path)
            return cached_path
        except (httpx.HTTPError, OSError, ValueError):
            logger.exception("Failed to cache artwork for track %s.", track.id)
            return None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
