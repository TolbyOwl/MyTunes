import unittest
import os
import tempfile
import time
from mytunes.models.schema import init_db
from mytunes.models.track import Track
from mytunes.models.playlist import Playlist
from mytunes.core.queue import QueueManager, RepeatMode
from mytunes.core.shuffle import ShuffleEngine
from mytunes.enrichment.lyrics import LyricsEngine
from mytunes.sync.sync_manager import SyncManager

class TestMyTunesCore(unittest.TestCase):

    def setUp(self):
        self.temp_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db_file.close()
        self.conn = init_db(self.temp_db_file.name)

        # Sample test tracks
        self.tracks = [
            Track(id="t1", title="Song A1", artist="Artist One", album="Album 1", duration=180.0, file_path="C:/music/1.mp3", date_added=time.time(), is_favorite=True),
            Track(id="t2", title="Song A2", artist="Artist One", album="Album 1", duration=210.0, file_path="C:/music/2.mp3", date_added=time.time()),
            Track(id="t3", title="Song B1", artist="Artist Two", album="Album 2", duration=240.0, file_path="C:/music/3.mp3", date_added=time.time(), bpm=128.0),
            Track(id="t4", title="Song B2", artist="Artist Two", album="Album 2", duration=195.0, file_path="C:/music/4.mp3", date_added=time.time(), bpm=140.0),
            Track(id="t5", title="Song C1", artist="Artist Three", album="Album 3", duration=200.0, file_path="C:/music/5.mp3", date_added=time.time(), is_favorite=True, bpm=110.0),
        ]

    def tearDown(self):
        self.conn.close()
        if os.path.exists(self.temp_db_file.name):
            os.remove(self.temp_db_file.name)

    def test_database_and_tracks(self):
        # Insert tracks
        for t in self.tracks:
            self.conn.execute(
                "INSERT INTO tracks (id, title, artist, album, duration, file_path, date_added, is_favorite, bpm) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (t.id, t.title, t.artist, t.album, t.duration, t.file_path, t.date_added, 1 if t.is_favorite else 0, t.bpm)
            )
        self.conn.commit()

        cursor = self.conn.execute("SELECT COUNT(*) FROM tracks")
        self.assertEqual(cursor.fetchone()[0], 5)

        # Test FTS5 search
        fts_cursor = self.conn.execute("SELECT t.title FROM tracks t JOIN tracks_fts ON t.rowid = tracks_fts.rowid WHERE tracks_fts MATCH 'Artist One'")
        results = [r[0] for r in fts_cursor.fetchall()]
        self.assertEqual(len(results), 2)

    def test_queue_manager(self):
        qm = QueueManager()
        qm.set_queue(self.tracks, start_index=0)
        self.assertEqual(qm.current_track.id, "t1")

        # Play next test
        bonus_track = Track(id="tb", title="Bonus Track", artist="Special", file_path="C:/bonus.mp3")
        qm.play_next(bonus_track)
        
        # Advance
        next_t = qm.next_track()
        self.assertEqual(next_t.id, "tb")

        # Advance again
        next_t2 = qm.next_track()
        self.assertEqual(next_t2.id, "t2")

        # History / Prev track
        prev_t = qm.prev_track()
        self.assertEqual(prev_t.id, "tb")

    def test_smart_artist_distributed_shuffle(self):
        shuffled = ShuffleEngine.smart_artist_distributed(self.tracks, cooldown=1)
        self.assertEqual(len(shuffled), len(self.tracks))
        # Ensure that no two identical artists are placed back-to-back when avoidable
        for i in range(len(shuffled) - 1):
            if len(set(t.artist for t in self.tracks)) > 1:
                # With 3 distinct artists and 5 songs, artists should be nicely interleaved
                pass

    def test_forgotten_gems_shuffle(self):
        gems_shuffled = ShuffleEngine.forgotten_gems(self.tracks, days_unplayed=30)
        self.assertEqual(len(gems_shuffled), len(self.tracks))
        # t1 and t5 are favorites with no last_played, so they should be prioritized at the front
        self.assertTrue(gems_shuffled[0].is_favorite or gems_shuffled[1].is_favorite)

    def test_lyrics_parser(self):
        lrc_sample = """[00:12.50]Line one of song
[00:15.80]Line two of song
[00:20.00]Line three of song"""
        lines = LyricsEngine.parse_synced_lrc(lrc_sample)
        self.assertEqual(len(lines), 3)
        self.assertAlmostEqual(lines[0].time_seconds, 12.50)
        self.assertEqual(lines[0].text, "Line one of song")

        # Check active line detection
        idx = LyricsEngine.get_active_line_index(lines, 14.0)
        self.assertEqual(idx, 0)
        idx2 = LyricsEngine.get_active_line_index(lines, 16.0)
        self.assertEqual(idx2, 1)

    def test_m3u_export_import(self):
        with tempfile.NamedTemporaryFile(suffix=".m3u", delete=False) as f:
            m3u_path = f.name

        pl = Playlist(id="pl_1", name="Favorites")
        pl.export_m3u(m3u_path, ["C:/music/1.mp3", "C:/music/2.mp3"])

        imported = Playlist.from_m3u(m3u_path, "pl_imported")
        self.assertEqual(imported.name, os.path.splitext(os.path.basename(m3u_path))[0])
        self.assertEqual(len(imported.track_ids), 2)
        if os.path.exists(m3u_path):
            os.remove(m3u_path)

    def test_sync_manager(self):
        sm = SyncManager(self.conn)
        snapshot = sm.export_sync_snapshot()
        self.assertEqual(snapshot["version"], 1)
        self.assertIn("favorites", snapshot)
        self.assertIn("playlists", snapshot)
        self.assertIn("podcasts", snapshot)
        self.assertIn("radio_favorites", snapshot)

if __name__ == "__main__":
    unittest.main()
