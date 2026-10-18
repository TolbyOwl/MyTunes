# D-Bus service annotations use signature strings instead of Python types.
# pyright: reportInvalidTypeForm=false
import importlib
import logging
import random
import sys
from typing import Any

from mytunes.core.audio import AudioEngine
from mytunes.core.media_artwork import MediaArtworkCache
from mytunes.core.media_control_actions import MediaControlActions
from mytunes.core.queue import QueueManager
from mytunes.models.track import Track

logger = logging.getLogger(__name__)

MPRIS_OBJECT_PATH = "/org/mpris/MediaPlayer2"
MPRIS_BUS_NAME = "org.mpris.MediaPlayer2.mytunes"

if sys.platform.startswith("linux"):
    from dbus_next.constants import PropertyAccess
    from dbus_next.errors import DBusError
    from dbus_next.signature import Variant
    from dbus_next.service import ServiceInterface, dbus_property, method

    DBUS_BOOL = "b"
    DBUS_DOUBLE = "d"
    DBUS_INT64 = "x"
    DBUS_METADATA = "a{sv}"
    DBUS_OBJECT_PATH = "o"
    DBUS_STRING = "s"
    DBUS_STRING_ARRAY = "as"
    DBUS_VOID = ""

    class _MprisRoot(ServiceInterface):
        def __init__(self) -> None:
            super().__init__("org.mpris.MediaPlayer2")

        @dbus_property(access=PropertyAccess.READ)
        def CanQuit(self) -> DBUS_BOOL:
            return False

        @dbus_property(access=PropertyAccess.READ)
        def CanRaise(self) -> DBUS_BOOL:
            return False

        @dbus_property(access=PropertyAccess.READ)
        def HasTrackList(self) -> DBUS_BOOL:
            return False

        @dbus_property(access=PropertyAccess.READ)
        def Identity(self) -> DBUS_STRING:
            return "MyTunes"

        @dbus_property(access=PropertyAccess.READ)
        def DesktopEntry(self) -> DBUS_STRING:
            return "mytunes"

        @dbus_property(access=PropertyAccess.READ)
        def SupportedUriSchemes(self) -> DBUS_STRING_ARRAY:
            return []

        @dbus_property(access=PropertyAccess.READ)
        def SupportedMimeTypes(self) -> DBUS_STRING_ARRAY:
            return []

        @method()
        def Raise(self) -> DBUS_VOID:
            return

        @method()
        def Quit(self) -> DBUS_VOID:
            return

    class _MprisPlayer(ServiceInterface):
        def __init__(self, owner: "LinuxMprisControls") -> None:
            super().__init__("org.mpris.MediaPlayer2.Player")
            self.owner = owner

        @dbus_property(access=PropertyAccess.READ)
        def PlaybackStatus(self) -> DBUS_STRING:
            if self.owner.audio_engine.is_playing:
                return "Playing"
            if self.owner.is_stopped:
                return "Stopped"
            return "Paused"

        @dbus_property()
        def LoopStatus(self) -> DBUS_STRING:
            if self.owner.queue_manager.repeat_mode.value == "one":
                return "Track"
            if self.owner.queue_manager.repeat_mode.value == "all":
                return "Playlist"
            return "None"

        @dbus_property()
        def Rate(self) -> DBUS_DOUBLE:
            return float(self.owner.audio_engine.playback_rate)

        @dbus_property()
        def Shuffle(self) -> DBUS_BOOL:
            return bool(self.owner.queue_manager.is_shuffled)

        @dbus_property(access=PropertyAccess.READ)
        def Metadata(self) -> DBUS_METADATA:
            track = self.owner.queue_manager.current_track
            if track is None:
                return {}

            metadata = {
                "mpris:trackid": Variant("o", self.owner.current_track_id),
                "mpris:length": Variant("x", int(max(0.0, track.duration) * 1_000_000)),
                "xesam:title": Variant("s", track.title),
                "xesam:artist": Variant("as", [track.artist]),
                "xesam:album": Variant("s", track.album),
                "xesam:albumArtist": Variant(
                    "as", [track.album_artist or track.artist]
                ),
            }
            if track.track_number is not None:
                metadata["xesam:trackNumber"] = Variant("i", track.track_number)
            if self.owner.artwork_uri is not None:
                metadata["mpris:artUrl"] = Variant("s", self.owner.artwork_uri)
            return metadata

        @dbus_property()
        def Volume(self) -> DBUS_DOUBLE:
            if self.owner.audio_engine.is_muted:
                return 0.0
            return float(self.owner.audio_engine.volume)

        @LoopStatus.setter
        def LoopStatus(self, value: DBUS_STRING):
            from mytunes.core.queue import RepeatMode

            repeat_modes = {
                "None": RepeatMode.OFF,
                "Track": RepeatMode.ONE,
                "Playlist": RepeatMode.ALL,
            }
            if value not in repeat_modes:
                raise DBusError(
                    "org.freedesktop.DBus.Error.InvalidArgs",
                    f"Invalid MPRIS loop status: {value}",
                )
            self.owner.queue_manager.repeat_mode = repeat_modes[value]
            self.owner._emit_player_properties("LoopStatus")

        @Rate.setter
        def Rate(self, value: DBUS_DOUBLE):
            if not 0.5 <= value <= 2.5:
                raise DBusError(
                    "org.freedesktop.DBus.Error.InvalidArgs",
                    "Playback rate must be between 0.5 and 2.5.",
                )
            self.owner.audio_engine.set_playback_rate(value)
            self.owner._emit_player_properties("Rate")

        @Shuffle.setter
        def Shuffle(self, value: DBUS_BOOL):
            self.owner.set_shuffle(value)

        @Volume.setter
        def Volume(self, value: DBUS_DOUBLE):
            if not 0.0 <= value <= 1.0:
                raise DBusError(
                    "org.freedesktop.DBus.Error.InvalidArgs",
                    "Volume must be between 0.0 and 1.0.",
                )
            if value > 0 and self.owner.audio_engine.is_muted:
                self.owner.audio_engine.toggle_mute()
            self.owner.audio_engine.set_volume(value)

        @dbus_property(access=PropertyAccess.READ)
        def Position(self) -> DBUS_INT64:
            return int(max(0.0, self.owner.position_seconds) * 1_000_000)

        @dbus_property(access=PropertyAccess.READ)
        def MinimumRate(self) -> DBUS_DOUBLE:
            return 0.5

        @dbus_property(access=PropertyAccess.READ)
        def MaximumRate(self) -> DBUS_DOUBLE:
            return 2.5

        @dbus_property(access=PropertyAccess.READ)
        def CanGoNext(self) -> DBUS_BOOL:
            queue = self.owner.queue_manager
            return bool(
                queue.current_track
                and (
                    queue.current_index + 1 < len(queue.queue)
                    or queue.repeat_mode.value in ("all", "one")
                )
            )

        @dbus_property(access=PropertyAccess.READ)
        def CanGoPrevious(self) -> DBUS_BOOL:
            queue = self.owner.queue_manager
            return (
                queue.current_track is not None
                and (
                    queue.current_index > 0
                    or bool(queue.history)
                    or queue.repeat_mode.value == "all"
                )
            )

        @dbus_property(access=PropertyAccess.READ)
        def CanPlay(self) -> DBUS_BOOL:
            return self.owner.queue_manager.current_track is not None

        @dbus_property(access=PropertyAccess.READ)
        def CanPause(self) -> DBUS_BOOL:
            return self.owner.queue_manager.current_track is not None

        @dbus_property(access=PropertyAccess.READ)
        def CanSeek(self) -> DBUS_BOOL:
            track = self.owner.queue_manager.current_track
            return bool(track and track.duration > 0)

        @dbus_property(access=PropertyAccess.READ)
        def CanControl(self) -> DBUS_BOOL:
            return True

        @method()
        def Next(self) -> DBUS_VOID:
            self.owner.actions.dispatch("next")

        @method()
        def Previous(self) -> DBUS_VOID:
            self.owner.actions.dispatch("previous")

        @method()
        def Pause(self) -> DBUS_VOID:
            self.owner.actions.dispatch("pause")

        @method()
        def PlayPause(self) -> DBUS_VOID:
            self.owner.actions.dispatch("play_pause")

        @method()
        def Stop(self) -> DBUS_VOID:
            self.owner.actions.dispatch("stop")

        @method()
        def Play(self) -> DBUS_VOID:
            self.owner.actions.dispatch("play")

        @method()
        def Seek(self, offset: DBUS_INT64) -> DBUS_VOID:
            track = self.owner.queue_manager.current_track
            if track is not None and track.duration > 0:
                target = self.owner.position_seconds + offset / 1_000_000
                self.owner.actions.seek(min(max(0.0, target), track.duration))

        @method()
        def SetPosition(
            self, track_id: DBUS_OBJECT_PATH, position: DBUS_INT64
        ) -> DBUS_VOID:
            track = self.owner.queue_manager.current_track
            if track is not None and track_id == self.owner.current_track_id:
                self.owner.actions.seek(
                    min(max(0.0, position / 1_000_000), track.duration)
                )

        @method()
        def OpenUri(self, _uri: DBUS_STRING) -> DBUS_VOID:
            raise DBusError(
                "org.mpris.MediaPlayer2.Player.NotSupported",
                "Opening arbitrary media URIs is not supported.",
            )


