from __future__ import annotations
import os
import hashlib
import sqlite3
import time
from typing import List, Optional, Callable
import mutagen
from mutagen.id3 import ID3, APIC
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4
from mytunes.models.track import Track
from mytunes.models.schema import DEFAULT_DB_PATH

SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav"}
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".mytunes", "art_cache")

class LocalProvider:
    """Scans local directories for audio files and extracts metadata & embedded art."""

    def __init__(self, db_conn: sqlite3.Connection):
        self.conn = db_conn
        os.makedirs(CACHE_DIR, exist_ok=True)

    def scan_directory(
        self,
        directory: str,
        on_progress: Optional[Callable[[int, str], None]] = None
    ) -> List[Track]:
        """Recursively scans a directory and updates the database."""
        tracks: List[Track] = []
        count = 0

        for root, _, files in os.walk(directory):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in SUPPORTED_EXTENSIONS:
                    file_path = os.path.join(root, file)
                    track = self.parse_file(file_path)
                    if track:
                        self.save_track(track)
                        tracks.append(track)
                        count += 1
                        if on_progress:
                            on_progress(count, track.title)

        self.conn.commit()
        return tracks

    def parse_file(self, file_path: str) -> Optional[Track]:
        """Extracts metadata and embedded cover art from an audio file."""
        try:
            audio = mutagen.File(file_path)
            if audio is None:
                return None

            filename = os.path.splitext(os.path.basename(file_path))[0]
            track_id = hashlib.md5(file_path.encode("utf-8")).hexdigest()

            # Default values
            title = filename
            artist = "Unknown Artist"
            album = "Unknown Album"
            album_artist = ""
            composer = ""
            genre = "Unknown Genre"
            year: Optional[int] = None
            duration = float(getattr(audio.info, "length", 0.0))
            track_number: Optional[int] = None
            disc_number: Optional[int] = 1
            bitrate: Optional[int] = getattr(audio.info, "bitrate", None)
            artwork_path: Optional[str] = None

            # Extract tags based on format
            if hasattr(audio, "tags") and audio.tags:
                tags = audio.tags

                # ID3 (MP3)
                if isinstance(tags, ID3):
                    if "TIT2" in tags:
                        title = str(tags["TIT2"])
                    if "TPE1" in tags:
                        artist = str(tags["TPE1"])
                    if "TALB" in tags:
                        album = str(tags["TALB"])
                    if "TPE2" in tags:
                        album_artist = str(tags["TPE2"])
                    if "TCON" in tags:
                        genre = str(tags["TCON"])
                    if "TDRC" in tags:
                        try:
                            year = int(str(tags["TDRC"])[:4])
                        except ValueError:
                            pass
                    if "TRCK" in tags:
                        try:
                            trck = str(tags["TRCK"]).split("/")[0]
                            track_number = int(trck)
                        except ValueError:
                            pass
                    if "TPOS" in tags:
                        try:
                            d_val = str(tags["TPOS"]).split("/")[0]
                            disc_number = int(d_val)
                        except ValueError:
                            pass
                    if "TCOM" in tags:
                        try:
                            composer = str(tags["TCOM"])
                        except Exception:
                            pass

                    # Extract APIC artwork
                    for tag in tags.values():
                        if isinstance(tag, APIC):
                            artwork_path = self._save_art(tag.data, track_id)
                            break

                # FLAC / OGG
                elif isinstance(audio, FLAC) or hasattr(audio, "pictures"):
                    title = tags.get("title", [title])[0]
                    artist = tags.get("artist", [artist])[0]
                    album = tags.get("album", [album])[0]
                    album_artist = tags.get("albumartist", [""])[0]
                    genre = tags.get("genre", [genre])[0]
                    composer = tags.get("composer", [""])[0]
                    date_val = tags.get("date", [None])[0]
                    if date_val:
                        try:
                            year = int(str(date_val)[:4])
                        except ValueError:
                            pass
                    trck_val = tags.get("tracknumber", [None])[0]
                    if trck_val:
                        try:
                            track_number = int(str(trck_val).split("/")[0])
                        except ValueError:
                            pass
                    disc_val = tags.get("discnumber", [None])[0]
                    if disc_val:
                        try:
                            disc_number = int(str(disc_val).split("/")[0])
                        except ValueError:
                            pass

                    # Extract picture from FLAC
                    if hasattr(audio, "pictures") and audio.pictures:
                        artwork_path = self._save_art(audio.pictures[0].data, track_id)

                # MP4 / M4A / AAC
                elif isinstance(audio, MP4):
                    title = tags.get("\xa9nam", [title])[0]
                    artist = tags.get("\xa9ART", [artist])[0]
                    album = tags.get("\xa9alb", [album])[0]
                    album_artist = tags.get("aART", [""])[0]
                    genre = tags.get("\xa9gen", [genre])[0]
                    composer = tags.get("\xa9wrt", [""])[0]
                    date_val = tags.get("\xa9day", [None])[0]
                    if date_val:
                        try:
                            year = int(str(date_val)[:4])
                        except ValueError:
                            pass
                    if "trkn" in tags and tags["trkn"]:
                        track_number = tags["trkn"][0][0]
                    if "disk" in tags and tags["disk"]:
                        disc_number = tags["disk"][0][0]
                    if "covr" in tags and tags["covr"]:
                        artwork_path = self._save_art(bytes(tags["covr"][0]), track_id)

            return Track(
                id=track_id,
                title=title,
                artist=artist,
                album=album,
                album_artist=album_artist,
                genre=genre,
                year=year,
                duration=duration,
                track_number=track_number,
                disc_number=disc_number,
                file_path=file_path,
                source="local",
                artwork_path=artwork_path,
                bitrate=bitrate,
                date_added=time.time()
            )
        except Exception:
            return None

    def _save_art(self, art_data: bytes, track_id: str) -> Optional[str]:
        """Caches album cover artwork to disk."""
        try:
            art_file = os.path.join(CACHE_DIR, f"{track_id}.jpg")
            with open(art_file, "wb") as f:
                f.write(art_data)
            return art_file
        except Exception:
            return None

    def save_track(self, track: Track) -> None:
        """Upserts a track into the SQLite database."""
        sql = """
        INSERT INTO tracks (
            id, title, artist, album, album_artist, genre, year,
            duration, track_number, disc_number, file_path, source,
            artwork_path, artwork_url, bitrate, play_count, last_played,
            is_favorite, rating, bpm, date_added
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_path) DO UPDATE SET
            title=excluded.title,
            artist=excluded.artist,
            album=excluded.album,
            genre=excluded.genre,
            year=excluded.year,
            duration=excluded.duration,
            track_number=excluded.track_number,
            artwork_path=COALESCE(excluded.artwork_path, tracks.artwork_path)
        """
        self.conn.execute(sql, (
            track.id, track.title, track.artist, track.album, track.album_artist,
            track.genre, track.year, track.duration, track.track_number,
            track.disc_number, track.file_path, track.source, track.artwork_path,
            track.artwork_url, track.bitrate, track.play_count, track.last_played,
            1 if track.is_favorite else 0, track.rating, track.bpm, track.date_added
        ))

    def get_all_tracks(self) -> List[Track]:
        """Loads all tracks from database."""
        cursor = self.conn.execute("SELECT * FROM tracks ORDER BY artist, album, track_number, title")
        tracks = []
        for row in cursor.fetchall():
            tracks.append(Track(
                id=row["id"],
                title=row["title"],
                artist=row["artist"],
                album=row["album"],
                album_artist=row["album_artist"] or "",
                genre=row["genre"] or "Unknown Genre",
                year=row["year"],
                duration=row["duration"] or 0.0,
                track_number=row["track_number"],
                disc_number=row["disc_number"] or 1,
                file_path=row["file_path"],
                source=row["source"] or "local",
                artwork_path=row["artwork_path"],
                artwork_url=row["artwork_url"],
                bitrate=row["bitrate"],
                play_count=row["play_count"] or 0,
                last_played=row["last_played"],
                is_favorite=bool(row["is_favorite"]),
                rating=row["rating"] or 0,
                bpm=row["bpm"],
                date_added=row["date_added"]
            ))
        return tracks

    def search_tracks(self, query: str) -> List[Track]:
        """Performs full-text search across library."""
        if not query.strip():
            return self.get_all_tracks()

        sql = """
        SELECT t.* FROM tracks t
        JOIN tracks_fts fts ON t.rowid = fts.rowid
        WHERE tracks_fts MATCH ?
        ORDER BY rank
        """
        # FTS5 search query formatting
        clean_query = " ".join([f'"{term}*"' for term in query.split() if term])
        try:
            cursor = self.conn.execute(sql, (clean_query,))
            tracks = []
            for row in cursor.fetchall():
                tracks.append(Track(
                    id=row["id"],
                    title=row["title"],
                    artist=row["artist"],
                    album=row["album"],
                    album_artist=row["album_artist"] or "",
                    genre=row["genre"] or "Unknown Genre",
                    year=row["year"],
                    duration=row["duration"] or 0.0,
                    track_number=row["track_number"],
                    disc_number=row["disc_number"] or 1,
                    file_path=row["file_path"],
                    source=row["source"] or "local",
                    artwork_path=row["artwork_path"],
                    artwork_url=row["artwork_url"],
                    bitrate=row["bitrate"],
                    play_count=row["play_count"] or 0,
                    last_played=row["last_played"],
                    is_favorite=bool(row["is_favorite"]),
                    rating=row["rating"] or 0,
                    bpm=row["bpm"],
                    date_added=row["date_added"]
                ))
            return tracks
        except sqlite3.OperationalError:
            # Fallback to simple LIKE if FTS expression is invalid
            sql_fallback = "SELECT * FROM tracks WHERE title LIKE ? OR artist LIKE ? OR album LIKE ?"
            param = f"%{query}%"
            cursor = self.conn.execute(sql_fallback, (param, param, param))
            return [Track(
                id=r["id"], title=r["title"], artist=r["artist"], album=r["album"],
                file_path=r["file_path"], duration=r["duration"] or 0.0,
                artwork_path=r["artwork_path"], is_favorite=bool(r["is_favorite"])
            ) for r in cursor.fetchall()]
