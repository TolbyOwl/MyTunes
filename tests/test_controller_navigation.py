import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import flet as ft

from mytunes.core.queue import QueueManager
from mytunes.main import QueueControllerSession, XInputController
from mytunes.models.track import Track


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
        controller._axis_repeat_at = {}
        controller._stick_dead_zone = 0.35
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
                return 10

            def get_numaxes(self):
                return 4

            def get_button(self, index):
                return index in {0, 6, 7, 8, 9}

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
        self.assertEqual(buttons, controller.A | controller.BACK | controller.START)
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


if __name__ == "__main__":
    unittest.main()
