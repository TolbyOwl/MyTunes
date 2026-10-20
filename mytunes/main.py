from __future__ import annotations
import os
import sys
import ctypes
import time
import asyncio
import logging
import inspect
import flet as ft
from typing import Any, Callable, Optional

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
try:
    import pygame
except ImportError:
    pygame = None

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mytunes.models.schema import init_db
from mytunes.models.track import Track
from mytunes.models.radio import RadioStation
from mytunes.models.podcast import Episode, PodcastShow
from mytunes.providers.local import LocalProvider
from mytunes.providers.metadata import ArtistMetadataProvider
from mytunes.sync.sync_manager import SyncManager
from mytunes.core.queue import QueueManager
from mytunes.core.audio import AudioEngine
from mytunes.core.playback_session import PlaybackSessionStore
from mytunes.core.media_controls import create_media_controls
from mytunes.ui.theme import MetroTheme
from mytunes.ui.components.pivot_nav import PivotNav
from mytunes.ui.components.player_bar import PlayerBar
from mytunes.ui.components.sleep_timer_dialog import SleepTimerDialog
from mytunes.ui.components.equalizer_dialog import EqualizerDialog
from mytunes.ui.components.quick_mix_dialog import QuickMixDialog
from mytunes.ui.components.lyrics_view import LyricsView
from mytunes.ui.views.music_view import MusicView
from mytunes.ui.views.radio_view import RadioView
from mytunes.ui.views.now_playing_view import NowPlayingView
from mytunes.ui.views.podcasts_view import PodcastsView
from mytunes.ui.views.cloud_view import CloudView
from mytunes.ui.views.playlists_view import PlaylistsView
from mytunes.ui.views.settings_view import SettingsView

from mytunes.ui.dialog_utils import show_snackbar, open_dialog, close_dialog, safe_update

logger = logging.getLogger(__name__)


