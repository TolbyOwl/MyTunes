from __future__ import annotations
import httpx
import feedparser
import time
import hashlib
from typing import List, Optional
from mytunes.models.podcast import PodcastShow, Episode

class PodcastProvider:
    """Provides podcast search (via iTunes API) and RSS feed parsing (via feedparser)."""

    def __init__(self):
        self.client = httpx.Client(timeout=10.0, headers={"User-Agent": "MyTunes/1.0"})

    def search_itunes(self, term: str, limit: int = 25) -> List[PodcastShow]:
        """Searches iTunes directory for podcasts."""
        url = "https://itunes.apple.com/search"
        params = {"term": term, "media": "podcast", "entity": "podcast", "limit": limit}
        try:
            resp = self.client.get(url, params=params)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                shows = []
                for item in results:
                    feed_url = item.get("feedUrl")
                    if not feed_url:
                        continue
                    show_id = str(item.get("collectionId", ""))
                    shows.append(PodcastShow(
                        id=show_id,
                        title=item.get("collectionName", "Unknown Podcast"),
                        author=item.get("artistName", ""),
                        description="",
                        feed_url=feed_url,
                        artwork_url=item.get("artworkUrl600") or item.get("artworkUrl100")
                    ))
                return shows
        except Exception:
            pass
        return []

    def parse_feed(self, feed_url: str) -> Optional[PodcastShow]:
        """Parses an RSS feed and returns the PodcastShow with its episodes."""
        try:
            feed = feedparser.parse(feed_url)
            if not feed or not feed.channel:
                return None

            channel = feed.channel
            title = getattr(channel, "title", "Unknown Podcast")
            author = getattr(channel, "author", "")
            description = getattr(channel, "description", "")
            artwork_url = None
            if hasattr(channel, "image") and hasattr(channel.image, "href"):
                artwork_url = channel.image.href

            show_id = hashlib.md5(feed_url.encode("utf-8")).hexdigest()
            show = PodcastShow(
                id=show_id,
                title=title,
                author=author,
                description=description,
                feed_url=feed_url,
                artwork_url=artwork_url
            )

            episodes = []
            for entry in feed.entries:
                audio_url = ""
                duration = 0.0

                # Extract audio enclosure
                if hasattr(entry, "enclosures"):
                    for enc in entry.enclosures:
                        if enc.get("type", "").startswith("audio/"):
                            audio_url = enc.get("href", "")
                            break

                if not audio_url:
                    continue

                # Duration extraction (e.g. itunes_duration can be "HH:MM:SS", "MM:SS", or total seconds)
                raw_duration = getattr(entry, "itunes_duration", None)
                if raw_duration:
                    try:
                        parts = str(raw_duration).strip().split(":")
                        if len(parts) == 3:
                            duration = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                        elif len(parts) == 2:
                            duration = float(parts[0]) * 60 + float(parts[1])
                        elif len(parts) == 1:
                            duration = float(parts[0])
                    except Exception:
                        duration = 0.0

                ep_id = getattr(entry, "id", None) or hashlib.md5(audio_url.encode("utf-8")).hexdigest()
                ep_title = getattr(entry, "title", "Untitled Episode")
                ep_desc = getattr(entry, "summary", "") or getattr(entry, "description", "")

                # Published time
                published_at = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published_at = time.mktime(entry.published_parsed)

                episodes.append(Episode(
                    id=ep_id,
                    podcast_id=show_id,
                    title=ep_title,
                    description=ep_desc,
                    audio_url=audio_url,
                    duration=duration,
                    published_at=published_at
                ))

            show.episodes = episodes
            return show
        except Exception:
            return None
