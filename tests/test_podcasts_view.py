import asyncio
import os
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

import flet as ft
from mytunes.models.podcast import Episode, PodcastShow
from mytunes.models.schema import init_db
from mytunes.ui.theme import MetroTheme
from mytunes.ui.views.podcasts_view import (
    EPISODE_BATCH_SIZE,
    INITIAL_EPISODE_BATCH_SIZE,
    PodcastsView,
)


class TestPodcastEpisodeRendering(unittest.TestCase):

    def setUp(self):
        self.conn = init_db(":memory:")
        self.page = MagicMock()
        self.on_play_next = Mock()
        self.on_add_queue = Mock()
        self.view = PodcastsView(
            self.page,
            self.conn,
            MetroTheme(),
            Mock(),
            self.on_play_next,
            self.on_add_queue,
        )
        self.show = PodcastShow(
            id="show",
            title="Test Podcast",
            feed_url="https://example.com/feed",
            episodes=[
                Episode(
                    id=str(index),
                    podcast_id="show",
                    title=f"Episode {index}",
                    published_at=float(index),
                )
                for index in range(INITIAL_EPISODE_BATCH_SIZE + EPISODE_BATCH_SIZE + 5)
            ],
        )

    def tearDown(self):
        self.conn.close()

    @staticmethod
    def _episode_titles(episodes_list: ft.ListView) -> list[str]:
        titles = []
        for row in episodes_list.controls:
            if not isinstance(row, ft.Container) or not isinstance(row.content, ft.Row):
                continue
            if len(row.content.controls) < 2:
                continue
            details = row.content.controls[1]
            if not isinstance(details, ft.Column):
                continue
            title = details.controls[0]
            if not isinstance(title, ft.Text):
                continue
            titles.append(title.value or "")
        return titles

    def _rendered_episodes_list(self) -> ft.ListView:
        episodes_list = self.view.content_area.controls[0]
        if not isinstance(episodes_list, ft.ListView):
            self.fail("Expected the rendered episode list to be a ListView")
        return episodes_list

    def _send_scroll_event(self, episodes_list: ft.ListView, pixels: float) -> None:
        event_handler = getattr(episodes_list, "on_scroll", None)
        if not callable(event_handler):
            self.fail("Expected the episode list to have a scroll handler")
        event_handler(
            ft.OnScrollEvent(
                name="scroll",
                control=episodes_list,
                event_type=ft.ScrollType.UPDATE,
                pixels=pixels,
                min_scroll_extent=0,
                max_scroll_extent=100,
                viewport_dimension=50,
            )
        )

    def test_renders_latest_100_episodes_first_without_scheduling_more(self):
        self.view._render_show_episodes(self.show)

        episodes_list = self._rendered_episodes_list()
        self.assertIsNone(self.view.content_area.scroll)
        expected_latest = [
            f"Episode {index}"
            for index in reversed(range(len(self.show.episodes) - INITIAL_EPISODE_BATCH_SIZE, len(self.show.episodes)))
        ]
        self.assertEqual(
            self._episode_titles(episodes_list),
            expected_latest,
        )
        self.page.run_task.assert_not_called()

    def test_appends_episodes_in_batches_after_scrolling_past_midpoint(self):
        self.view._render_show_episodes(self.show)
        episodes_list = self._rendered_episodes_list()

        self._send_scroll_event(episodes_list, 49)
        self.page.run_task.assert_not_called()

        self._send_scroll_event(episodes_list, 51)
        self.page.run_task.assert_called_once()
        task_args = self.page.run_task.call_args.args
        self.assertIs(task_args[0].__self__, self.view)
        self.assertIs(task_args[0].__func__, PodcastsView._append_next_episode_batch)
        self.assertEqual(task_args[1], self.show)
        self.assertEqual(task_args[2], self.view._episode_render_id)
        self.assertIs(task_args[3], episodes_list)
        self._send_scroll_event(episodes_list, 75)
        self.page.run_task.assert_called_once()

        asyncio.run(
            self.view._append_next_episode_batch(
                task_args[1],
                task_args[2],
                task_args[3],
            )
        )
        self.assertEqual(
            len(self._episode_titles(episodes_list)),
            INITIAL_EPISODE_BATCH_SIZE + EPISODE_BATCH_SIZE,
        )

        self._send_scroll_event(episodes_list, 51)
        task_args = self.page.run_task.call_args.args
        asyncio.run(
            self.view._append_next_episode_batch(
                task_args[1],
                task_args[2],
                task_args[3],
            )
        )
        self.assertEqual(len(self._episode_titles(episodes_list)), len(self.show.episodes))
        self.assertEqual(
            self._episode_titles(episodes_list),
            [f"Episode {index}" for index in reversed(range(len(self.show.episodes)))],
        )

    def test_ignores_scroll_events_for_stale_render(self):
        self.view._render_show_episodes(self.show)
        episodes_list = self._rendered_episodes_list()
        self._send_scroll_event(episodes_list, 51)
        task_args = self.page.run_task.call_args.args
        self.view._episode_render_id += 1

        asyncio.run(
            self.view._append_next_episode_batch(
                task_args[1],
                task_args[2],
                task_args[3],
            )
        )

        self.assertEqual(
            len(self._episode_titles(episodes_list)),
            INITIAL_EPISODE_BATCH_SIZE,
        )

    def test_disables_scroll_handler_when_all_episodes_are_initially_rendered(self):
        self.show.episodes = self.show.episodes[:INITIAL_EPISODE_BATCH_SIZE]

        self.view._render_show_episodes(self.show)

        episodes_list = self._rendered_episodes_list()
        self.assertIsNone(episodes_list.on_scroll)
        self.page.run_task.assert_not_called()

    def test_episode_menu_queues_episode_as_track(self):
        self.view._render_show_episodes(self.show)
        episode_row = self._rendered_episodes_list().controls[3]
        episode_menu = episode_row.content.controls[-1]

        self.assertIsInstance(episode_menu, ft.PopupMenuButton)
        self.assertEqual(
            [item.content for item in episode_menu.items],
            ["Play Next", "Add to Queue", "Download Episode"],
        )
        episode_menu.items[0].on_click(None)
        episode_menu.items[1].on_click(None)

        next_track = self.on_play_next.call_args.args[0]
        queued_track = self.on_add_queue.call_args.args[0]
        self.assertEqual(next_track.id, f"pod_{self.show.episodes[-1].id}")
        self.assertEqual(next_track.file_path, self.show.episodes[-1].audio_url)
        self.assertEqual(next_track.source, "stream")
        self.assertEqual(queued_track.id, next_track.id)

    def test_episode_download_can_be_deleted_from_the_menu(self):
        episode = self.show.episodes[0]
        episode.audio_url = "https://example.com/audio.mp3"
        with tempfile.TemporaryDirectory() as offline_dir:
            download_path = os.path.join(
                offline_dir,
                f"Episode 0_{self.view._download_episode_id(episode)}.mp3",
            )
            with open(download_path, "wb") as download:
                download.write(b"audio")

            self.view._audio_cache = Mock()
            self.view._audio_cache.download_for_offline.return_value = download_path
            self.page.run_task.side_effect = lambda task: asyncio.run(task())
            row = self.view._build_episode_row(episode, self.show)
            download_item = row.content.controls[-1].items[-1]

            with (
                patch("mytunes.ui.views.podcasts_view.OFFLINE_DIR", offline_dir),
                patch("mytunes.ui.views.podcasts_view.threading.Thread") as thread,
            ):
                self.view._start_episode_download(episode, self.show, download_item)
                thread.call_args.kwargs["target"](*thread.call_args.kwargs["args"])

                self.assertTrue(episode.is_downloaded)
                self.assertEqual(download_item.content, "Delete Download")
                self.assertTrue(os.path.isfile(download_path))
                download_item.on_click(None)

            self.assertFalse(episode.is_downloaded)
            self.assertFalse(os.path.exists(download_path))
            self.assertEqual(download_item.content, "Download Episode")

    def test_restores_outer_scroll_when_returning_to_subscriptions(self):
        self.view._render_show_episodes(self.show)
        self.view._navigate_back()

        self.assertEqual(self.view.content_area.scroll, ft.ScrollMode.AUTO)


if __name__ == "__main__":
    unittest.main()