class XInputController:
    """Polls XInput and DirectInput gamepads and routes their controls to the UI."""

    _CONNECTED_POLL_INTERVAL = 0.05
    _DISCONNECTED_POLL_INTERVAL = 0.25

    # XInput bitmask constants
    DPAD_UP = 0x0001
    DPAD_DOWN = 0x0002
    DPAD_LEFT = 0x0004
    DPAD_RIGHT = 0x0008
    START = 0x0010
    BACK = 0x0020
    LEFT_THUMB = 0x0040
    RIGHT_THUMB = 0x0080
    LEFT_SHOULDER = 0x0100
    RIGHT_SHOULDER = 0x0200
    A = 0x1000
    B = 0x2000
    X = 0x4000
    Y = 0x8000

    def __init__(
        self,
        page: ft.Page,
        pivot_nav,
        player_bar,
        audio_engine,
        queue_manager,
        on_toggle_fullscreen,
        views,
        on_section_change,
        on_back,
        open_queue_modal,
    ):
        self.page = page
        self.pivot_nav = pivot_nav
        self.player_bar = player_bar
        self.audio_engine = audio_engine
        self.queue_manager = queue_manager
        self.on_toggle_fullscreen = on_toggle_fullscreen
        self.views = views
        self.on_section_change = on_section_change
        self.on_back = on_back
        self.open_queue_modal = open_queue_modal

        self.connected = False
        self.controller_mode = False
        self._pressed_buttons = 0
        self._stick_dead_zone = 0.35
        self._axis_repeat_at: dict[str, float] = {}
        self._axis_held_since: dict[str, float] = {}
        self._left_trigger_pressed = False
        self._right_trigger_pressed = False
        self._focus_items: list[dict[str, Any]] = []
        self._focus_index = -1
        self._focus_root: Optional[ft.Control] = None
        self._focused_control: Optional[ft.Control] = None
        self._focused_original: Any = None
        self._now_playing_focus_index = -1
        self._controller_menu_dialog: Optional[ft.AlertDialog] = None
        self._controller_menu_items: list[Any] = []
        self._controller_menu_index = 0
        self.queue_session: Any = None
        self.lyrics_view: Optional[LyricsView] = None
        self.is_lyrics_active: Callable[[], bool] = lambda: False
        self._xinput = self._load_xinput()
        self._dinput_joystick = None
        self._pygame_ready = False

        self.page.run_task(self._poll_loop)

    @staticmethod
    def _load_xinput():
        try:
            return ctypes.windll.xinput1_4
        except Exception:
            try:
                return ctypes.windll.xinput9_1_0
            except Exception:
                return None

    @staticmethod
    def _controller_hints() -> dict[str, str]:
        return {
            "A": "Confirm",
            "B": "Back",
            "X": "More",
            "Y": "Search",
            "LB/RB": "Tabs",
            "D-pad ↑/↓": "Volume",
            "D-pad ←/→": "Tracks",
            "LT/RT": "Seek 10s",
            "Start": "Queue",
            "Back": "Fullscreen",
        }

    def _set_connected(self, connected: bool) -> None:
        if self.connected == connected:
            return
        self.connected = connected
        self._pressed_buttons = 0
        self._left_trigger_pressed = False
        self._right_trigger_pressed = False
        self._axis_repeat_at.clear()
        self._axis_held_since.clear()
        self.player_bar.set_controller_mode(connected)
        hints = self._controller_hints() if connected else {}
        self.player_bar.set_controller_hints(hints)
        if self.views and hasattr(self.views[0], "set_controller_mode"):
            self.views[0].set_controller_mode(connected, hints)
        if hasattr(self.pivot_nav, "set_controller_mode"):
            self.pivot_nav.set_controller_mode(connected)
        self.controller_mode = connected
        if connected:
            self._focus_index = -1
            self._now_playing_focus_index = -1
        self.page.update()
        if not connected:
            self.reset_focus()

    def _exit_controller_mode(self) -> None:
        if self.controller_mode:
            self.controller_mode = False
            self.player_bar.set_controller_mode(False)
            if self.views and hasattr(self.views[0], "set_controller_mode"):
                self.views[0].set_controller_mode(False)
            if hasattr(self.pivot_nav, "set_controller_mode"):
                self.pivot_nav.set_controller_mode(False)
            self.reset_focus()
            self.page.update()

    def _enter_controller_mode(self) -> None:
        if self.connected and not self.controller_mode:
            self.controller_mode = True
            hints = self._controller_hints()
            self.player_bar.set_controller_mode(True)
            self.player_bar.set_controller_hints(hints)
            if self.views and hasattr(self.views[0], "set_controller_mode"):
                self.views[0].set_controller_mode(True, hints)
            if hasattr(self.pivot_nav, "set_controller_mode"):
                self.pivot_nav.set_controller_mode(True)
            self.page.update()

    async def _poll_loop(self):
        while True:
            gamepad_state = self._read_xinput_state()
            if gamepad_state is None:
                gamepad_state = self._read_dinput_state()
            if gamepad_state is None:
                if self.connected:
                    self._set_connected(False)
                await asyncio.sleep(self._DISCONNECTED_POLL_INTERVAL)
                continue

            if not self.connected:
                self._set_connected(True)

            buttons, left_x, left_y, right_x, right_y, left_trigger, right_trigger = gamepad_state
            self._handle_button_state(buttons)
            self._handle_analog(left_x, left_y, right_x, right_y)
            self._handle_triggers(left_trigger, right_trigger)
            await asyncio.sleep(self._CONNECTED_POLL_INTERVAL)

    def _read_xinput_state(self) -> Optional[tuple[int, float, float, float, float, int, int]]:
        if self._xinput is None:
            return None

        class XInputGamepad(ctypes.Structure):
            _fields_ = [
                ("wButtons", ctypes.c_ushort),
                ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short),
                ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short),
            ]

        class XInputState(ctypes.Structure):
            _fields_ = [
                ("dwPacketNumber", ctypes.c_ulong),
                ("Gamepad", XInputGamepad),
            ]

        state = XInputState()
        try:
            result = self._xinput.XInputGetState(0, ctypes.byref(state))
        except Exception:
            logger.exception("Unable to read the XInput controller state")
            return None
        if result != 0:
            return None

        gamepad = state.Gamepad
        return (
            gamepad.wButtons,
            gamepad.sThumbLX / 32767.0,
            -gamepad.sThumbLY / 32767.0,
            gamepad.sThumbRX / 32767.0,
            -gamepad.sThumbRY / 32767.0,
            gamepad.bLeftTrigger,
            gamepad.bRightTrigger,
        )

    def _read_dinput_state(self) -> Optional[tuple[int, float, float, float, float, int, int]]:
        if pygame is None:
            return None
        try:
            if not pygame.display.get_init():
                pygame.display.init()
            if not self._pygame_ready:
                pygame.joystick.init()
                self._pygame_ready = True
            pygame.event.pump()
            if pygame.joystick.get_count() == 0:
                self._dinput_joystick = None
                return None
            if self._dinput_joystick is None or not self._dinput_joystick.get_init():
                self._dinput_joystick = pygame.joystick.Joystick(0)

            joystick = self._dinput_joystick
            button_count = joystick.get_numbuttons()
            axis_count = joystick.get_numaxes()
            buttons = 0
            dinput_button_map = {
                0: self.A,
                1: self.B,
                2: self.X,
                3: self.Y,
                4: self.LEFT_SHOULDER,
                5: self.RIGHT_SHOULDER,
                12: self.DPAD_UP,
                13: self.DPAD_DOWN,
                14: self.DPAD_LEFT,
                15: self.DPAD_RIGHT,
            }
            uses_trigger_buttons = axis_count < 5 and button_count >= 10
            if uses_trigger_buttons:
                dinput_button_map.update({8: self.BACK, 9: self.START})
            else:
                dinput_button_map.update({6: self.BACK, 7: self.START})
            for index, mask in dinput_button_map.items():
                if index < button_count and joystick.get_button(index):
                    buttons |= mask

            if joystick.get_numhats() > 0:
                hat_x, hat_y = joystick.get_hat(0)
                if hat_y > 0:
                    buttons |= self.DPAD_UP
                elif hat_y < 0:
                    buttons |= self.DPAD_DOWN
                if hat_x < 0:
                    buttons |= self.DPAD_LEFT
                elif hat_x > 0:
                    buttons |= self.DPAD_RIGHT

            def axis(index: int) -> float:
                return joystick.get_axis(index) if index < axis_count else 0.0

            left_trigger = right_trigger = 0
            if axis_count >= 6:
                left_trigger = round((axis(4) + 1.0) * 127.5)
                right_trigger = round((axis(5) + 1.0) * 127.5)
            elif axis_count == 5:
                combined_trigger = axis(4)
                left_trigger = round(max(0.0, -combined_trigger) * 255)
                right_trigger = round(max(0.0, combined_trigger) * 255)
            elif uses_trigger_buttons:
                if joystick.get_button(6):
                    left_trigger = 255
                if joystick.get_button(7):
                    right_trigger = 255

            return (
                buttons,
                axis(0),
                axis(1),
                axis(2),
                axis(3),
                left_trigger,
                right_trigger,
            )
        except Exception:
            logger.debug("DirectInput controller polling failed", exc_info=True)
            self._dinput_joystick = None
            return None

    def _handle_button_state(self, buttons: int) -> None:
        diff = buttons & ~self._pressed_buttons
        self._pressed_buttons = buttons
        if diff == 0:
            return
        self._enter_controller_mode()

        if diff & self.A:
            self._activate_selection()
        if diff & self.B:
            self._handle_back()
        if diff & self.X:
            self._show_more_menu()
        if diff & self.Y:
            self._handle_search()
        if diff & self.LEFT_SHOULDER:
            self._handle_prev_tab()
        if diff & self.RIGHT_SHOULDER:
            self._handle_next_tab()
        if diff & self.START:
            self._open_queue()
        if diff & self.BACK:
            self.on_toggle_fullscreen()
        if diff & self.DPAD_UP:
            self._adjust_volume(+0.05)
        if diff & self.DPAD_DOWN:
            self._adjust_volume(-0.05)
        if diff & self.DPAD_LEFT:
            self._change_track(-1)
        if diff & self.DPAD_RIGHT:
            self._change_track(1)

    def _handle_analog(self, left_x: float, left_y: float, right_x: float, right_y: float) -> None:
        if max(abs(left_x), abs(left_y), abs(right_x), abs(right_y)) > self._stick_dead_zone:
            self._enter_controller_mode()
        if self._axis_should_repeat("left_y", left_y):
            self._move_list_selection(-1 if left_y < 0 else 1)
        if self._axis_should_repeat("right_y", right_y):
            self._move_queue_order(-1 if right_y < 0 else 1)
        if self._axis_should_repeat("left_x", left_x):
            self._move_horizontal_selection(-1 if left_x < 0 else 1)

    def _axis_should_repeat(self, axis_name: str, value: float) -> bool:
        now = time.monotonic()
        if abs(value) <= self._stick_dead_zone:
            self._axis_repeat_at.pop(axis_name, None)
            self._axis_held_since.pop(axis_name, None)
            return False
        held_since = self._axis_held_since.setdefault(axis_name, now)
        next_repeat = self._axis_repeat_at.get(axis_name, 0.0)
        if now < next_repeat:
            return False
        held_for = now - held_since
        repeat_interval = max(0.07, 0.22 - held_for * 0.1)
        self._axis_repeat_at[axis_name] = now + repeat_interval
        return True

    def _handle_triggers(self, left_trigger: int, right_trigger: int) -> None:
        left_pressed = left_trigger > 30
        right_pressed = right_trigger > 30
        if left_pressed or right_pressed:
            self._enter_controller_mode()
        if left_pressed and not self._left_trigger_pressed:
            self.audio_engine.seek(max(0.0, self.audio_engine.current_position - 10.0))
        if right_pressed and not self._right_trigger_pressed:
            self.audio_engine.seek(self.audio_engine.current_position + 10.0)
        self._left_trigger_pressed = left_pressed
        self._right_trigger_pressed = right_pressed

    def _handle_back(self) -> None:
        if self._close_controller_menu():
            return
        if self._close_queue_session():
            return
        if self._close_page_dialog():
            return
        self.on_back()

    def _handle_search(self) -> None:
        current_index = self.pivot_nav.active_index
        if not 0 <= current_index < len(self.views):
            return
        search_input = getattr(self.views[current_index], "search_input", None)
        if isinstance(search_input, ft.TextField):
            self.page.run_task(search_input.focus)

    def _handle_prev_tab(self) -> None:
        if self.pivot_nav.active_index > 0:
            self.on_section_change(self.pivot_nav.active_index - 1)

    def _handle_next_tab(self) -> None:
        if self.pivot_nav.active_index < len(self.views) - 1:
            self.on_section_change(self.pivot_nav.active_index + 1)

    def _adjust_volume(self, delta: float) -> None:
        self.audio_engine.set_volume(max(0.0, min(1.0, self.audio_engine.volume + delta)))

    def _move_list_selection(self, direction: int) -> None:
        if self._controller_menu_dialog is not None:
            if self._controller_menu_items:
                self._controller_menu_index = min(
                    len(self._controller_menu_items) - 1,
                    max(0, self._controller_menu_index + direction),
                )
                self._render_controller_menu()
            return

        if self._has_queue_session():
            self._call_session("move_selection", direction)
            return

        if self._lyrics_active():
            lyrics_view = getattr(self, "lyrics_view", None)
            if lyrics_view is not None:
                lyrics_view.move_controller_selection(direction)
            return

        focus_root = self._get_active_page_dialog()
        if focus_root is not None:
            self._sync_focus_root(focus_root)
            self._move_generic_focus(focus_root, direction)
            return

        if self.pivot_nav.active_index == 0:
            self._move_now_playing_focus(direction)
            return

        focus_root = self.views[self.pivot_nav.active_index]
        self._sync_focus_root(focus_root)
        self._move_generic_focus(focus_root, direction)

    def _move_now_playing_focus(self, direction: int) -> None:
        view = self.views[0]
        focusables = view.controller_focusables()
        if not focusables:
            return
        self._now_playing_focus_index = view.move_controller_focus(
            self._now_playing_focus_index,
            direction,
            horizontal=False,
        )
        view.set_controller_focus(self._now_playing_focus_index)

    def _move_horizontal_selection(self, direction: int) -> None:
        if self._lyrics_active() or self._has_queue_session():
            return
        if self.pivot_nav.active_index == 0:
            view = self.views[0]
            focusables = view.controller_focusables()
            if (
                0 <= self._now_playing_focus_index < len(focusables)
                and focusables[self._now_playing_focus_index]
                in (view.progress_slider, view.volume_slider)
            ):
                self._adjust_now_playing_control(direction)
                return
            if not focusables:
                return
            self._now_playing_focus_index = view.move_controller_focus(
                self._now_playing_focus_index,
                direction,
                horizontal=True,
            )
            view.set_controller_focus(self._now_playing_focus_index)
            return
        self._move_list_selection(direction)

    def _move_generic_focus(self, root: ft.Control, direction: int) -> None:
        self._focus_items = self._collect_focus_items(root)
        if not self._focus_items:
            self._clear_focus()
            self._focus_index = -1
            return
        if self._focused_control not in [item["control"] for item in self._focus_items]:
            self._focus_index = 0
        else:
            self._focus_index = min(
                len(self._focus_items) - 1,
                max(0, self._focus_index + direction),
            )
        self._set_focused_control(self._focus_items[self._focus_index]["control"])

    def _move_queue_order(self, direction: int) -> None:
        if self._has_queue_session():
            self._call_session("reorder_selection", direction)

    def _activate_selection(self) -> None:
        if self._controller_menu_dialog is not None:
            self._activate_controller_menu_item(self._controller_menu_index)
            return
        if self._has_queue_session():
            self._call_session("activate")
            return
        if self._lyrics_active():
            lyrics_view = getattr(self, "lyrics_view", None)
            if lyrics_view is not None:
                if lyrics_view.controller_selected_index < 0:
                    lyrics_view.move_controller_selection(1)
                lyrics_view.activate_controller_selection()
            return
        dialog = self._get_active_page_dialog()
        if dialog is not None:
            self._sync_focus_root(dialog)
            self._focus_items = self._collect_focus_items(dialog)
            if self._focus_index < 0 and self._focus_items:
                self._focus_index = 0
                self._set_focused_control(self._focus_items[0]["control"])
            if 0 <= self._focus_index < len(self._focus_items):
                control = self._focus_items[self._focus_index]["control"]
                self._activate_control(control)
                self._focus_active_dialog()
            return
        if self.pivot_nav.active_index == 0:
            view = self.views[0]
            focusables = view.controller_focusables()
            if self._now_playing_focus_index < 0 and focusables:
                self._now_playing_focus_index = 0
                view.set_controller_focus(0)
            if 0 <= self._now_playing_focus_index < len(focusables):
                self._activate_control(focusables[self._now_playing_focus_index])
                self._focus_active_dialog()
                self._focus_after_action(view)
            return

        focus_root = self.views[self.pivot_nav.active_index]
        self._sync_focus_root(focus_root)
        self._focus_items = self._collect_focus_items(focus_root)
        if self._focus_index < 0 and self._focus_items:
            self._focus_index = 0
            self._set_focused_control(self._focus_items[0]["control"])
        if 0 <= self._focus_index < len(self._focus_items):
            self._activate_control(self._focus_items[self._focus_index]["control"])
            self._focus_active_dialog()
            self._focus_after_action(focus_root)

    def _activate_control(self, control: ft.Control) -> None:
        if isinstance(control, ft.TextField):
            self.page.run_task(control.focus)
            return
        if isinstance(control, ft.PopupMenuButton):
            self._open_controller_menu(control)
            return
        self._invoke_callback(getattr(control, "on_click", None))

    def _adjust_now_playing_control(self, direction: int) -> None:
        if self._lyrics_active() or self.pivot_nav.active_index != 0:
            return
        view = self.views[0]
        focusables = view.controller_focusables()
        if not focusables:
            return
        if not 0 <= self._now_playing_focus_index < len(focusables):
            self._move_now_playing_focus(direction)
            return

        selected = focusables[self._now_playing_focus_index]
        if selected is view.progress_slider:
            track = self.queue_manager.current_track
            if track is None or track.duration <= 0:
                return
            position = max(
                0.0,
                min(track.duration, self.audio_engine.current_position + direction * 5.0),
            )
            self.audio_engine.seek(position)
        elif selected is view.volume_slider:
            self._adjust_volume(direction * 0.05)
        else:
            self._move_now_playing_focus(direction)

    def _change_track(self, direction: int) -> None:
        track = self.queue_manager.prev_track() if direction < 0 else self.queue_manager.next_track()
        if track is not None:
            self.audio_engine.play_track(track)

    def _open_queue(self) -> None:
        self.open_queue_modal()
        self._focus_index = -1
        self._clear_focus()

    def _has_queue_session(self) -> bool:
        if self.queue_session is None:
            return False
        if not getattr(self.queue_session, "active", True):
            self.queue_session = None
            return False
        return True

    def _call_session(self, method_name: str, *args: Any) -> None:
        method = getattr(self.queue_session, method_name, None)
        if callable(method):
            method(*args)

    def _close_queue_session(self) -> bool:
        if not self._has_queue_session():
            return False
        self._call_session("close")
        self.queue_session = None
        return True

    def _lyrics_active(self) -> bool:
        return self.is_lyrics_active()

    def _close_page_dialog(self) -> bool:
        dialog = self._get_active_page_dialog()
        if dialog is None:
            return False
        pop_dialog = getattr(self.page, "pop_dialog", None)
        if callable(pop_dialog):
            pop_dialog()
        else:
            close_dialog(self.page, dialog)
        self.reset_focus()
        return True

    def _get_active_page_dialog(self) -> Optional[ft.AlertDialog]:
        overlays = getattr(self.page, "overlay", []) or []
        for overlay in reversed(overlays):
            if isinstance(overlay, ft.AlertDialog) and overlay.open:
                return overlay
        legacy_dialog = getattr(self.page, "dialog", None)
        if isinstance(legacy_dialog, ft.AlertDialog) and legacy_dialog.open:
            return legacy_dialog
        return None

    def _sync_focus_root(self, root: ft.Control) -> None:
        if self._focus_root is root:
            return
        self._clear_focus()
        self._focus_root = root
        self._focus_items = []
        self._focus_index = -1

    def _focus_active_dialog(self) -> None:
        if self._has_queue_session():
            return
        dialog = self._get_active_page_dialog()
        if dialog is None:
            if isinstance(self._focus_root, ft.AlertDialog):
                self._clear_focus()
                self._focus_root = None
                self._focus_items = []
                self._focus_index = -1
            return
        self._sync_focus_root(dialog)
        self._focus_items = self._collect_focus_items(dialog)
        if self._focus_items:
            self._focus_index = 0
            control = self._focus_items[0]["control"]
            self._set_focused_control(control)
            if isinstance(control, ft.TextField):
                self.page.run_task(control.focus)

    def _focus_after_action(self, root: ft.Control) -> None:
        if (
            self._get_active_page_dialog() is not None
            or self._has_queue_session()
            or self._lyrics_active()
            or root is not self.views[self.pivot_nav.active_index]
        ):
            return

        items = self._collect_focus_items(root)
        if self._focused_control not in [item["control"] for item in items]:
            self._clear_focus()
            self._focus_items = items
            self._focus_index = 0 if items else -1
            if items:
                self._set_focused_control(items[0]["control"])
        else:
            self._focus_items = items

    @staticmethod
    def _is_focus_scrollable(control: ft.Control) -> bool:
        return isinstance(control, (ft.ListView, ft.GridView)) or (
            isinstance(control, ft.ScrollableControl)
            and getattr(control, "scroll", None) is not None
        )

    def _collect_focus_items(self, root: ft.Control) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        def visit(
            control: Any,
            parent_item: Optional[dict[str, Any]] = None,
            scrollable: Optional[ft.Control] = None,
        ) -> None:
            if not isinstance(control, ft.Control) or not getattr(control, "visible", True):
                return
            if self._is_focus_scrollable(control):
                scrollable = control
            if isinstance(control, ft.PopupMenuButton):
                if parent_item is not None and control.items:
                    parent_item["menu"] = control
                elif control.items:
                    items.append(
                        {
                            "control": control,
                            "menu": control,
                            "scrollable": scrollable,
                        }
                    )
                return

            current_item = parent_item
            on_click = getattr(control, "on_click", None)
            is_text_field = isinstance(control, ft.TextField)
            if (callable(on_click) or is_text_field) and parent_item is None:
                current_item = {
                    "control": control,
                    "menu": None,
                    "scrollable": scrollable,
                }
                items.append(current_item)

            content = getattr(control, "content", None)
            if isinstance(content, ft.Control):
                visit(content, current_item, scrollable)
            for child in getattr(control, "controls", []) or []:
                visit(child, current_item, scrollable)
            for child in getattr(control, "actions", []) or []:
                visit(child, current_item, scrollable)

        visit(root)
        return items

    def _set_focused_control(self, control: Optional[ft.Control]) -> None:
        if self._focused_control is control:
            return
        self._clear_focus()
        self._focused_control = control
        if isinstance(control, ft.Container):
            self._focused_original = ("border", control.border)
            control.border = ft.Border.all(2, self.player_bar._mt.current_accent)
            safe_update(control)
        elif isinstance(control, ft.IconButton):
            self._focused_original = ("icon_color", control.icon_color)
            control.icon_color = self.player_bar._mt.current_accent
            safe_update(control)
        elif isinstance(control, ft.TextField):
            self._focused_original = ("focused_border_color", control.focused_border_color)
            control.focused_border_color = self.player_bar._mt.current_accent
            safe_update(control)
        if control is not None:
            scrollable = next(
                (
                    item.get("scrollable")
                    for item in self._focus_items
                    if item["control"] is control
                ),
                None,
            )
            self._scroll_focus_into_view(control, scrollable)

    def _scroll_focus_into_view(
        self,
        control: ft.Control,
        scrollable: Optional[ft.Control] = None,
    ) -> None:
        if control.key is None:
            control.key = ft.ScrollKey(f"controller-focus-{id(control)}")
            safe_update(control)

        if scrollable is None:
            parent = control.parent
            while isinstance(parent, ft.Control):
                if self._is_focus_scrollable(parent):
                    scrollable = parent
                    break
                parent = parent.parent
        if scrollable is not None:
            self.page.run_task(
                scrollable.scroll_to,
                scroll_key=str(control.key),
                duration=220,
            )

    def _clear_focus(self) -> None:
        if self._focused_control is None or self._focused_original is None:
            return
        attribute, original = self._focused_original
        setattr(self._focused_control, attribute, original)
        safe_update(self._focused_control)
        self._focused_control = None
        self._focused_original = None

    @staticmethod
    def _invoke_callback(callback: Any) -> None:
        if not callable(callback):
            return
        try:
            signature = inspect.signature(callback)
        except (TypeError, ValueError):
            callback(None)
            return
        required_parameters = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        try:
            callback(None) if required_parameters else callback()
        except Exception:
            logger.exception("Controller action callback failed")

    def _show_more_menu(self) -> None:
        if self._has_queue_session():
            return
        if self._controller_menu_dialog is not None:
            return
        root = self._get_active_page_dialog()
        if root is None and self.pivot_nav.active_index == 0:
            return
        if root is None:
            root = self.views[self.pivot_nav.active_index]
        self._sync_focus_root(root)
        self._focus_items = self._collect_focus_items(root)
        if self._focus_index < 0 and self._focus_items:
            self._focus_index = 0
            self._set_focused_control(self._focus_items[0]["control"])
        if not 0 <= self._focus_index < len(self._focus_items):
            return
        menu = self._focus_items[self._focus_index].get("menu")
        if menu is None:
            return
        self._open_controller_menu(menu)

    def _open_controller_menu(self, menu: ft.PopupMenuButton) -> None:
        self._controller_menu_items = [
            item for item in menu.items if not getattr(item, "disabled", False)
        ]
        if not self._controller_menu_items:
            return
        self._controller_menu_index = 0
        self._controller_menu_dialog = ft.AlertDialog(
            title=ft.Text("More options"),
            content=ft.Column(tight=True, spacing=4),
            actions=[
                ft.TextButton(
                    "Close",
                    on_click=lambda e: self._close_controller_menu(),
                )
            ],
        )
        self._render_controller_menu()
        open_dialog(self.page, self._controller_menu_dialog)

    def _render_controller_menu(self) -> None:
        dialog = self._controller_menu_dialog
        if dialog is None or not isinstance(dialog.content, ft.Column):
            return
        dialog.content.controls = [
            ft.TextButton(
                content=ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.ARROW_RIGHT
                            if index == self._controller_menu_index
                            else ft.Icons.CHEVRON_RIGHT,
                            color=self.player_bar._mt.current_accent,
                        ),
                        ft.Text(self._menu_item_label(item)),
                    ],
                ),
                on_click=lambda e, selected=index: self._activate_controller_menu_item(selected),
            )
            for index, item in enumerate(self._controller_menu_items)
        ]
        safe_update(dialog)

    @staticmethod
    def _menu_item_label(item: Any) -> str:
        content = getattr(item, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, ft.Text):
            return content.value or ""
        if isinstance(content, ft.Control):
            controls = getattr(content, "controls", []) or []
            for control in controls:
                if isinstance(control, ft.Text) and control.value:
                    return control.value
        return str(content or "Option")

    def _activate_controller_menu_item(self, index: int) -> None:
        if not 0 <= index < len(self._controller_menu_items):
            return
        item = self._controller_menu_items[index]
        self._close_controller_menu()
        self._invoke_callback(getattr(item, "on_click", None))
        self._focus_active_dialog()
        if self._focus_root is not None:
            self._focus_after_action(self._focus_root)

    def _close_controller_menu(self) -> bool:
        if self._controller_menu_dialog is None:
            return False
        if self._controller_menu_dialog.open:
            close_dialog(self.page, self._controller_menu_dialog)
        self._controller_menu_dialog = None
        self._controller_menu_items = []
        self._controller_menu_index = 0
        return True

    def reset_focus(self) -> None:
        self._clear_focus()
        self._focus_items = []
        self._focus_index = -1
        self._focus_root = None
        self._now_playing_focus_index = -1
        if self.views and hasattr(self.views[0], "set_controller_focus"):
            self.views[0].set_controller_focus(-1)


