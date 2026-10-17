"""
Artist metadata provider for fetching artist images and biographies.
Uses Deezer API for high-resolution artist images and fan stats.
Uses Last.fm API for detailed artist biographies, retaining the "Read more on Last.fm" link,
with Wikipedia API as fallback.
Includes local SQLite caching to ensure instant loads and offline availability.
"""

from __future__ import annotations
import os
import re
import json
import ssl
import time
import urllib.request
import urllib.parse
from typing import Optional, Dict

LASTFM_API_KEY = "9517950dfe325f4fc952d19c1ddf65b4"

class ArtistMetadataProvider:
    """
    Fetches and caches artist pictures, fan statistics, and biographies.
    """

    def __init__(self, db_conn=None):
        self.conn = db_conn
        self._ensure_cache_table()
        # SSL context that handles self-signed or system-expired root certificates gracefully
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    def _ensure_cache_table(self) -> None:
        if self.conn:
            try:
                self.conn.execute("""
                    CREATE TABLE IF NOT EXISTS artist_metadata (
                        artist_name TEXT PRIMARY KEY,
                        picture_url TEXT,
                        picture_medium TEXT,
                        bio TEXT,
                        lastfm_url TEXT,
                        nb_fan INTEGER DEFAULT 0,
                        deezer_id INTEGER,
                        updated_at REAL NOT NULL
                    )
                """)
                # Add lastfm_url column if migrating from previous schema
                try:
                    self.conn.execute("ALTER TABLE artist_metadata ADD COLUMN lastfm_url TEXT")
                except Exception:
                    pass
                self.conn.commit()
            except Exception:
                pass

    def get_cached_metadata(self, artist_name: str) -> Optional[Dict]:
        """Retrieves cached metadata from the database if available."""
        if not self.conn or not artist_name:
            return None
        try:
            row = self.conn.execute(
                "SELECT artist_name, picture_url, picture_medium, bio, lastfm_url, nb_fan, deezer_id, updated_at "
                "FROM artist_metadata WHERE LOWER(artist_name) = LOWER(?)",
                (artist_name.strip(),)
            ).fetchone()
            if row:
                return {
                    "artist_name": row["artist_name"],
                    "picture_url": row["picture_url"],
                    "picture_medium": row["picture_medium"],
                    "bio": row["bio"] or "",
                    "lastfm_url": row["lastfm_url"] if "lastfm_url" in row.keys() else None,
                    "nb_fan": row["nb_fan"] or 0,
                    "deezer_id": row["deezer_id"],
                    "updated_at": row["updated_at"]
                }
        except Exception:
            pass
        return None

    def fetch_and_cache(self, artist_name: str) -> Dict:
        """
        Fetches artist image and fans from Deezer,
        bio from Last.fm (retaining 'Read more on Last.fm' with link, and Wikipedia fallback),
        and saves the result to SQLite cache.
        """
        artist_name = (artist_name or "").strip()
        if not artist_name:
            return {"artist_name": "", "picture_url": None, "picture_medium": None, "bio": "", "lastfm_url": None, "nb_fan": 0}

        # Check existing cache first
        cached = self.get_cached_metadata(artist_name)
        if cached and (cached.get("picture_url") or cached.get("bio")):
            return cached

        picture_url = None
        picture_medium = None
        nb_fan = 0
        deezer_id = None
        lastfm_url = None

        # 1. Fetch picture and fans from Deezer API
        try:
            q = urllib.parse.quote(artist_name)
            deezer_url = f"https://api.deezer.com/search/artist?q={q}"
            req = urllib.request.Request(deezer_url, headers={"User-Agent": "MyTunes/1.0"})
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=6) as res:
                data = json.loads(res.read().decode("utf-8"))
                artists = data.get("data", [])
                if artists:
                    # Choose exact name match if available, otherwise artist with highest fan count
                    best_match = None
                    exact_matches = [a for a in artists if a.get("name", "").strip().lower() == artist_name.lower()]
                    if exact_matches:
                        best_match = max(exact_matches, key=lambda a: a.get("nb_fan", 0))
                    else:
                        best_match = max(artists, key=lambda a: a.get("nb_fan", 0))

                    if best_match:
                        deezer_id = best_match.get("id")
                        picture_url = best_match.get("picture_big") or best_match.get("picture_xl") or best_match.get("picture")
                        picture_medium = best_match.get("picture_medium") or picture_url
                        nb_fan = best_match.get("nb_fan", 0)
        except Exception:
            pass

        # 2. Fetch bio from Last.fm API
        bio = ""
        try:
            q = urllib.parse.quote(artist_name)
            api_endpoint = f"http://ws.audioscrobbler.com/2.0/?method=artist.getinfo&artist={q}&api_key={LASTFM_API_KEY}&format=json"
            req = urllib.request.Request(api_endpoint, headers={"User-Agent": "MyTunes/1.0"})
            with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=5) as res:
                data = json.loads(res.read().decode("utf-8"))
                artist_data = data.get("artist", {})
                lastfm_url = artist_data.get("url")
                raw_bio = artist_data.get("bio", {}).get("content") or artist_data.get("bio", {}).get("summary") or ""
                if raw_bio:
                    # Clean out legal license boilerplate while preserving the text and Read more on Last.fm
                    clean_bio = re.sub(r'User-contributed text is available under the Creative Commons By-SA License;.*$', '', raw_bio, flags=re.IGNORECASE).strip()
                    # Strip any HTML formatting tags, preserving text
                    clean_bio = re.sub(r'<[^>]+>', '', clean_bio).strip()
                    # Ensure "Read more on Last.fm" is present at the end
                    if "Read more on Last.fm" not in clean_bio:
                        clean_bio = clean_bio.rstrip(".") + ". Read more on Last.fm."
                    bio = clean_bio
        except Exception:
            pass

        # 3. Fallback to Wikipedia API if Last.fm returned no bio
        if not bio:
            candidates = [
                artist_name,
                f"{artist_name} (band)",
                f"{artist_name} (musician)",
                f"{artist_name} (singer)",
                f"{artist_name} (group)"
            ]
            for candidate in candidates:
                try:
                    cand_q = urllib.parse.quote(candidate)
                    wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro=true&explaintext=true&titles={cand_q}&redirects=1&format=json"
                    req = urllib.request.Request(wiki_url, headers={"User-Agent": "MyTunes/1.0"})
                    with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=5) as res:
                        wdata = json.loads(res.read().decode("utf-8"))
                        pages = wdata.get("query", {}).get("pages", {})
                        found_bio = False
                        for pid, pinfo in pages.items():
                            if pid == "-1":
                                continue
                            text = pinfo.get("extract", "").strip()
                            if "commonly refers to:" in text or "may refer to:" in text:
                                continue
                            if text:
                                bio = text
                                found_bio = True
                                break
                        if found_bio:
                            break
                except Exception:
                    pass

        result = {
            "artist_name": artist_name,
            "picture_url": picture_url,
            "picture_medium": picture_medium,
            "bio": bio,
            "lastfm_url": lastfm_url,
            "nb_fan": nb_fan,
            "deezer_id": deezer_id,
            "updated_at": time.time()
        }

        # Cache to SQLite
        if self.conn:
            try:
                self.conn.execute("""
                    INSERT INTO artist_metadata (artist_name, picture_url, picture_medium, bio, lastfm_url, nb_fan, deezer_id, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(artist_name) DO UPDATE SET
                        picture_url = excluded.picture_url,
                        picture_medium = excluded.picture_medium,
                        bio = excluded.bio,
                        lastfm_url = excluded.lastfm_url,
                        nb_fan = excluded.nb_fan,
                        deezer_id = excluded.deezer_id,
                        updated_at = excluded.updated_at
                """, (artist_name, picture_url, picture_medium, bio, lastfm_url, nb_fan, deezer_id, time.time()))
                self.conn.commit()
            except Exception:
                pass

        return result
