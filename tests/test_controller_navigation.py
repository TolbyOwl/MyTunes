import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import flet as ft

from mytunes.core.queue import QueueManager
from mytunes.main import QueueControllerSession, XInputController
from mytunes.models.track import Track
from mytunes.ui.components.pivot_nav import PivotNav
from mytunes.ui.theme import MetroTheme


class TestControllerNavigation(unittest.TestCase):
    def make_controller(self, controls=None):
        controller = XInputController.__new__(XInputController)
        controller.page = Mock()
        controller.page.overlay = []
        controller.page.dialog = None
        controller.player_bar = SimpleNamespace(
            _mt=SimpleNamespace(current_accent="#0078D7"),
        )
        controller.pivot_nav = SimpleNamespace(active_index=1)
        controller.views = [None, ft.Column(controls=controls or [])]
        controller.queue_session = None
        controller._controller_menu_dialog = None
        controller._controller_menu_items = []
        controller._controller_menu_index = 0
        controller._focus_items = []
        controller._focus_index = -1
        controller._focus_root = None
        controller._focused_control = None
        controller._focused_original = None
        controller._now_playing_focus_index = -1
        controller._pressed_buttons = 0
        controller._axis_repeat_at = {}
        controller._axis_held_since = {}
        controller._stick_dead_zone = 0.35
        controller._poll_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="test-gamepad",
        )
        self.addCleanup(
            controller._poll_executor.shutdown,
            wait=True,
            cancel_futures=True,
        )
        controller._left_trigger_pressed = False
        controller._right_trigger_pressed = False
        controller.connected = False
        controller.controller_mode = False
        controller.audio_engine = SimpleNamespace(current_position=20.0)
        controller.is_lyrics_active = lambda: False
        controller.lyrics_view = None
        controller.on_back = Mock()
        return controller

    def test_left_stick_selects_each_clickable_item_and_a_activates_it(self):
        selected = []
        controls = [
            ft.Container(on_click=lambda e: selected.append("first")),
            ft.Container(on_click=lambda e: selected.append("second")),
        ]
        controller = self.make_controller(controls)

        controller._move_list_selection(1)
        controller._move_list_selection(1)
        controller._activate_selection()

        self.assertEqual(controller._focus_index, 1)
        self.assertEqual(selected, ["second"])

    def test_horizontal_left_stick_moves_now_playing_focus(self):
        first = ft.IconButton(icon=ft.Icons.PLAY_ARROW)
        second = ft.IconButton(icon=ft.Icons.SKIP_NEXT)
        now_playing = SimpleNamespace(
            progress_slider=ft.Slider(),
            volume_slider=ft.Slider(),
            controller_focusables=lambda: [first, second],
            move_controller_focus=Mock(return_value=1),
            set_controller_focus=Mock(),
        )
        controller = self.make_controller()
        controller.pivot_nav.active_index = 0
        controller.views[0] = now_playing
        controller._now_playing_focus_index = 0

        controller._handle_analog(0.9, 0.0, 0.0, 0.0)

        self.assertEqual(controller._now_playing_focus_index, 1)
        now_playing.set_controller_focus.assert_called_once_with(1)

    def test_horizontal_left_stick_moves_selection_in_other_tabs(self):
        first = ft.Container(on_click=lambda e: None)
        second = ft.Container(on_click=lambda e: None)
        controller = self.make_controller([first, second])

        controller._handle_analog(0.9, 0.0, 0.0, 0.0)

        self.assertIs(controller._focused_control, first)
        controller._handle_analog(0.0, 0.0, 0.0, 0.0)
        controller._handle_analog(0.9, 0.0, 0.0, 0.0)
        self.assertIs(controller._focused_control, second)

    def test_horizontal_left_stick_adjusts_selected_now_playing_sliders(self):
        progress = ft.Slider()
        volume = ft.Slider()
        now_playing = SimpleNamespace(
            progress_slider=progress,
            volume_slider=volume,
            controller_focusables=lambda: [progress, volume],
            move_controller_focus=Mock(return_value=1),
            set_controller_focus=Mock(),
        )
        controller = self.make_controller()
        controller.pivot_nav.active_index = 0
        controller.views[0] = now_playing
        controller.queue_manager = SimpleNamespace(
            current_track=Track(id="track", title="Song", duration=120)
        )
        controller.audio_engine.seek = Mock()
        controller.audio_engine.current_position = 20.0
        controller._now_playing_focus_index = 0

        controller._handle_analog(0.9, 0.0, 0.0, 0.0)
        self.assertEqual(controller.audio_engine.seek.call_args.args[0], 25.0)

        controller._axis_repeat_at.clear()
        controller._now_playing_focus_index = 1
        controller._adjust_volume = Mock()
        controller._handle_analog(-0.9, 0.0, 0.0, 0.0)
        controller._adjust_volume.assert_called_once_with(-0.05)

    def test_focus_scrolls_target_using_scrollable_ancestor(self):
        first = ft.Container(on_click=lambda e: None)
        second = ft.Container(on_click=lambda e: None)
        scrollable = ft.Column(
            controls=[first, second],
            scroll=ft.ScrollMode.AUTO,
        )
        root = ft.Container(content=scrollable)
        controller = self.make_controller()

        controller._sync_focus_root(root)
        controller._move_generic_focus(root, 1)
        target_key = first.key
        controller._move_generic_focus(root, 1)

        self.assertIs(controller._focused_control, second)
        controller.page.run_task.assert_called_with(
            scrollable.scroll_to,
            scroll_key=str(second.key),
            duration=220,
        )
        self.assertIsNotNone(target_key)

    def test_focus_scrolls_default_list_views_without_explicit_scroll_mode(self):
        item = ft.Container(on_click=lambda e: None)
        scrollable = ft.ListView(controls=[item])
        controller = self.make_controller()

        controller._sync_focus_root(scrollable)
        controller._move_generic_focus(scrollable, 1)

        controller.page.run_task.assert_called_once_with(
            scrollable.scroll_to,
            scroll_key=str(item.key),
            duration=220,
        )

    def test_held_analog_repeats_accelerate_progressively(self):
        controller = self.make_controller()
        times = iter([0.0, 0.21, 0.22, 1.65, 1.70, 1.72])

        with patch("mytunes.main.time.monotonic", side_effect=lambda: next(times)):
            results = [
                controller._axis_should_repeat("left_y", 0.9),
                controller._axis_should_repeat("left_y", 0.9),
                controller._axis_should_repeat("left_y", 0.9),
                controller._axis_should_repeat("left_y", 0.9),
                controller._axis_should_repeat("left_y", 0.9),
                controller._axis_should_repeat("left_y", 0.9),
            ]

        self.assertEqual(results, [True, False, True, True, False, True])
        with patch("mytunes.main.time.monotonic", return_value=1.73):
            self.assertFalse(controller._axis_should_repeat("left_y", 0.0))
        self.assertNotIn("left_y", controller._axis_held_since)

    def test_disconnected_controller_polling_uses_lower_frequency(self):
        controller = self.make_controller()
        controller._read_xinput_state = Mock(return_value=None)
        controller._read_dinput_state = Mock(return_value=None)
        sleep = Mock(side_effect=asyncio.CancelledError)

        async def run_once():
            with patch("mytunes.main.asyncio.sleep", sleep):
                with self.assertRaises(asyncio.CancelledError):
                    await controller._poll_loop()

        asyncio.run(run_once())

        sleep.assert_called_once_with(0.25)

    def test_connected_controller_keeps_responsive_poll_frequency(self):
        controller = self.make_controller()
        controller.connected = True
        controller._read_xinput_state = Mock(return_value=(0, 0, 0, 0, 0, 0, 0))
        controller._read_dinput_state = Mock()
        sleep = Mock(side_effect=asyncio.CancelledError)

        async def run_once():
            with patch("mytunes.main.asyncio.sleep", sleep):
                with self.assertRaises(asyncio.CancelledError):
                    await controller._poll_loop()

        asyncio.run(run_once())

        controller._read_dinput_state.assert_not_called()
        sleep.assert_called_once_with(0.05)

    def test_gamepad_reads_run_off_the_page_event_loop(self):
        controller = self.make_controller()
        event_loop_thread = None
        reader_threads = []
        controller._read_controller_state = lambda: (
            reader_threads.append(threading.get_ident()) or None
        )
        sleep = Mock(side_effect=asyncio.CancelledError)

        async def run_once():
            nonlocal event_loop_thread
            event_loop_thread = threading.get_ident()
            with patch("mytunes.main.asyncio.sleep", sleep):
                with self.assertRaises(asyncio.CancelledError):
                    await controller._poll_loop()

        asyncio.run(run_once())

        self.assertEqual(len(reader_threads), 1)
        self.assertNotEqual(reader_threads[0], event_loop_thread)
        sleep.assert_called_once_with(0.25)

    def test_gamepad_state_prefers_xinput_then_falls_back_to_dinput(self):
        controller = self.make_controller()
        xinput_state = (1, 0.0, 0.0, 0.0, 0.0, 0, 0)
        controller._read_xinput_state = Mock(return_value=xinput_state)
        controller._read_dinput_state = Mock()

        self.assertEqual(controller._read_controller_state(), xinput_state)
        controller._read_dinput_state.assert_not_called()

        controller._read_xinput_state.return_value = None
        dinput_state = (2, 0.1, 0.2, 0.3, 0.4, 5, 6)
        controller._read_dinput_state.return_value = dinput_state

        self.assertEqual(controller._read_controller_state(), dinput_state)
        controller._read_dinput_state.assert_called_once_with()

    def test_header_shows_shoulder_badges_in_controller_mode(self):
        nav = PivotNav(
            sections=["Now Playing", "Music"],
            active_index=0,
            theme=MetroTheme(),
            on_section_change=Mock(),
        )
        nav.set_controller_mode(True)

        self.assertTrue(nav.left_shoulder_hint.visible)
        self.assertTrue(nav.right_shoulder_hint.visible)
        self.assertEqual(nav.left_shoulder_hint.content.value, "LB")
        self.assertEqual(nav.right_shoulder_hint.content.value, "RB")

        nav.set_controller_mode(False)
        self.assertFalse(nav.left_shoulder_hint.visible)
        self.assertFalse(nav.right_shoulder_hint.visible)

    def test_header_click_batches_style_change_with_section_update(self):
        on_section_change = Mock()
        nav = PivotNav(
            sections=["Now Playing", "Music"],
            active_index=0,
            theme=MetroTheme(),
            on_section_change=on_section_change,
        )

        with patch("mytunes.ui.components.pivot_nav.safe_update") as update:
            nav._on_item_click(1)

        self.assertEqual(nav.active_index, 1)
        on_section_change.assert_called_once_with(1)
        update.assert_not_called()

    def test_x_button_opens_and_activates_selected_song_menu(self):
        selected = []
        menu = ft.PopupMenuButton(
            items=[
                ft.PopupMenuItem(
                    content="Add to queue",
                    on_click=lambda e: selected.append("queued"),
                )
            ]
        )
        row = ft.Container(
            on_click=lambda e: None,
            content=ft.Row(controls=[menu]),
        )
        controller = self.make_controller()
        controller.views[1] = ft.Column(controls=[row])
        controller._handle_button_state(controller.X)

        self.assertIsNotNone(controller._controller_menu_dialog)
        self.assertEqual(len(controller._controller_menu_items), 1)
        controller._activate_controller_menu_item(0)

        self.assertEqual(selected, ["queued"])
        self.assertIsNone(controller._controller_menu_dialog)

    def test_controller_buttons_route_to_their_documented_actions(self):
        controller = self.make_controller()
        controller._activate_selection = Mock()
        controller._handle_back = Mock()
        controller._show_more_menu = Mock()
        controller._handle_search = Mock()
        controller._handle_prev_tab = Mock()
        controller._handle_next_tab = Mock()
        controller._open_queue = Mock()
        controller.on_toggle_fullscreen = Mock()
        controller._adjust_volume = Mock()
        controller._change_track = Mock()
        buttons = (
            controller.A
            | controller.B
            | controller.X
            | controller.Y
            | controller.LEFT_SHOULDER
            | controller.RIGHT_SHOULDER
            | controller.START
            | controller.BACK
            | controller.DPAD_UP
            | controller.DPAD_DOWN
            | controller.DPAD_LEFT
            | controller.DPAD_RIGHT
        )

        controller._handle_button_state(buttons)

        controller._activate_selection.assert_called_once_with()
        controller._handle_back.assert_called_once_with()
        controller._show_more_menu.assert_called_once_with()
        controller._handle_search.assert_called_once_with()
        controller._handle_prev_tab.assert_called_once_with()
        controller._handle_next_tab.assert_called_once_with()
        controller._open_queue.assert_called_once_with()
        controller.on_toggle_fullscreen.assert_called_once_with()
        self.assertEqual(
            [call.args[0] for call in controller._adjust_volume.call_args_list],
            [0.05, -0.05],
        )
        self.assertEqual(
            [call.args[0] for call in controller._change_track.call_args_list],
            [-1, 1],
        )

    def test_queue_left_stick_selects_and_right_stick_reorders(self):
        controller = self.make_controller()
        session = SimpleNamespace(
            active=True,
            move_selection=Mock(),
            reorder_selection=Mock(),
        )
        controller.queue_session = session

        controller._move_list_selection(1)
        controller._move_queue_order(-1)

        session.move_selection.assert_called_once_with(1)
        session.reorder_selection.assert_called_once_with(-1)

    def test_y_button_focuses_search_field_as_an_async_page_task(self):
        controller = self.make_controller()
        search = ft.TextField()
        controller.views[1] = SimpleNamespace(search_input=search)

        controller._handle_search()

        controller.page.run_task.assert_called_once_with(search.focus)

    def test_modal_open_after_selection_receives_controller_focus(self):
        selected = []
        dialog = ft.AlertDialog(
            open=True,
            actions=[
                ft.TextButton(
                    "Confirm",
                    on_click=lambda e: selected.append("dialog"),
                )
            ],
        )
        controller = self.make_controller(
            [ft.Container(on_click=lambda e: selected.append("background"))]
        )
        controller.page.overlay = [dialog]

        controller._move_list_selection(1)
        controller._activate_selection()

        self.assertIs(controller._focus_root, dialog)
        self.assertEqual(selected, ["dialog"])

    def test_triggers_seek_ten_seconds_once_per_press(self):
        controller = self.make_controller()
        controller.audio_engine.seek = Mock()

        controller._handle_triggers(255, 0)
        controller._handle_triggers(255, 0)
        controller._handle_triggers(0, 0)
        controller._handle_triggers(0, 255)

        self.assertEqual(
            [call.args[0] for call in controller.audio_engine.seek.call_args_list],
            [10.0, 30.0],
        )

    def test_directinput_fallback_normalizes_buttons_axes_and_trigger_buttons(self):
        controller = self.make_controller()

        class FakeJoystick:
            def get_init(self):
                return True

            def get_numbuttons(self):
                return 16

            def get_numaxes(self):
                return 4

            def get_button(self, index):
                return index in {0, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 15}

            def get_numhats(self):
                return 0

            def get_axis(self, index):
                return [0.2, 0.4, -0.3, -0.6][index]

        joystick = FakeJoystick()
        pygame_stub = SimpleNamespace(
            display=SimpleNamespace(get_init=lambda: True),
            event=SimpleNamespace(pump=lambda: None),
            joystick=SimpleNamespace(
                get_count=lambda: 1,
                Joystick=lambda index: joystick,
            ),
        )
        controller._pygame_ready = True
        controller._dinput_joystick = joystick

        with patch("mytunes.main.pygame", pygame_stub):
            state = controller._read_dinput_state()

        self.assertIsNotNone(state)
        assert state is not None
        buttons, left_x, left_y, right_x, right_y, left_trigger, right_trigger = state
        self.assertEqual(
            buttons,
            controller.A
            | controller.X
            | controller.Y
            | controller.LEFT_SHOULDER
            | controller.RIGHT_SHOULDER
            | controller.DPAD_UP
            | controller.DPAD_DOWN
            | controller.DPAD_LEFT
            | controller.DPAD_RIGHT
            | controller.BACK
            | controller.START,
        )
        self.assertEqual((left_x, left_y, right_x, right_y), (0.2, 0.4, -0.3, -0.6))
        self.assertEqual((left_trigger, right_trigger), (255, 255))

    def test_queue_session_reorders_selected_item_not_current_track(self):
        queue = QueueManager()
        tracks = [
            Track(id=str(index), title=f"Track {index}", artist="Artist")
            for index in range(3)
        ]
        queue.set_queue(tracks, start_index=0)
        audio = SimpleNamespace(play_track=Mock())
        queue_list = ft.ReorderableListView()
        session = QueueControllerSession(
            queue,
            audio,
            Mock(),
            ft.AlertDialog(),
            queue_list,
            Mock(),
            selected_index=2,
        )

        session.reorder_selection(-1)
        self.assertEqual(queue.current_index, 0)
        session.activate()

        self.assertEqual([track.id for track in queue.queue], ["0", "2", "1"])
        self.assertEqual(queue.current_index, 1)
        self.assertEqual(session.selected_index, 1)
        audio.play_track.assert_called_once_with(queue.queue[1])

    def test_queue_selection_scrolls_selected_item_into_view(self):
        queue = QueueManager()
        tracks = [
            Track(id=str(index), title=f"Track {index}", artist="Artist")
            for index in range(3)
        ]
        queue.set_queue(tracks, start_index=0)
        queue_list = ft.ReorderableListView()
        queue_list.scroll_to = Mock()
        page = Mock()
        session = QueueControllerSession(
            queue,
            SimpleNamespace(play_track=Mock()),
            page,
            ft.AlertDialog(),
            queue_list,
            Mock(),
            selected_index=0,
        )

        session.move_selection(1)

        page.run_task.assert_called_once_with(
            queue_list.scroll_to,
            scroll_key="queue-item-1-1",
            duration=220,
        )


if __name__ == "__main__":
    unittest.main()