class LinuxMprisControls:
    """Exports MyTunes playback state and controls over the session D-Bus."""

    def __init__(
        self,
        page: Any,
        audio_engine: AudioEngine,
        queue_manager: QueueManager,
    ) -> None:
        self.page = page
        self.audio_engine = audio_engine
        self.queue_manager = queue_manager
        self.actions = MediaControlActions(page, audio_engine, queue_manager)
        self.artwork_cache = MediaArtworkCache()
        self._bus: Any = None
        self._player_interface: Any = None
        self._track_generation = 0
        self._track_id = "/org/mpris/MediaPlayer2/track/none"
        self.artwork_uri: str | None = None
        self.position_seconds = 0.0
        self.is_stopped = True
        self._registered = False

        if not sys.platform.startswith("linux"):
            return

        try:
            self._player_interface = _MprisPlayer(self)
            page.run_task(self._start)
        except Exception:
            logger.exception("Failed to schedule Linux MPRIS initialization.")

    @property
    def current_track_id(self) -> str:
        return self._track_id

    async def _start(self) -> None:
        try:
            message_bus = importlib.import_module(
                "dbus_next.aio.message_bus"
            ).MessageBus
            self._bus = await message_bus().connect()
            self._bus.export(MPRIS_OBJECT_PATH, _MprisRoot())
            self._bus.export(MPRIS_OBJECT_PATH, self._player_interface)
            await self._bus.request_name(MPRIS_BUS_NAME)
            self._registered = True
            self._emit_player_properties(
                "PlaybackStatus",
                "Metadata",
                "Position",
                "CanGoNext",
                "CanGoPrevious",
                "CanPlay",
                "CanPause",
                "CanSeek",
            )
            logger.info("Registered MyTunes MPRIS session on D-Bus.")
        except Exception:
            logger.exception(
                "Could not register MyTunes MPRIS controls. Check that this "
                "Linux desktop session provides a session D-Bus."
            )
            if self._bus is not None:
                self._bus.disconnect()
                self._bus = None

    def update_track(self, track: Track | None) -> None:
        self._track_generation += 1
        generation = self._track_generation
        self.position_seconds = 0.0
        self.artwork_uri = None
        if track is None:
            self._track_id = "/org/mpris/MediaPlayer2/track/none"
        else:
            self.is_stopped = True
            self._track_id = f"/org/mpris/MediaPlayer2/track/{track.id.encode().hex()}"
            self.page.run_task(self._update_artwork, generation, track)
        if track is None:
            self.is_stopped = True
        self._emit_player_properties(
            "Metadata",
            "Position",
            "CanGoNext",
            "CanGoPrevious",
            "CanPlay",
            "CanPause",
            "CanSeek",
        )

    async def _update_artwork(self, generation: int, track: Track) -> None:
        artwork_path = await self.artwork_cache.resolve(track)
        if generation != self._track_generation or self._player_interface is None:
            return

        self.artwork_uri = artwork_path.as_uri() if artwork_path is not None else None
        self._emit_player_properties("Metadata")

    def update_playback_state(self, _is_playing: bool) -> None:
        self.is_stopped = False
        self._emit_player_properties("PlaybackStatus")

    def update_playback_stopped(self) -> None:
        self.is_stopped = True
        self.position_seconds = 0.0
        self._emit_player_properties("PlaybackStatus", "Position")

    def update_position(self, current_seconds: float, _total_seconds: float) -> None:
        self.position_seconds = max(0.0, current_seconds)

    def update_volume(self, _volume: float) -> None:
        self._emit_player_properties("Volume")

    def _emit_player_properties(self, *names: str) -> None:
        if self._player_interface is None or not self._registered:
            return
        try:
            values = {
                name: getattr(self._player_interface, name)
                for name in names
            }
            self._player_interface.emit_properties_changed(values)
        except Exception:
            logger.exception("Failed to notify Linux media controls of changes.")

    def set_shuffle(self, enabled: bool) -> None:
        if self.queue_manager.is_shuffled == enabled:
            return

        queue = self.queue_manager
        current_track = queue.current_track
        if enabled:
            queue.original_queue = list(queue.queue)
            random.shuffle(queue.queue)
            if current_track is not None:
                queue.current_index = next(
                    index
                    for index, track in enumerate(queue.queue)
                    if track is current_track
                )
        else:
            original_queue = list(queue.original_queue)
            if current_track is not None:
                queue.current_index = next(
                    (
                        index
                        for index, track in enumerate(original_queue)
                        if track is current_track
                    ),
                    -1,
                )
            queue.queue = original_queue
        queue.is_shuffled = enabled
        self._emit_player_properties("Shuffle", "CanGoNext", "CanGoPrevious")

    def close(self) -> None:
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None
        self._registered = False
