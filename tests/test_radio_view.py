import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from mytunes.models.radio import RadioStation
from mytunes.models.schema import init_db
from mytunes.ui.theme import MetroTheme
from mytunes.ui.views.radio_view import RadioView


class TestRadioViewLoading(unittest.TestCase):
    def setUp(self):
        self.connection = init_db(":memory:")
        self.page = MagicMock()
        self.provider = Mock()
        with patch("mytunes.ui.views.radio_view.RadioProvider", return_value=self.provider):
            self.view = RadioView(
                self.page,
                MetroTheme(),
                Mock(),
                db_conn=self.connection,
            )

    def tearDown(self):
        self.connection.close()

    def test_radio_view_does_not_fetch_network_data_during_construction(self):
        self.provider.get_top_stations.assert_not_called()
        self.assertEqual(self.view.stations, [])

    def test_featured_stations_load_only_when_the_radio_tab_is_opened(self):
        self.view.ensure_featured_loaded()

        self.provider.get_top_stations.assert_not_called()
        self.page.run_task.assert_called_once()
        fetch_callback = self.page.run_task.call_args.args[0]
        self.assertIs(fetch_callback.__self__, self.view)
        self.assertIs(fetch_callback.__func__, self.view._fetch_remote_stations.__func__)

    def test_remote_station_fetch_does_not_block_and_renders_result(self):
        station = RadioStation(
            id="station-1",
            name="Test Station",
            stream_url="https://example.com/stream",
        )
        self.provider.get_top_stations.return_value = [station]
        with patch(
            "mytunes.ui.views.radio_view.asyncio.to_thread",
            new=AsyncMock(return_value=[station]),
        ) as to_thread:
            asyncio.run(
                self.view._fetch_remote_stations(
                    0,
                    lambda: self.provider.get_top_stations(limit=30),
                    featured=True,
                )
            )

        to_thread.assert_awaited_once()
        self.assertEqual(self.view.stations, [station])
        self.assertTrue(self.view._featured_loaded)

    def test_new_radio_request_discards_stale_network_response(self):
        station = RadioStation(
            id="stale",
            name="Stale Station",
            stream_url="https://example.com/stale",
        )
        self.view._request_generation = 2
        with patch(
            "mytunes.ui.views.radio_view.asyncio.to_thread",
            new=AsyncMock(return_value=[station]),
        ) as to_thread:
            asyncio.run(
                self.view._fetch_remote_stations(
                    1,
                    lambda: [station],
                )
            )

        self.assertEqual(self.view.stations, [])
        self.assertFalse(self.view._featured_loaded)


if __name__ == "__main__":
    unittest.main()
