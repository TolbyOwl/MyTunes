import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

import flet as ft

from mytunes.enrichment.lyrics import LyricsLine
from mytunes.ui.components.lyrics_view import LyricsView


class TestLyricsView(unittest.TestCase):
    def setUp(self):
        self.page = MagicMock()
        self.page.run_task.side_effect = lambda handler, *args, **kwargs: asyncio.run(
            handler(*args, **kwargs)
        )
        self.seek = MagicMock()
        self.view = LyricsView(self.page, self.seek)
        self.view.lines = [
            LyricsLine(10.0, "First line"),
            LyricsLine(20.0, "Second line"),
        ]
        self.view._render_lyrics()
        self.view.lyrics_column.scroll_to = AsyncMock()

    def test_active_line_scrolls_into_view(self):
        self.view.update_position(21.0)

        self.assertEqual(self.view.active_index, 1)
        self.view.lyrics_column.scroll_to.assert_awaited_once_with(
            scroll_key=self.view.line_scroll_keys[1],
            duration=350
        )
        self.assertIsInstance(self.view.lyrics_column.controls[1].key, ft.ScrollKey)

    def test_synced_lines_are_centered_and_tappable(self):
        first_line = self.view.lyrics_column.controls[0]

        self.assertEqual(
            self.view.content.content.horizontal_alignment,
            ft.CrossAxisAlignment.CENTER
        )
        self.assertEqual(first_line.text_align, ft.TextAlign.CENTER)
        self.assertTrue(first_line.selectable)
        self.assertIsNotNone(first_line.on_tap)

    def test_manual_scroll_pauses_follow_and_resume_restores_it(self):
        event = MagicMock()
        event.event_type = ft.ScrollType.USER
        self.view._on_scroll(event)

        self.assertFalse(self.view.auto_follow)
        self.assertTrue(self.view.resume_auto_scroll_button.visible)

        self.view.update_position(21.0)
        self.view.lyrics_column.scroll_to.assert_not_awaited()

        self.view._resume_auto_scroll()

        self.assertTrue(self.view.auto_follow)
        self.assertFalse(self.view.resume_auto_scroll_button.visible)
        self.view.lyrics_column.scroll_to.assert_awaited_once_with(
            scroll_key=self.view.line_scroll_keys[1],
            duration=350
        )

    def test_tapping_synced_line_seeks_to_its_timestamp(self):
        self.view.lyrics_column.controls[1].on_tap(None)

        self.seek.assert_called_once_with(20.0)
        self.assertEqual(self.view.active_index, 1)

    def test_plain_lyrics_do_not_pause_autofollow_or_seek(self):
        self.view.lines = []
        self.view.plain_lyrics = "Unsynced lyrics"
        self.view._render_lyrics()
        event = MagicMock()
        event.event_type = ft.ScrollType.USER

        self.view._on_scroll(event)

        self.assertTrue(self.view.auto_follow)
        self.assertFalse(self.view.resume_auto_scroll_button.visible)
        self.assertFalse(self.view.lyrics_column.controls[0].on_tap)
