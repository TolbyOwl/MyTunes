from __future__ import annotations
import json
import logging
import sqlite3
import time
from typing import Optional
from mytunes.models.podcast import Episode, PodcastShow

logger = logging.getLogger(__name__)


class PodcastCache:
    """Persistent cache for podcast directory searches and parsed RSS feeds."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_search_results(
        self,
        query: str,
        limit: int,
    ) -> Optional[tuple[list[PodcastShow], float]]:
        key = query.strip().casefold()
        row = self.conn.execute(
            """
            SELECT fetched_at, data_json
            FROM podcast_search_cache
            WHERE query = ? AND result_limit = ?
            """,
            (key, limit),
        ).fetchone()
        if row is None:
            return None

        try:
            records = json.loads(row["data_json"])
            shows = [self._show_from_data(record) for record in records]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            logger.warning("Ignoring invalid cached podcast search for %r: %s", query, error)
            return None
        return shows, row["fetched_at"]

    def store_search_results(
        self,
        query: str,
        limit: int,
        shows: list[PodcastShow],
    ) -> None:
        key = query.strip().casefold()
        payload = json.dumps([self._show_to_data(show) for show in shows])
        self.conn.execute(
            """
            INSERT OR REPLACE INTO podcast_search_cache
                (query, result_limit, fetched_at, data_json)
            VALUES (?, ?, ?, ?)
            """,
            (key, limit, time.time(), payload),
        )
        self.conn.commit()

    def get_feed(self, feed_url: str) -> Optional[tuple[PodcastShow, float]]:
        row = self.conn.execute(
            "SELECT fetched_at, data_json FROM podcast_feed_cache WHERE feed_url = ?",
            (feed_url,),
        ).fetchone()
        if row is None:
            return None

        try:
            show = self._show_from_data(json.loads(row["data_json"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            logger.warning("Ignoring invalid cached podcast feed %r: %s", feed_url, error)
            return None
        return show, row["fetched_at"]

    def store_feed(self, show: PodcastShow) -> None:
        payload = json.dumps(self._show_to_data(show))
        self.conn.execute(
            """
            INSERT OR REPLACE INTO podcast_feed_cache (feed_url, fetched_at, data_json)
            VALUES (?, ?, ?)
            """,
            (show.feed_url, time.time(), payload),
        )
        self.conn.commit()

    @staticmethod
    def _show_to_data(show: PodcastShow) -> dict:
        return {
            "id": show.id,
            "title": show.title,
            "author": show.author,
            "description": show.description,
            "feed_url": show.feed_url,
            "artwork_url": show.artwork_url,
            "episodes": [
                {
                    "id": episode.id,
                    "podcast_id": episode.podcast_id,
                    "title": episode.title,
                    "description": episode.description,
                    "audio_url": episode.audio_url,
                    "duration": episode.duration,
                    "published_at": episode.published_at,
                    "playback_position": episode.playback_position,
                    "is_played": episode.is_played,
                    "is_downloaded": episode.is_downloaded,
                    "download_path": episode.download_path,
                }
                for episode in show.episodes
            ],
        }

    @staticmethod
    def _show_from_data(data: dict) -> PodcastShow:
        return PodcastShow(
            id=data["id"],
            title=data["title"],
            author=data.get("author", ""),
            description=data.get("description", ""),
            feed_url=data["feed_url"],
            artwork_url=data.get("artwork_url"),
            episodes=[
                Episode(**episode_data)
                for episode_data in data.get("episodes", [])
            ],
        )
