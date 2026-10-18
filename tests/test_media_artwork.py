import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mytunes.core.media_artwork import MediaArtworkCache
from mytunes.models.track import Track


class _Response:
    headers = {"content-type": "image/png"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def raise_for_status(self):
        return None

    async def aiter_bytes(self):
        yield b"image data"


class _Client:
    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def stream(self, *_args, **_kwargs):
        return _Response()


class TestMediaArtworkCache(unittest.TestCase):
    def test_uses_existing_local_artwork(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "cover.jpg"
            image.write_bytes(b"local image")
            cache = MediaArtworkCache(Path(temp_dir) / "cache")

            result = asyncio.run(
                cache.resolve(Track(id="local", title="Song", artwork_path=str(image)))
            )

            self.assertEqual(result, image.resolve())

    def test_downloads_remote_artwork_once_and_reuses_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = MediaArtworkCache(Path(temp_dir))
            track = Track(
                id="remote",
                title="Song",
                artwork_url="https://example.test/cover",
            )
            with patch(
                "mytunes.core.media_artwork.httpx.AsyncClient", side_effect=_Client
            ) as client:
                first_result = asyncio.run(cache.resolve(track))
                second_result = asyncio.run(cache.resolve(track))

            self.assertIsNotNone(first_result)
            self.assertEqual(first_result, second_result)
            assert first_result is not None
            self.assertEqual(first_result.suffix, ".png")
            self.assertEqual(first_result.read_bytes(), b"image data")
            client.assert_called_once()


if __name__ == "__main__":
    unittest.main()
