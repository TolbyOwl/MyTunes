from __future__ import annotations
import json
import os
import platform
import time
import sqlite3
from typing import Dict, Any, Optional

SYNC_FILENAME = ".mytunes_sync.json"

class SyncManager:
    """
    Manages zero-backend cloud synchronization.
    Packs local playlists, favorites, podcasts, and radio into a structured JSON
    snapshot and performs additive/timestamp conflict-free merge with the cloud snapshot.
    """

    def __init__(self, db_conn: sqlite3.Connection):
        self.conn = db_conn

    def export_sync_snapshot(self) -> Dict[str, Any]:
        """Gathers local state into a portable JSON snapshot."""
        now = time.time()
        
        # 1. Favorites
        cursor = self.conn.execute("SELECT id, title, artist, file_path FROM tracks WHERE is_favorite = 1")
        favorites = [{"id": r["id"], "title": r["title"], "artist": r["artist"]} for r in cursor.fetchall()]

        # 2. Playlists
        p_cursor = self.conn.execute("SELECT id, name, description, created_at, updated_at FROM playlists")
        playlists = []
        for p in p_cursor.fetchall():
            t_cursor = self.conn.execute(
                """
                SELECT t.id, t.title, t.artist 
                FROM playlist_tracks pt
                JOIN tracks t ON pt.track_id = t.id
                WHERE pt.playlist_id = ?
                ORDER BY pt.position ASC
                """,
                (p["id"],)
            )
            tracks = [{"id": r["id"], "title": r["title"], "artist": r["artist"]} for r in t_cursor.fetchall()]
            playlists.append({
                "id": p["id"],
                "name": p["name"],
                "description": p["description"],
                "created_at": p["created_at"],
                "updated_at": p["updated_at"],
                "tracks": tracks
            })

        # 3. Podcasts & Progress
        pod_cursor = self.conn.execute("SELECT id, title, feed_url, date_subscribed FROM podcasts")
        podcasts = []
        for pod in pod_cursor.fetchall():
            ep_cursor = self.conn.execute(
                "SELECT id, audio_url, playback_position, is_played FROM episodes WHERE podcast_id = ? AND playback_position > 0",
                (pod["id"],)
            )
            episodes = [{
                "id": ep["id"],
                "audio_url": ep["audio_url"],
                "playback_position": ep["playback_position"],
                "is_played": bool(ep["is_played"])
            } for ep in ep_cursor.fetchall()]

            podcasts.append({
                "feed_url": pod["feed_url"],
                "title": pod["title"],
                "episodes": episodes
            })

        # 4. Radio Favorites
        radio_cursor = self.conn.execute(
            "SELECT id, name, stream_url, homepage, favicon, country, language, tags, codec, bitrate FROM radio_stations WHERE is_favorite = 1"
        )
        radio_favs = [{
            "id": r["id"],
            "name": r["name"],
            "stream_url": r["stream_url"],
            "homepage": r["homepage"] or "",
            "favicon": r["favicon"] or "",
            "country": r["country"] or "",
            "language": r["language"] or "",
            "tags": r["tags"] or "",
            "codec": r["codec"] or "",
            "bitrate": r["bitrate"] or 0
        } for r in radio_cursor.fetchall()]

        return {
            "version": 1,
            "updated_at": now,
            "device": platform.node() or "MyTunes Device",
            "favorites": favorites,
            "playlists": playlists,
            "podcasts": podcasts,
            "radio_favorites": radio_favs
        }

    def merge_sync_snapshot(self, cloud_data: Dict[str, Any]) -> None:
        """
        Merges cloud snapshot into local database using an additive union strategy
        so no favorites or playlist additions from any device are ever lost.
        """
        if not cloud_data or cloud_data.get("version") != 1:
            return

        # 1. Merge Favorites
        for fav in cloud_data.get("favorites", []):
            self.conn.execute(
                "UPDATE tracks SET is_favorite = 1 WHERE id = ? OR (title = ? AND artist = ?)",
                (fav.get("id"), fav.get("title"), fav.get("artist"))
            )

        # 2. Merge Playlists
        for p in cloud_data.get("playlists", []):
            p_id = p.get("id")
            p_name = p.get("name")
            p_desc = p.get("description", "")
            p_updated = p.get("updated_at", time.time())

            # Check if playlist exists
            cursor = self.conn.execute("SELECT id, updated_at FROM playlists WHERE id = ? OR name = ?", (p_id, p_name))
            row = cursor.fetchone()
            if not row:
                self.conn.execute(
                    "INSERT INTO playlists (id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (p_id, p_name, p_desc, p.get("created_at", time.time()), p_updated)
                )
            
            # Merge tracks into playlist
            for pos, t in enumerate(p.get("tracks", [])):
                t_match = self.conn.execute(
                    "SELECT id FROM tracks WHERE id = ? OR (title = ? AND artist = ?)",
                    (t.get("id"), t.get("title"), t.get("artist"))
                ).fetchone()
                if t_match:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
                        (p_id, t_match["id"], pos)
                    )

        # 3. Merge Radio Favorites
        for rf in cloud_data.get("radio_favorites", []):
            self.conn.execute(
                """
                INSERT INTO radio_stations (id, name, stream_url, homepage, favicon, country, language, tags, codec, bitrate, is_favorite)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(stream_url) DO UPDATE SET
                    is_favorite = 1,
                    name = COALESCE(NULLIF(excluded.name, ''), radio_stations.name),
                    favicon = COALESCE(NULLIF(excluded.favicon, ''), radio_stations.favicon),
                    country = COALESCE(NULLIF(excluded.country, ''), radio_stations.country),
                    tags = COALESCE(NULLIF(excluded.tags, ''), radio_stations.tags)
                """,
                (
                    rf.get("id"),
                    rf.get("name"),
                    rf.get("stream_url"),
                    rf.get("homepage", ""),
                    rf.get("favicon", ""),
                    rf.get("country", ""),
                    rf.get("language", ""),
                    rf.get("tags", ""),
                    rf.get("codec", ""),
                    rf.get("bitrate", 0)
                )
            )

        self.conn.commit()

    def serialize_to_json(self) -> str:
        """Exports snapshot as formatted JSON string."""
        return json.dumps(self.export_sync_snapshot(), indent=2)

    def load_from_json(self, json_str: str) -> None:
        """Parses and merges JSON string into database."""
        data = json.loads(json_str)
        self.merge_sync_snapshot(data)
