import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock
from unittest.mock import patch

import mytunes.ui.views.settings_view as settings_module

from mytunes.models.schema import init_db
from mytunes.sync.sync_manager import SyncManager
from mytunes.ui.theme import MetroTheme
from mytunes.ui.views.cloud_view import CloudView
from mytunes.ui.views.settings_view import SettingsView


class TestMusicFolderSettings(unittest.TestCase):

    def setUp(self):
        self.conn = init_db(":memory:")
        self.provider = Mock()
        self.page = MagicMock()
        self.library_updated = Mock()
        self.view = SettingsView(
            self.page,
            MetroTheme(),
            lambda: None,
            self.conn,
            self.provider,
            self.library_updated,
        )

    def tearDown(self):
        self.conn.close()

    def test_saved_folders_load_without_scanning_on_startup(self):
        self.assertEqual(self.view.scan_folders, [])
        self.provider.scan_directory.assert_not_called()

        self.view.scan_folders = [os.path.normpath("C:/Music")]
        self.view._save_scan_folders()

        reopened_view = SettingsView(
            self.page,
            MetroTheme(),
            lambda: None,
            self.conn,
            self.provider,
            self.library_updated,
        )
        self.assertEqual(reopened_view.scan_folders, self.view.scan_folders)
        self.provider.scan_directory.assert_not_called()

    def test_adding_folder_saves_it_without_scanning(self):
        with tempfile.TemporaryDirectory() as folder:
            self.view.folder_picker.get_directory_path = AsyncMock(return_value=folder)

            asyncio.run(self.view._on_add_folder(None))

            self.assertEqual(self.view.scan_folders, [os.path.normpath(folder)])
            self.provider.scan_directory.assert_not_called()

    def test_scan_request_runs_in_background(self):
        self.view.scan_folders = ["C:/Music"]

        self.view._start_scan(self.view.scan_folders)

        self.page.run_thread.assert_called_once_with(
            self.view._scan_folders,
            self.view.scan_folders,
        )
        self.assertTrue(self.view.is_scanning)

    def test_removing_folder_deindexes_tracks_but_keeps_files_and_other_roots(self):
        with tempfile.TemporaryDirectory() as root:
            removed_root = os.path.join(root, "Removed")
            retained_root = os.path.join(removed_root, "Retained")
            outside_root = os.path.join(root, "Outside")
            os.makedirs(retained_root)
            os.makedirs(outside_root)
            removed_file = os.path.join(removed_root, "removed.mp3")
            retained_file = os.path.join(retained_root, "retained.mp3")
            outside_file = os.path.join(outside_root, "outside.mp3")
            for path in (removed_file, retained_file, outside_file):
                with open(path, "wb") as media_file:
                    media_file.write(b"media")
                self.conn.execute(
                    "INSERT INTO tracks (id, title, file_path, date_added) VALUES (?, ?, ?, ?)",
                    (path, os.path.basename(path), path, 1.0),
                )
            self.conn.commit()
            self.view.scan_folders = [removed_root, retained_root, outside_root]

            self.view._remove_scan_folder(removed_root)

            indexed_paths = {
                row["file_path"]
                for row in self.conn.execute("SELECT file_path FROM tracks")
            }
            self.assertNotIn(removed_file, indexed_paths)
            self.assertIn(retained_file, indexed_paths)
            self.assertIn(outside_file, indexed_paths)
            self.assertTrue(os.path.isfile(removed_file))
            self.assertEqual(
                self.view.scan_folders,
                [retained_root, outside_root],
            )
            self.library_updated.assert_called_once_with()

    def test_removing_nested_scan_root_keeps_tracks_covered_by_parent(self):
        with tempfile.TemporaryDirectory() as root:
            nested_root = os.path.join(root, "Nested")
            os.makedirs(nested_root)
            media_path = os.path.join(nested_root, "song.mp3")
            with open(media_path, "wb") as media_file:
                media_file.write(b"media")
            self.conn.execute(
                "INSERT INTO tracks (id, title, file_path, date_added) VALUES (?, ?, ?, ?)",
                ("nested-track", "Song", media_path, 1.0),
            )
            self.conn.commit()
            self.view.scan_folders = [root, nested_root]

            self.view._remove_scan_folder(nested_root)

            self.assertIsNotNone(
                self.conn.execute(
                    "SELECT id FROM tracks WHERE id = ?", ("nested-track",)
                ).fetchone()
            )
            self.assertTrue(os.path.isfile(media_path))

    def test_clear_app_caches_preserves_offline_downloads(self):
        with tempfile.TemporaryDirectory() as root:
            audio_cache = os.path.join(root, "audio_cache")
            artwork_cache = os.path.join(root, "art_cache")
            offline_downloads = os.path.join(root, "offline_downloads")
            for directory in (audio_cache, artwork_cache, offline_downloads):
                os.makedirs(directory)
            audio_file = os.path.join(audio_cache, "stream.mp3")
            artwork_file = os.path.join(artwork_cache, "cover.jpg")
            offline_file = os.path.join(offline_downloads, "saved.mp3")
            for path in (audio_file, artwork_file, offline_file):
                with open(path, "wb") as cached_file:
                    cached_file.write(b"cached data")
            self.conn.execute(
                "INSERT INTO tracks (id, title, file_path, artwork_path, date_added) "
                "VALUES (?, ?, ?, ?, ?)",
                ("cached-art-track", "Song", "song.mp3", artwork_file, 1.0),
            )
            self.conn.execute(
                "INSERT INTO artist_metadata "
                "(artist_name, updated_at) VALUES (?, ?)",
                ("Artist", 1.0),
            )
            self.conn.execute(
                "INSERT INTO podcast_search_cache "
                "(query, result_limit, fetched_at, data_json) VALUES (?, ?, ?, ?)",
                ("show", 10, 1.0, "[]"),
            )
            self.conn.execute(
                "INSERT INTO podcast_feed_cache "
                "(feed_url, fetched_at, data_json) VALUES (?, ?, ?)",
                ("https://example.com/feed", 1.0, "{}"),
            )
            self.conn.commit()
            with (
                patch.object(settings_module, "DEFAULT_CACHE_DIR", audio_cache),
                patch.object(settings_module, "ARTWORK_CACHE_DIR", artwork_cache),
                patch.object(settings_module, "LOCAL_ARTWORK_CACHE_DIR", artwork_cache),
            ):
                self.view._clear_cache(None)

            self.assertEqual(os.listdir(audio_cache), [])
            self.assertEqual(os.listdir(artwork_cache), [])
            self.assertTrue(os.path.isfile(offline_file))
            self.assertEqual(
                self.conn.execute("SELECT COUNT(*) FROM artist_metadata").fetchone()[0],
                0,
            )
            self.assertEqual(
                self.conn.execute("SELECT COUNT(*) FROM podcast_search_cache").fetchone()[0],
                0,
            )
            self.assertEqual(
                self.conn.execute("SELECT COUNT(*) FROM podcast_feed_cache").fetchone()[0],
                0,
            )
            row = self.conn.execute(
                "SELECT artwork_path FROM tracks WHERE id = ?", ("cached-art-track",)
            ).fetchone()
            self.assertIsNone(row["artwork_path"])
            self.library_updated.assert_called_once_with()

    def test_scan_folders_scans_saved_paths_and_refreshes_library(self):
        with tempfile.TemporaryDirectory() as folder:
            tracks = [object(), object()]
            self.provider.scan_directory.return_value = tracks
            self.view.scan_folders = [folder]

            self.view._scan_folders([folder])

            self.provider.scan_directory.assert_called_once_with(folder)
            self.page.run_task.assert_called_once()
            finish_scan, scanned_count, errors = self.page.run_task.call_args.args
            self.assertEqual(finish_scan, self.view._finish_scan)
            self.assertEqual(scanned_count, len(tracks))
            self.assertEqual(errors, [])
            asyncio.run(finish_scan(scanned_count, errors))

            self.library_updated.assert_called_once_with()

    def test_rescan_missing_folder_reports_failure(self):
        with tempfile.TemporaryDirectory() as root:
            missing_folder = os.path.join(root, "missing")
            self._assert_missing_folder_scan(missing_folder)

    def test_cloud_sync_view_can_be_embedded_in_settings(self):
        cloud_view = CloudView(
            self.page,
            MetroTheme(),
            SyncManager(self.conn),
            embedded=True,
        )
        settings_view = SettingsView(
            self.page,
            MetroTheme(),
            lambda: None,
            self.conn,
            self.provider,
            self.library_updated,
            cloud_view,
        )

        self.assertIn(cloud_view, settings_view.content.controls)
        self.assertFalse(cloud_view.expand)
        self.assertIsNone(cloud_view.content.scroll)

    def _assert_missing_folder_scan(self, missing_folder):
        self.provider.scan_directory.reset_mock()

        self.view._scan_folders([missing_folder])

        self.provider.scan_directory.assert_not_called()
        _, scanned_count, errors = self.page.run_task.call_args.args
        self.assertEqual(scanned_count, 0)
        self.assertEqual(errors, [f"Folder not found: {missing_folder}"])


if __name__ == "__main__":
    unittest.main()
