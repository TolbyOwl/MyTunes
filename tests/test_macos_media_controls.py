import asyncio
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from mytunes.core.macos_media_controls import MacOSMediaControls
from mytunes.models.track import Track


class _RemoteCommand:
    def __init__(self):
        self.handler = None
        self.enabled = False
        self.targets = []

    def addTargetWithHandler_(self, handler):
        self.handler = handler
        target = object()
        self.targets.append(target)
        return target

    def setEnabled_(self, enabled):
        self.enabled = enabled

    def removeTarget_(self, target):
        self.targets.remove(target)


class _NowPlayingCenter:
    def __init__(self):
        self.info = None

    @classmethod
    def defaultCenter(cls):
        if not hasattr(cls, "center"):
            cls.center = cls()
        return cls.center

    def setNowPlayingInfo_(self, info):
        self.info = info

    def nowPlayingInfo(self):
        return self.info


class _RemoteCommandCenter:
    def __init__(self):
        self.playCommand = _RemoteCommand()
        self.pauseCommand = _RemoteCommand()
        self.togglePlayPauseCommand = _RemoteCommand()
        self.stopCommand = _RemoteCommand()
        self.nextTrackCommand = _RemoteCommand()
        self.previousTrackCommand = _RemoteCommand()

    @classmethod
    def sharedCommandCenter(cls):
        if not hasattr(cls, "center"):
            cls.center = cls()
        return cls.center


class _Image:
    @classmethod
    def alloc(cls):
        return cls()

    def initWithContentsOfFile_(self, path):
        return f"image:{path}"


class _Artwork:
    @classmethod
    def alloc(cls):
        return cls()

    def initWithBoundsSize_requestHandler_(self, size, handler):
        return ("artwork", size, handler(size))


class TestMacOSMediaControls(unittest.TestCase):
    def setUp(self):
        _NowPlayingCenter.center = _NowPlayingCenter()
        _RemoteCommandCenter.center = _RemoteCommandCenter()
        self.page = Mock()
        self.actions = Mock()
        self.media_player = SimpleNamespace(
            MPNowPlayingInfoCenter=_NowPlayingCenter,
            MPRemoteCommandCenter=_RemoteCommandCenter,
            MPRemoteCommandHandlerStatusSuccess=1,
            MPMediaItemPropertyTitle="title",
            MPMediaItemPropertyArtist="artist",
            MPMediaItemPropertyAlbumTitle="album",
            MPMediaItemPropertyPlaybackDuration="duration",
            MPMediaItemPropertyElapsedPlaybackTime="elapsed",
            MPMediaItemPropertyPlaybackRate="rate",
            MPMediaItemPropertyAlbumTrackNumber="track_number",
            MPMediaItemPropertyAlbumArtist="album_artist",
            MPMediaItemPropertyArtwork="artwork",
            MPMediaItemArtwork=_Artwork,
        )

    def test_publishes_now_playing_and_registers_remote_commands(self):
        with patch.object(sys, "platform", "darwin"), patch.dict(
            sys.modules,
            {"AppKit": SimpleNamespace(), "MediaPlayer": self.media_player},
        ):
            controls = MacOSMediaControls(self.page, Mock(), Mock())
            controls.actions = self.actions
            controls.update_track(
                Track(
                    id="mac-track",
                    title="Song",
                    artist="Artist",
                    album="Album",
                    album_artist="Album Artist",
                    duration=120,
                    track_number=2,
                )
            )
            controls.update_playback_state(False)
            controls.update_position(15, 120)
            result = controls._remote_commands.nextTrackCommand.handler(None)
            info = dict(self.media_player.MPNowPlayingInfoCenter.center.info)
            controls.close()

        self.assertEqual(info["title"], "Song")
        self.assertEqual(info["artist"], "Artist")
        self.assertEqual(info["album"], "Album")
        self.assertEqual(info["duration"], 120)
        self.assertEqual(info["album_artist"], "Album Artist")
        self.assertEqual(info["track_number"], 2)
        self.assertEqual(info["rate"], 0.0)
        self.assertEqual(info["elapsed"], 15)
        self.actions.dispatch.assert_called_once_with("next")
        self.assertEqual(result, 1)
        self.assertEqual(
            len(controls._remote_commands.nextTrackCommand.targets), 0
        )

    def test_publishes_cached_artwork_in_now_playing_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            artwork_path = Path(temp_dir) / "cover.jpg"
            artwork_path.write_bytes(b"image")
            with patch.object(sys, "platform", "darwin"), patch.dict(
                sys.modules,
                {
                    "AppKit": SimpleNamespace(
                        NSImage=_Image,
                        NSMakeSize=lambda width, height: (width, height),
                    ),
                    "MediaPlayer": self.media_player,
                },
            ):
                controls = MacOSMediaControls(self.page, Mock(), Mock())
                controls._appkit = sys.modules["AppKit"]
                controls.update_track(Track(id="mac-art", title="Song"))
                with patch.object(
                    controls.artwork_cache,
                    "resolve",
                    new=AsyncMock(return_value=artwork_path),
                ):
                    asyncio.run(
                        controls._update_artwork(
                            controls._track_generation,
                            Track(id="mac-art", title="Song"),
                        )
                    )
                info = self.media_player.MPNowPlayingInfoCenter.center.info
                controls.close()

        self.assertEqual(
            info["artwork"], ("artwork", (600, 600), f"image:{artwork_path}")
        )


if __name__ == "__main__":
    unittest.main()
