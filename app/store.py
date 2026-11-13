"""Database schema and song storage."""
import json
import os
import sqlite3
import time

import covers
import midi_info

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("KEYFALL_DATA") or os.path.join(ROOT, "data")
DB_PATH = os.path.join(DATA, "keyfall.db")
JOURNAL_MODE = "DELETE" if os.environ.get("KEYFALL_SQLITE_JOURNAL", "WAL").upper() == "DELETE" else "WAL"
DIRS = {k: os.path.join(DATA, k) for k in ("midi", "notes", "covers")}

CATEGORIES = ["Pop & Rock", "Classical", "Modern Piano", "Film & TV", "Video Games", "Other"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pass_hash BLOB NOT NULL,
    salt BLOB NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS songs (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '',
    arranger TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,              -- 'library' or 'community'
    uploader_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    path TEXT NOT NULL,                -- relative to project root
    md5 TEXT NOT NULL UNIQUE,
    size INTEGER, duration REAL, notes INTEGER, tracks INTEGER,
    nps REAL, peak_nps REAL, polyphony INTEGER, low INTEGER, high INTEGER,
    bpm REAL, key TEXT, time_sig TEXT,
    difficulty INTEGER NOT NULL,
    cover_ext TEXT,                    -- custom cover extension, NULL = generated
    downloads INTEGER NOT NULL DEFAULT 0,
    plays INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    dislikes INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0,
    rating_sum INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS votes (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    value INTEGER NOT NULL CHECK (value IN (-1, 1)),
    PRIMARY KEY (user_id, song_id)
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    stars INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    body TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE (song_id, user_id)
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES comments(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_song ON reviews(song_id);
CREATE INDEX IF NOT EXISTS idx_comments_song ON comments(song_id);
"""


def connect():
    os.makedirs(DATA, exist_ok=True)
    for d in DIRS.values():
        os.makedirs(d, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    # WAL is faster locally; network filesystems (shared hosting) are safer with DELETE.
    db.execute(f"PRAGMA journal_mode = {JOURNAL_MODE}")
    return db


# Columns added after the first release; init() adds them to older databases.
MIGRATIONS = {
    "album": "TEXT",          # album the artwork comes from
    "cover_source": "TEXT",   # NULL = generated from notes, 'upload', 'deezer' or 'itunes'
    "cover_link": "TEXT",     # page on the artwork source, for attribution
}


def init():
    db = connect()
    db.executescript(SCHEMA)
    have = {r["name"] for r in db.execute("PRAGMA table_info(songs)")}
    for col, typ in MIGRATIONS.items():
        if col not in have:
            db.execute(f"ALTER TABLE songs ADD COLUMN {col} {typ}")
    db.commit()
    return db


def cover_path(sid, ext, thumb=False):
    return os.path.join(DIRS["covers"], f"{sid}.{'thumb' if thumb else 'custom'}.{ext}")


def clear_custom_cover(sid):
    for ext in ("png", "jpg", "webp"):
        for thumb in (False, True):
            try:
                os.remove(cover_path(sid, ext, thumb))
            except FileNotFoundError:
                pass


def refresh_counts(db, song_id):
    db.execute(
        """UPDATE songs SET
            likes = (SELECT COUNT(*) FROM votes WHERE song_id = :id AND value = 1),
            dislikes = (SELECT COUNT(*) FROM votes WHERE song_id = :id AND value = -1),
            review_count = (SELECT COUNT(*) FROM reviews WHERE song_id = :id),
            rating_sum = (SELECT COALESCE(SUM(stars), 0) FROM reviews WHERE song_id = :id),
            comment_count = (SELECT COUNT(*) FROM comments WHERE song_id = :id)
           WHERE id = :id""",
        {"id": song_id},
    )


class Duplicate(Exception):
    def __init__(self, song_id):
        super().__init__(song_id)
        self.song_id = song_id


def add_song(db, raw, meta, source, uploader_id=None, path=None):
    """Validate + analyse MIDI bytes and insert a song. Returns the new id.

    meta: title, artist, version, arranger, category, description, tags
    path: existing file (library import); otherwise bytes are written to data/midi.
    """
    data, stats, playback = midi_info.parse(raw)
    row = db.execute("SELECT id FROM songs WHERE md5 = ?", (stats["md5"],)).fetchone()
    if row:
        raise Duplicate(row["id"])
    cur = db.execute(
        """INSERT INTO songs (title, artist, version, arranger, category, description, tags, source,
               uploader_id, path, md5, size, duration, notes, tracks, nps, peak_nps, polyphony, low, high,
               bpm, key, time_sig, difficulty, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            meta["title"], meta["artist"], meta.get("version", ""), meta.get("arranger", ""),
            meta.get("category", "Other"), meta.get("description", ""), meta.get("tags", ""), source,
            uploader_id, "", stats["md5"], stats["size"], stats["duration"], stats["notes"], stats["tracks"],
            stats["nps"], stats["peak_nps"], stats["polyphony"], stats["low"], stats["high"], stats["bpm"],
            stats["key"], stats["time_sig"], stats["difficulty"], int(meta.get("created_at", time.time())),
        ),
    )
    sid = cur.lastrowid
    if path is None or data is not raw:  # uploads, or RMID that had to be unwrapped
        rel = os.path.join("data", "midi", f"{sid}.mid")
        with open(os.path.join(ROOT, rel), "wb") as f:
            f.write(data)
    else:
        rel = os.path.relpath(path, ROOT)
    db.execute("UPDATE songs SET path = ? WHERE id = ?", (rel, sid))
    with open(os.path.join(DIRS["notes"], f"{sid}.json"), "w") as f:
        json.dump(playback, f, separators=(",", ":"))
    with open(os.path.join(DIRS["covers"], f"{sid}.svg"), "w") as f:
        f.write(covers.render(playback))
    return sid


def delete_song_files(song):
    sid = song["id"]
    paths = [os.path.join(DIRS["notes"], f"{sid}.json"), os.path.join(DIRS["covers"], f"{sid}.svg")]
    clear_custom_cover(sid)
    if song["source"] == "community":
        paths.append(os.path.join(ROOT, song["path"]))
    for p in paths:
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
