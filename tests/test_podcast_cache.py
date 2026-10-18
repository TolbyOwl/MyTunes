import unittest
from unittest.mock import MagicMock, Mock, patch

import flet as ft
from mytunes.models.podcast import Episode, PodcastShow
from mytunes.models.schema import init_db
from mytunes.providers.podcast_cache import PodcastCache
from mytunes.ui.theme import MetroTheme
from mytunes.ui.views.podcasts_view import PodcastsView


class TestPodcastCache(unittest.TestCase):

    def setUp(self):
        self.conn = init_db(":memory:")
        self.cache = PodcastCache(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_search_results_are_cached_by_normalized_query_and_limit(self):
        show = PodcastShow(
            id="42",
            title="Test Podcast",
            author="Host",
            feed_url="https://example.com/feed.xml",
            artwork_url="https://example.com/art.jpg",
        )
        self.cache.store_search_results("  Test PODCAST ", 20, [show])

        cached = self.cache.get_search_results("test podcast", 20)

        assert cached is not None
        shows, fetched_at = cached
        self.assertEqual(len(shows), 1)
        self.assertEqual(shows[0].title, show.title)
        self.assertGreater(fetched_at, 0)
        self.assertIsNone(self.cache.get_search_results("test podcast", 10))

    def test_feed_cache_round_trips_episode_metadata(self):
        show = PodcastShow(
            id="show",
            title="Test Podcast",
            author="Host",
            description="Feed description",
            feed_url="https://example.com/feed.xml",
            artwork_url="https://example.com/art.jpg",
            episodes=[
                Episode(
                    id="episode",
                    podcast_id="show",
                    title="Latest Episode",
                    description="Episode details",
                    audio_url="https://example.com/audio.mp3",
                    duration=125.5,
                    published_at=1234.0,
                )
            ],
        )
        self.cache.store_feed(show)

        cached = self.cache.get_feed(show.feed_url)

        assert cached is not None
        cached_show, fetched_at = cached
        self.assertEqual(cached_show.title, show.title)
        self.assertEqual(cached_show.episodes[0].audio_url, show.episodes[0].audio_url)
        self.assertEqual(cached_show.episodes[0].duration, show.episodes[0].duration)
        self.assertGreater(fetched_at, 0)

    def test_fresh_search_cache_avoids_directory_request(self):
        view = PodcastsView(
            MagicMock(),
            self.conn,
            MetroTheme(),
            Mock(),
        )
        show = PodcastShow(
            id="42",
            title="Test Podcast",
            feed_url="https://example.com/feed.xml",
        )
        view.cache.store_search_results("test podcast", 20, [show])
        view.provider.search_itunes = Mock()
        view.search_input.value = "Test Podcast"

        view._do_search()

        view.provider.search_itunes.assert_not_called()
        self.assertEqual([result.title for result in view.search_results], [show.title])

    def test_cached_feed_renders_and_refresh_icon_is_next_to_subscribe(self):
        view = PodcastsView(
            MagicMock(),
            self.conn,
            MetroTheme(),
            Mock(),
        )
        show = PodcastShow(
            id="show",
            title="Test Podcast",
            feed_url="https://example.com/feed.xml",
            episodes=[
                Episode(
                    id="episode",
                    podcast_id="show",
                    title="Latest Episode",
                    audio_url="https://example.com/audio.mp3",
                )
            ],
        )
        view.cache.store_feed(show)
        view.provider.parse_feed = Mock()

        view._open_show_details(show)

        view.provider.parse_feed.assert_not_called()
        selected_show = view.selected_show
        assert selected_show is not None
        self.assertEqual(selected_show.title, show.title)
        episodes_list = view.content_area.controls[0]
        assert isinstance(episodes_list, ft.ListView)
        header = episodes_list.controls[1]
        assert isinstance(header, ft.Row)
        metadata = header.controls[1]
        assert isinstance(metadata, ft.Column)
        subscribe_and_refresh = metadata.controls[3]
        assert isinstance(subscribe_and_refresh, ft.Row)
        self.assertEqual(len(subscribe_and_refresh.controls), 2)
        refresh_button = subscribe_and_refresh.controls[1]
        assert isinstance(refresh_button, ft.IconButton)
        self.assertEqual(refresh_button.icon, ft.Icons.REFRESH)
        self.assertEqual(refresh_button.tooltip, "Refresh podcast episodes")
        self.assertIsNotNone(refresh_button.on_click)

    def test_stale_feed_is_shown_while_refresh_runs_in_background(self):
        view = PodcastsView(
            MagicMock(),
            self.conn,
            MetroTheme(),
            Mock(),
        )
        show = PodcastShow(
            id="show",
            title="Saved Podcast",
            feed_url="https://example.com/feed.xml",
            episodes=[
                Episode(
                    id="episode",
                    podcast_id="show",
                    title="Saved Episode",
                    audio_url="https://example.com/audio.mp3",
                )
            ],
        )
        view.cache.store_feed(show)
        self.conn.execute(
            "UPDATE podcast_feed_cache SET fetched_at = 0 WHERE feed_url = ?",
            (show.feed_url,),
        )
        view.provider.parse_feed = Mock()

        with patch("mytunes.ui.views.podcasts_view.threading.Thread") as worker:
            view._open_show_details(show)

        view.provider.parse_feed.assert_not_called()
        self.assertTrue(view._feed_refreshing)
        selected_show = view.selected_show
        assert selected_show is not None
        self.assertEqual(selected_show.title, show.title)
        worker.assert_called_once()
        self.assertEqual(worker.call_args.kwargs["target"], view._feed_refresh_worker)


if __name__ == "__main__":
    unittest.main()