class QueueControllerSession:
    def __init__(
        self,
        queue_manager: QueueManager,
        audio_engine: AudioEngine,
        page: ft.Page,
        dialog: ft.AlertDialog,
        queue_list: ft.ReorderableListView,
        refresh_items: Callable[[], None],
        selected_index: int,
    ):
        self.queue_manager = queue_manager
        self.audio_engine = audio_engine
        self.page = page
        self.dialog = dialog
        self.queue_list = queue_list
        self.refresh_items = refresh_items
        self.selected_index = selected_index
        self.active = True

    def move_selection(self, direction: int) -> None:
        if not self.queue_manager.queue:
            return
        self.selected_index = min(
            len(self.queue_manager.queue) - 1,
            max(0, self.selected_index + direction),
        )
        self._refresh()

    def reorder_selection(self, direction: int) -> None:
        target_index = self.selected_index + direction
        if self.queue_manager.reorder_at(self.selected_index, target_index):
            self.selected_index = target_index
            self._refresh()

    def activate(self) -> None:
        track = self.queue_manager.play_at(self.selected_index)
        if track is not None:
            self.audio_engine.play_track(track)
            self._refresh()

    def close(self) -> None:
        if not self.active:
            return
        self.active = False
        close_dialog(self.page, self.dialog)

    def _refresh(self) -> None:
        self.refresh_items()
        safe_update(self.queue_list)
        if self.queue_manager.queue and 0 <= self.selected_index < len(
            self.queue_manager.queue
        ):
            track = self.queue_manager.queue[self.selected_index]
            self.page.run_task(
                self.queue_list.scroll_to,
                scroll_key=f"queue-item-{self.selected_index}-{track.id}",
                duration=220,
            )


