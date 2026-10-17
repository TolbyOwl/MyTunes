import unittest
import tempfile
import os
import time
from mytunes.models.schema import init_db
from mytunes.models.podcast import PodcastShow, Episode
from mytunes.sync.sync_manager import SyncManager

class TestPodcastSubscriptions(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.conn = init_db(self.temp_db.name)

    def tearDown(self):
        self.conn.close()
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)

    def test_podcast_subscription_and_sync(self):
        # 1. Subscribe to a podcast
        show = PodcastShow(
            id="show_123",
            title="The Daily Tech",
            author="Tech Host",
            description="Daily tech news",
            feed_url="https://feeds.example.com/dailytech.xml",
            artwork_url="https://example.com/art.jpg"
        )
        self.conn.execute(
            """
            INSERT INTO podcasts (id, title, author, description, feed_url, artwork_url, date_subscribed)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (show.id, show.title, show.author, show.description, show.feed_url, show.artwork_url, time.time())
        )
        self.conn.commit()

        # Verify subscription exists in DB
        cursor = self.conn.execute("SELECT title, feed_url FROM podcasts WHERE feed_url = ?", (show.feed_url,))
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "The Daily Tech")

        # 2. Add an episode with playback position
        ep = Episode(
            id="ep_1",
            podcast_id=show.id,
            title="Episode 1: The Future of Music",
            audio_url="https://audio.example.com/ep1.mp3",
            playback_position=142.5
        )
        self.conn.execute(
            """
            INSERT INTO episodes (id, podcast_id, title, audio_url, playback_position)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ep.id, ep.podcast_id, ep.title, ep.audio_url, ep.playback_position)
        )
        self.conn.commit()

        # 3. Export to Cloud Sync snapshot
        sm = SyncManager(self.conn)
        snapshot = sm.export_sync_snapshot()

        self.assertIn("podcasts", snapshot)
        self.assertEqual(len(snapshot["podcasts"]), 1)
        self.assertEqual(snapshot["podcasts"][0]["feed_url"], show.feed_url)
        self.assertEqual(snapshot["podcasts"][0]["episodes"][0]["playback_position"], 142.5)

if __name__ == "__main__":
    unittest.main()
