import sqlite3
import os
from typing import Optional

DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".mytunes", "mytunes.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT DEFAULT 'Unknown Artist',
    album TEXT DEFAULT 'Unknown Album',
    album_artist TEXT DEFAULT '',
    genre TEXT DEFAULT 'Unknown Genre',
    year INTEGER,
    duration REAL DEFAULT 0.0,
    track_number INTEGER,
    disc_number INTEGER DEFAULT 1,
    file_path TEXT UNIQUE NOT NULL,
    source TEXT DEFAULT 'local',
    artwork_path TEXT,
    artwork_url TEXT,
    bitrate INTEGER,
    play_count INTEGER DEFAULT 0,
    last_played REAL,
    is_favorite INTEGER DEFAULT 0,
    rating INTEGER DEFAULT 0,
    bpm REAL,
    date_added REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist);
CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album);
CREATE INDEX IF NOT EXISTS idx_tracks_favorite ON tracks(is_favorite);
CREATE INDEX IF NOT EXISTS idx_tracks_source ON tracks(source);

CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
    title, artist, album, genre, content='tracks', content_rowid='rowid'
);

-- Triggers to keep FTS index in sync
CREATE TRIGGER IF NOT EXISTS tracks_ai AFTER INSERT ON tracks BEGIN
  INSERT INTO tracks_fts(rowid, title, artist, album, genre) 
  VALUES (new.rowid, new.title, new.artist, new.album, new.genre);
END;

CREATE TRIGGER IF NOT EXISTS tracks_ad AFTER DELETE ON tracks BEGIN
  INSERT INTO tracks_fts(tracks_fts, rowid, title, artist, album, genre) 
  VALUES('delete', old.rowid, old.title, old.artist, old.album, old.genre);
END;

CREATE TRIGGER IF NOT EXISTS tracks_au AFTER UPDATE ON tracks BEGIN
  INSERT INTO tracks_fts(tracks_fts, rowid, title, artist, album, genre) 
  VALUES('delete', old.rowid, old.title, old.artist, old.album, old.genre);
  INSERT INTO tracks_fts(rowid, title, artist, album, genre) 
  VALUES (new.rowid, new.title, new.artist, new.album, new.genre);
END;

CREATE TABLE IF NOT EXISTS playlists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    is_smart INTEGER DEFAULT 0,
    smart_rules TEXT
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id TEXT NOT NULL,
    track_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (playlist_id, track_id),
    FOREIGN KEY(playlist_id) REFERENCES playlists(id) ON DELETE CASCADE,
    FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS podcasts (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT DEFAULT '',
    description TEXT DEFAULT '',
    feed_url TEXT UNIQUE NOT NULL,
    artwork_url TEXT,
    date_subscribed REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    podcast_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    audio_url TEXT NOT NULL,
    duration REAL DEFAULT 0.0,
    published_at REAL,
    playback_position REAL DEFAULT 0.0,
    is_played INTEGER DEFAULT 0,
    is_downloaded INTEGER DEFAULT 0,
    download_path TEXT,
    FOREIGN KEY(podcast_id) REFERENCES podcasts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS podcast_search_cache (
    query TEXT NOT NULL,
    result_limit INTEGER NOT NULL,
    fetched_at REAL NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY (query, result_limit)
);

CREATE TABLE IF NOT EXISTS podcast_feed_cache (
    feed_url TEXT PRIMARY KEY,
    fetched_at REAL NOT NULL,
    data_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS radio_stations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    stream_url TEXT UNIQUE NOT NULL,
    homepage TEXT DEFAULT '',
    favicon TEXT,
    country TEXT DEFAULT '',
    language TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    codec TEXT DEFAULT '',
    bitrate INTEGER DEFAULT 0,
    is_favorite INTEGER DEFAULT 0,
    last_played REAL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_synced_at REAL DEFAULT 0.0,
    sync_provider TEXT DEFAULT 'none',
    sync_file_id TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS artist_metadata (
    artist_name TEXT PRIMARY KEY,
    picture_url TEXT,
    picture_medium TEXT,
    bio TEXT,
    nb_fan INTEGER DEFAULT 0,
    deezer_id INTEGER,
    updated_at REAL NOT NULL
);
"""

def init_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Initializes and returns a SQLite database connection with full schema."""
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    
    db_dir = os.path.dirname(db_path)
    if db_dir and db_path != ":memory:":
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