def main(page: ft.Page) -> None:
    page.title = "MyTunes"
    if page.window is not None:
        page.window.width = 1100
        page.window.height = 720
        page.window.min_width = 850
        page.window.min_height = 600

    page.padding = 0
    page.spacing = 0

    # 1. Initialize Database & Backend
    db_conn = init_db()
    local_provider = LocalProvider(db_conn)
    sync_manager = SyncManager(db_conn)
    playback_session = PlaybackSessionStore(db_conn)
    saved_session = playback_session.load(local_provider.get_all_tracks())

    # 2. Theme & Design
    theme = MetroTheme(is_dark=True, default_accent="#0078D7")
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = theme.bg_color

    # 3. Queue & Audio Engine
    queue_manager = QueueManager()
    if saved_session and saved_session.tracks:
        queue_manager.set_queue(saved_session.tracks, saved_session.current_index)
        if saved_session.current_index < 0:
            queue_manager.current_index = -1
    audio_engine = AudioEngine(page, queue_manager)
    if saved_session:
        audio_engine.set_volume(saved_session.volume)
        audio_engine.is_muted = saved_session.is_muted
        if audio_engine.audio and saved_session.is_muted:
            audio_engine.audio.volume = 0.0

    def persist_playback_session(force_position: bool = False) -> None:
        playback_session.save(
            queue_manager,
            audio_engine.current_position,
            audio_engine.volume,
            audio_engine.is_muted,
            force_position=force_position,
        )

    queue_manager.on_queue_changed = persist_playback_session
    if saved_session is None:
        persist_playback_session(force_position=True)
    media_controls = create_media_controls(page, audio_engine, queue_manager)

    def close_app(_event) -> None:
        persist_playback_session(force_position=True)
        media_controls.close()

    page.on_close = close_app

    # 4. Dialogs & Overlays
    sleep_dialog = SleepTimerDialog(page, audio_engine)
    eq_dialog = EqualizerDialog(page)

    # 5. Lyrics View (Toggleable)
    lyrics_view = LyricsView(page, audio_engine.seek)
    lyrics_active = False
    artist_metadata = ArtistMetadataProvider(db_conn=db_conn)

    def play_previous_track() -> None:
        previous_track = queue_manager.prev_track()
        if previous_track:
            audio_engine.play_track(previous_track)

    def play_next_track() -> None:
        next_track = queue_manager.next_track()
        if next_track:
            audio_engine.play_track(next_track)

    now_playing_view = NowPlayingView(
        page,
        theme,
        artist_metadata,
        audio_engine.toggle_play_pause,
        play_previous_track,
        play_next_track,
        audio_engine.seek,
        on_favorite=lambda: player_bar._toggle_favorite(None),
        on_mix=lambda: open_quick_mix(),
        on_repeat=lambda: (
            player_bar._toggle_repeat(None),
            queue_manager.repeat_mode,
        )[1],
        on_repeat_mode=lambda: queue_manager.repeat_mode,
        on_lyrics=lambda: toggle_lyrics(),
        on_speed=lambda: (
            player_bar._cycle_playback_speed(None),
            player_bar.speed_label.value,
        )[1],
        on_eq=lambda: eq_dialog.show(),
        on_sleep=lambda: sleep_dialog.show(),
        on_queue=lambda: open_queue_modal(),
        on_volume_change=audio_engine.set_volume,
        on_mute=lambda: (
            player_bar._toggle_mute(None),
            audio_engine.is_muted,
        )[1],
        on_artist_click=lambda artist: open_artist_in_music(artist),
        on_album_click=lambda album, artist: open_album_in_music(album, artist),
    )

    # Forward declaration for UI callbacks
    def on_track_changed(track: Track | None) -> None:
        player_bar.update_track(track, update_ui=False)
        now_playing_view.update_track(track, update_ui=False)
        media_controls.update_track(track)
        if track and lyrics_active:
            lyrics_view.load_for_track(track)
        if pivot_nav is not None and pivot_nav.active_index == 0:
            safe_update(now_playing_view)
        else:
            safe_update(player_bar)

    queue_manager.on_track_changed = on_track_changed

    def on_playback_state_changed(is_playing: bool) -> None:
        if pivot_nav is not None and pivot_nav.active_index == 0:
            now_playing_view.update_playback_state(is_playing)
        else:
            player_bar.update_playback_state(is_playing)
        media_controls.update_playback_state(is_playing)

    def on_position_changed(current: float, total: float) -> None:
        if pivot_nav is not None and pivot_nav.active_index == 0:
            now_playing_view.update_position(current, total)
        else:
            player_bar.update_position(current, total)
        media_controls.update_position(current, total)
        persist_playback_session()
        if lyrics_active:
            lyrics_view.update_position(current)

    def on_volume_changed(volume: float) -> None:
        media_controls.update_volume(volume)
        if pivot_nav is not None and pivot_nav.active_index == 0:
            now_playing_view.update_volume(audio_engine.volume, audio_engine.is_muted)
        player_bar.volume_slider.value = audio_engine.volume
        player_bar.btn_volume.icon = (
            ft.Icons.VOLUME_OFF
            if audio_engine.is_muted
            else ft.Icons.VOLUME_MUTE
            if audio_engine.volume == 0
            else ft.Icons.VOLUME_DOWN
            if audio_engine.volume < 0.5
            else ft.Icons.VOLUME_UP
        )
        if pivot_nav is None or pivot_nav.active_index != 0:
            safe_update(player_bar)
        persist_playback_session()

    def on_seeked(_position: float) -> None:
        persist_playback_session(force_position=True)

    audio_engine.on_state_changed = on_playback_state_changed
    audio_engine.on_stopped = media_controls.update_playback_stopped
    audio_engine.on_volume_changed = on_volume_changed
    audio_engine.on_position_changed = on_position_changed
    audio_engine.on_seeked = on_seeked

    audio_engine.on_sleep_triggered = lambda: (
        show_snackbar(page, "Sleep Timer expired: Playback stopped.")
    )

    # Playback handlers
    def play_track(track: Track, current_list: list[Track]) -> None:
        try:
            idx = current_list.index(track)
        except ValueError:
            idx = 0
        queue_manager.set_queue(current_list, start_index=idx)
        audio_engine.play_track(track)

    def play_next(track: Track) -> None:
        queue_manager.play_next(track)
        show_snackbar(page, f"Playing next: {track.title}")

    def add_to_queue(track: Track) -> None:
        queue_manager.add_to_queue(track)
        show_snackbar(page, f"Added to queue: {track.title}")

    def play_radio_station(station: RadioStation) -> None:
        stream_track = Track(
            id=f"radio_{station.id}",
            title=station.name,
            artist=f"Radio ({station.country or 'Global'})",
            album=station.tags or "Online Stream",
            file_path=station.stream_url,
            source="stream",
            artwork_url=station.favicon
        )
        queue_manager.set_queue([stream_track], 0)
        audio_engine.play_track(stream_track)

    def play_podcast_episode(episode: Episode, show: PodcastShow) -> None:
        downloaded_path = (
            episode.download_path
            if episode.download_path and os.path.isfile(episode.download_path)
            else None
        )
        podcast_track = Track(
            id=f"pod_{episode.id}",
            title=episode.title,
            artist=show.author or show.title,
            album=show.title,
            duration=episode.duration,
            file_path=downloaded_path or episode.audio_url,
            source="local" if downloaded_path else "stream",
            artwork_url=show.artwork_url
        )
        queue_manager.set_queue([podcast_track], 0)
        audio_engine.play_track(podcast_track)

    def on_mix_generated(mix_tracks: list[Track], mix_name: str) -> None:
        if mix_tracks:
            queue_manager.set_queue(mix_tracks, 0)
            audio_engine.play_track(mix_tracks[0])
            show_snackbar(page, f"Playing {mix_name}")

    def toggle_lyrics() -> None:
        nonlocal lyrics_active
        lyrics_active = not lyrics_active
        if lyrics_active:
            content_container.content = ft.Column(
                expand=True,
                spacing=0,
                controls=[
                    ft.Row(
                        controls=[
                            ft.TextButton(
                                "Back",
                                icon=ft.Icons.ARROW_BACK,
                                on_click=lambda e: toggle_lyrics(),
                            )
                        ],
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    lyrics_view,
                ],
            )
            if queue_manager.current_track:
                lyrics_view.load_for_track(queue_manager.current_track)
        else:
            if pivot_nav is not None:
                content_container.content = views[pivot_nav.active_index]
        page.update(pivot_nav, content_container, player_bar)

    def open_quick_mix() -> None:
        all_library_tracks = local_provider.get_all_tracks()
        mix_dlg = QuickMixDialog(page, all_library_tracks, on_mix_generated)
        mix_dlg.show()

    queue_modal_session: Optional[QueueControllerSession] = None
    controller_manager: Optional[XInputController] = None

    def open_queue_modal() -> None:
        nonlocal queue_modal_session, controller_manager
        if queue_modal_session is not None and queue_modal_session.active:
            if controller_manager is not None:
                controller_manager.queue_session = queue_modal_session
            return

        q_list = ft.ReorderableListView(
            expand=True,
            spacing=4,
            show_default_drag_handles=False,
        )
        session: Optional[QueueControllerSession] = None

        def refresh_queue_items() -> None:
            q_list.controls = []
            for index, track in enumerate(queue_manager.queue):
                is_current = index == queue_manager.current_index
                is_selected = session is not None and index == session.selected_index
                q_list.controls.append(
                    ft.Container(
                        key=f"queue-item-{index}-{track.id}",
                        padding=8,
                        bgcolor=(
                            ft.Colors.with_opacity(0.25, theme.current_accent)
                            if is_selected
                            else theme.surface_variant
                            if is_current
                            else ft.Colors.TRANSPARENT
                        ),
                        border=(
                            ft.Border.all(1, theme.current_accent)
                            if is_selected
                            else None
                        ),
                        ink=True,
                        on_click=lambda e, item_index=index: play_queue_item(item_index),
                        content=ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.PLAY_ARROW
                                    if is_current
                                    else ft.Icons.MUSIC_NOTE,
                                    size=16,
                                    color=(
                                        theme.current_accent
                                        if is_current
                                        else ft.Colors.GREY_500
                                    ),
                                ),
                                ft.Text(
                                    track.title,
                                    size=13,
                                    weight=(
                                        ft.FontWeight.BOLD
                                        if is_current
                                        else ft.FontWeight.W_400
                                    ),
                                    expand=True,
                                    no_wrap=True,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.Text(
                                    track.artist,
                                    size=12,
                                    color=theme.text_secondary,
                                    width=110,
                                    no_wrap=True,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.ReorderableDragHandle(
                                    content=ft.Container(
                                        width=28,
                                        height=32,
                                        alignment=ft.Alignment(0, 0),
                                        content=ft.Icon(
                                            ft.Icons.DRAG_HANDLE,
                                            size=20,
                                            color=ft.Colors.GREY_500,
                                        ),
                                    ),
                                    mouse_cursor=ft.MouseCursor.GRAB,
                                ),
                            ],
                            spacing=8,
                        ),
                    )
                )

        def play_queue_item(index: int) -> None:
            if session is not None:
                session.selected_index = index
                session.activate()

        def reorder_queue(event: ft.OnReorderEvent) -> None:
            if event.old_index is None or event.new_index is None:
                return
            if queue_manager.reorder_at(event.old_index, event.new_index):
                if session is not None:
                    session.selected_index = event.new_index
                refresh_queue_items()
                safe_update(q_list)

        q_list.on_reorder = reorder_queue

        q_dlg = ft.AlertDialog(
            title=ft.Text("Up Next / Queue", weight=ft.FontWeight.BOLD),
            content=ft.Container(width=400, height=350, content=q_list),
            actions=[
                ft.TextButton(
                    "Close",
                    on_click=lambda e: session.close() if session is not None else None,
                )
            ]
        )
        selected_index = queue_manager.current_index
        if selected_index < 0 and queue_manager.queue:
            selected_index = 0
        session = QueueControllerSession(
            queue_manager,
            audio_engine,
            page,
            q_dlg,
            q_list,
            refresh_queue_items,
            selected_index,
        )
        refresh_queue_items()
        open_dialog(page, q_dlg)
        queue_modal_session = session
        if controller_manager is not None:
            controller_manager.queue_session = session

    def refresh_theme() -> None:
        page.bgcolor = theme.bg_color
        if pivot_nav is not None:
            pivot_nav._build_nav()
        player_bar._build_layout()
        page.update()

    fullscreen_enabled = False

    def toggle_fullscreen() -> None:
        nonlocal fullscreen_enabled
        try:
            window = page.window
            if window is None:
                logger.error("The current Flet window does not support fullscreen mode")
                return
            fullscreen_enabled = not fullscreen_enabled
            window.full_screen = fullscreen_enabled
            window.frameless = fullscreen_enabled
            if pivot_nav is not None:
                pivot_nav.set_fullscreen(fullscreen_enabled)
        except Exception:
            logger.exception("Unable to toggle the borderless fullscreen window")
            show_snackbar(page, "Could not toggle fullscreen mode")
            return
        page.update()

    # 6. Instantiate Views
    view_music = MusicView(page, local_provider, theme, play_track, play_next, add_to_queue)
    cloud_settings = CloudView(page, theme, sync_manager, embedded=True)
    view_podcasts = PodcastsView(
        page,
        db_conn,
        theme,
        play_podcast_episode,
        play_next,
        add_to_queue,
    )
    view_radio = RadioView(page, theme, play_radio_station, db_conn=db_conn)
    view_playlists = PlaylistsView(page, db_conn, theme, play_track, play_next)
    view_settings = SettingsView(
        page,
        theme,
        refresh_theme,
        db_conn,
        local_provider,
        view_music.load_tracks,
        cloud_settings,
    )

    views = [
        now_playing_view,
        view_music,
        view_podcasts,
        view_radio,
        view_playlists,
        view_settings,
    ]

    pivot_nav: Optional[PivotNav] = None
    content_container = ft.Container(content=views[1], expand=True)

    def on_section_change(index: int) -> None:
        nonlocal lyrics_active
        if not 0 <= index < len(views):
            return
        lyrics_active = False
        if pivot_nav is not None and pivot_nav.active_index != index:
            pivot_nav.set_active_index(index, update=False)
        if controller_manager is not None:
            controller_manager.reset_focus()
        content_container.content = views[index]
        player_bar.visible = index != 0
        if index == 3:
            view_radio.ensure_featured_loaded()
        if index == 4:
            view_playlists.ensure_loaded()
        if index == 0:
            now_playing_view.update_playback_state(audio_engine.is_playing)
            now_playing_view.update_position(
                audio_engine.current_position,
                audio_engine.total_duration,
            )
            now_playing_view.update_volume(
                audio_engine.volume,
                audio_engine.is_muted,
            )
        else:
            player_bar.update_playback_state(audio_engine.is_playing)
            player_bar.update_position(
                audio_engine.current_position,
                audio_engine.total_duration,
            )
        page.update(pivot_nav, content_container, player_bar)

    def controller_back() -> None:
        if lyrics_active:
            if lyrics_view.auto_follow:
                toggle_lyrics()
            else:
                lyrics_view._resume_auto_scroll()
            return
        current_index = pivot_nav.active_index if pivot_nav is not None else 0
        if current_index == 1 and view_music.controller_back():
            return
        if current_index == 2 and view_podcasts._current_screen != "subscriptions":
            view_podcasts._navigate_back()
            return
        if current_index == 3 and view_radio.current_tab == "favorites":
            view_radio._switch_tab("explore")
            return
        on_section_change(1 if current_index == 0 else 0)

    # 7. Metro Pivot Navigation Header
    pivot_nav = PivotNav(
        sections=[
            "Now Playing",
            "Music",
            "Podcasts",
            "Radio",
            "Playlists",
            "Settings",
        ],
        active_index=1,
        theme=theme,
        on_section_change=on_section_change
    )
    pivot_nav.fullscreen_button.on_click = lambda e: toggle_fullscreen()

    def open_artist_in_music(artist_name: str) -> None:
        on_section_change(1)
        view_music._open_artist_page(artist_name)

    def open_album_in_music(album_name: str, album_artist: str) -> None:
        on_section_change(1)
        view_music._open_album_page(album_name, album_artist)

    # 8. Player Bar
    player_bar = PlayerBar(
        page=page,
        audio_engine=audio_engine,
        queue_manager=queue_manager,
        theme=theme,
        on_lyrics_click=toggle_lyrics,
        on_eq_click=lambda: eq_dialog.show(),
        on_sleep_click=lambda: sleep_dialog.show(),
        on_mix_click=open_quick_mix,
        on_queue_click=open_queue_modal,
        on_artist_click=open_artist_in_music,
        on_album_click=open_album_in_music,
        db_conn=db_conn,
    )
    if saved_session:
        player_bar.volume_slider.value = saved_session.volume
        now_playing_view.update_volume(
            saved_session.volume,
            saved_session.is_muted,
        )
        player_bar.btn_volume.icon = (
            ft.Icons.VOLUME_OFF
            if saved_session.is_muted
            else ft.Icons.VOLUME_MUTE
            if saved_session.volume == 0
            else ft.Icons.VOLUME_DOWN
            if saved_session.volume < 0.5
            else ft.Icons.VOLUME_UP
        )

    controller_manager = XInputController(
        page,
        pivot_nav,
        player_bar,
        audio_engine,
        queue_manager,
        toggle_fullscreen,
        views,
        on_section_change,
        controller_back,
        open_queue_modal,
    )
    controller_manager.lyrics_view = lyrics_view
    controller_manager.is_lyrics_active = lambda: lyrics_active

    # 9. Main Layout
    page.add(
        ft.GestureDetector(
            expand=True,
            on_hover=lambda e: (
                controller_manager._exit_controller_mode()
                if controller_manager is not None
                else None
            ),
            on_scroll=lambda e: (
                controller_manager._exit_controller_mode()
                if controller_manager is not None
                else None
            ),
            content=ft.Column(
                expand=True,
                spacing=0,
                controls=[
                    pivot_nav,
                    content_container,
                    player_bar
                ]
            ),
        )
    )
    if saved_session:
        restored_track = queue_manager.current_track
        player_bar.update_track(restored_track)
        now_playing_view.update_track(restored_track)
        media_controls.update_track(restored_track)
        if restored_track:
            audio_engine.restore_paused_track(
                restored_track,
                saved_session.position_seconds,
            )
        player_bar.update_playback_state(False)
        now_playing_view.update_playback_state(False)

if __name__ == "__main__":
    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)
