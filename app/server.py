"""Keyfall — a song library for falling-notes piano players.

Run:  python3 -I app/server.py [--host 127.0.0.1] [--port 8080]
"""
import argparse
import base64
import binascii
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import traceback
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import midi_info  # noqa: E402
import store  # noqa: E402

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
MAX_BODY = 8 * 1024 * 1024
MAX_MIDI = 2 * 1024 * 1024
MAX_COVER = 2 * 1024 * 1024
SESSION_DAYS = 30
PBKDF2_ROUNDS = 200_000
# Set KEYFALL_TRUST_PROXY=1 when running behind a reverse proxy (PythonAnywhere, nginx):
# then X-Real-IP / X-Forwarded-Proto are trusted for rate limiting and Secure cookies.
TRUST_PROXY = os.environ.get("KEYFALL_TRUST_PROXY") == "1"

SORTS = {
    "title": "s.title COLLATE NOCASE",
    "artist": "s.artist COLLATE NOCASE",
    "newest": "s.created_at",
    "rating": "(s.rating_sum + 6.0) / (s.review_count + 2.0)",  # Bayesian average, prior = 3★ x 2
    "likes": "(s.likes - s.dislikes)",
    "downloads": "s.downloads",
    "plays": "s.plays",
    "difficulty": "s.difficulty",
    "duration": "s.duration",
}
DEFAULT_DIR = {"title": "asc", "artist": "asc", "difficulty": "asc", "duration": "asc"}
LEVEL_RANGES = {name.lower(): (lo, cap) for (lo, (cap, name)) in
                zip([0] + [c for c, _ in midi_info.LEVELS[:-1]], midi_info.LEVELS)}
IMAGE_MAGIC = [(b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg")]

_login_attempts = {}
_lock = threading.Lock()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)


def clean_text(value, field, max_len, required=False, multiline=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ApiError(400, f"{field} must be text")
    value = value.replace("\r\n", "\n")
    value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", value)
    if not multiline:
        value = re.sub(r"\s+", " ", value)
    value = value.strip()
    if required and not value:
        raise ApiError(400, f"{field} is required")
    if len(value) > max_len:
        raise ApiError(400, f"{field} is too long (max {max_len} characters)")
    return value


def clean_tags(value):
    if isinstance(value, list):
        value = ",".join(str(v) for v in value)
    value = clean_text(value, "Tags", 200)
    tags = []
    for t in value.split(","):
        t = t.strip()[:24]
        if t and t.lower() not in (x.lower() for x in tags):
            tags.append(t)
    return ",".join(tags[:8])


def decode_b64(value, field, limit):
    if not isinstance(value, str) or not value:
        raise ApiError(400, f"{field} is missing")
    if "," in value[:100] and value.startswith("data:"):
        value = value.split(",", 1)[1]
    if len(value) > limit * 4 // 3 + 16:
        raise ApiError(413, f"{field} is too large (max {limit // 1024 // 1024} MB)")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(400, f"{field} is not valid base64")


def image_ext(data):
    for magic, ext in IMAGE_MAGIC:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise ApiError(400, "Cover must be a PNG, JPEG or WebP image")


def song_json(row, user=None):
    d = dict(row)
    d.pop("path", None)
    d.pop("md5", None)
    d["level"] = midi_info.level(d["difficulty"])
    d["rating"] = round(d["rating_sum"] / d["review_count"], 2) if d["review_count"] else None
    d["tags"] = [t for t in d["tags"].split(",") if t]
    d["range"] = f"{midi_info.note_name(d['low'])}–{midi_info.note_name(d['high'])}"
    base = f"/api/songs/{d['id']}/cover"
    if d["cover_ext"]:
        v = f"v={d['cover_source'] or 'upload'}.{d['cover_ext']}"
        d["cover"], d["thumb"] = f"{base}?{v}", f"{base}?{v}&size=thumb"
    else:
        d["cover"] = d["thumb"] = base
    d["custom_cover"] = bool(d.pop("cover_ext", None))
    d.pop("rating_sum", None)
    d["uploader"] = d.pop("uploader_name", None)
    return d


def download_name(song):
    name = f"{song['artist']} - {song['title']}"
    if song["version"]:
        name += f" ({song['version']})"
    return re.sub(r'[\\/:*?"<>|]+', "", name)[:150] + ".mid"


class Handler(BaseHTTPRequestHandler):
    server_version = "Keyfall/1.0"
    protocol_version = "HTTP/1.1"

    # ---------------------------------------------------------------- plumbing
    def log_message(self, fmt, *args):
        if not getattr(self.server, "quiet", False):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _headers(self, status, ctype, length, extra=None):
        """Queue a response; it is written by flush() after the DB transaction commits."""
        self._pending = (status, ctype, length, extra)

    def response_headers(self):
        status, ctype, length, extra = self._pending
        headers = [
            ("Content-Type", ctype),
            ("Content-Length", str(length)),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "same-origin"),
            ("X-Frame-Options", "DENY"),
            ("Content-Security-Policy",
             "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
             "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"),
        ]
        if self.is_https():
            headers.append(("Strict-Transport-Security", "max-age=15552000"))
        headers += list((extra or {}).items())
        return status, headers

    def flush(self):
        status, headers = self.response_headers()
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD" and self._pending_body:
            self.wfile.write(self._pending_body)

    def is_https(self):
        return TRUST_PROXY and self.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def client_ip(self):
        if TRUST_PROXY:
            ip = self.headers.get("X-Real-IP") or self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            if ip:
                return ip
        return self.client_address[0]

    def send_json(self, obj, status=200, extra=None):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self._headers(status, "application/json; charset=utf-8", len(body),
                      {"Cache-Control": "no-store", **(extra or {})})
        self._pending_body = body

    def send_file(self, path, ctype=None, extra=None):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except (FileNotFoundError, IsADirectoryError):
            raise ApiError(404, "Not found")
        ctype = ctype or mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self._headers(200, ctype, len(body), extra)
        self._pending_body = body

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "Request too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise ApiError(400, "Invalid JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "Expected a JSON object")
        return data

    def current_user(self):
        if hasattr(self, "_user"):
            return self._user
        self._user = None
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get("kf_session")
        if token:
            row = self.db.execute(
                """SELECT u.id, u.username, u.is_admin, s.created_at FROM sessions s
                   JOIN users u ON u.id = s.user_id WHERE s.token = ?""",
                (token.value,),
            ).fetchone()
            if row and row["created_at"] > time.time() - SESSION_DAYS * 86400:
                self._user = {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}
        return self._user

    def require_user(self):
        user = self.current_user()
        if not user:
            raise ApiError(401, "Sign in to do that")
        return user

    def dispatch(self, method):
        # The handler object is reused for every request on a keep-alive connection,
        # so per-request state must be reset here.
        self.__dict__.pop("_user", None)
        self._pending = self._pending_body = None
        url = urlparse(self.path)
        self.query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        path = url.path
        self.db = store.connect()
        try:
            if path.startswith("/api/"):
                if method not in ("GET", "HEAD") and self.headers.get("X-Requested-With") != "keyfall":
                    raise ApiError(403, "Missing request header")  # CSRF guard: forces a CORS preflight
                for pattern, verb, fn in ROUTES:
                    m = pattern.fullmatch(path)
                    if m and verb == method:
                        fn(self, *m.groups())
                        self.db.commit()
                        self.flush()
                        return
                raise ApiError(404, "Unknown endpoint")
            if method not in ("GET", "HEAD"):
                raise ApiError(405, "Method not allowed")
            self.serve_static(path)
            self.flush()
        except ApiError as e:
            self.db.rollback()
            self.close_connection = True  # request body may be unread
            self.send_json({"error": e.message}, e.status)
            self.flush()
        except Exception:
            self.db.rollback()
            self.close_connection = True
            traceback.print_exc()
            self.send_json({"error": "Internal server error"}, 500)
            self.flush()
        finally:
            self.db.close()

    def do_GET(self):
        self.dispatch("GET")

    def do_HEAD(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PATCH(self):
        self.dispatch("PATCH")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def serve_static(self, path):
        if path in ("/", "") or not os.path.splitext(path)[1]:
            path = "/index.html"  # SPA fallback
        full = os.path.realpath(os.path.join(WEB, path.lstrip("/")))
        if not full.startswith(os.path.realpath(WEB) + os.sep):
            raise ApiError(404, "Not found")
        self.send_file(full, extra={"Cache-Control": "no-cache"})

    def get_song(self, sid):
        row = self.db.execute(
            """SELECT s.*, u.username AS uploader_name FROM songs s
               LEFT JOIN users u ON u.id = s.uploader_id WHERE s.id = ?""",
            (int(sid),),
        ).fetchone()
        if not row:
            raise ApiError(404, "Song not found")
        return row

    def can_edit(self, user, owner_id):
        return user and (user["is_admin"] or user["id"] == owner_id)

    # ---------------------------------------------------------------- auth
    def start_session(self, user_id):
        token = secrets.token_urlsafe(32)
        self.db.execute("INSERT INTO sessions VALUES (?,?,?)", (token, user_id, int(time.time())))
        return {"Set-Cookie": f"kf_session={token}; HttpOnly; SameSite=Lax; Path=/; "
                              f"Max-Age={SESSION_DAYS * 86400}{self.secure_flag()}"}

    def secure_flag(self):
        return "; Secure" if self.is_https() else ""

    def api_register(self):
        data = self.read_json()
        username = clean_text(data.get("username"), "Username", 24, required=True)
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,24}", username):
            raise ApiError(400, "Username: 3–24 letters, numbers, dots, dashes or underscores")
        password = data.get("password") or ""
        if not isinstance(password, str) or len(password) < 8 or len(password) > 200:
            raise ApiError(400, "Password must be at least 8 characters")
        if self.db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise ApiError(409, "That username is taken")
        salt = secrets.token_bytes(16)
        first = self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        try:
            cur = self.db.execute(
                "INSERT INTO users (username, pass_hash, salt, is_admin, created_at) VALUES (?,?,?,?,?)",
                (username, hash_password(password, salt), salt, int(first), int(time.time())),
            )
        except sqlite3.IntegrityError:
            raise ApiError(409, "That username is taken")
        cookie = self.start_session(cur.lastrowid)
        self.send_json({"user": {"id": cur.lastrowid, "username": username, "is_admin": first}}, 201, cookie)

    def api_login(self):
        ip = self.client_ip()
        now = time.time()
        with _lock:
            attempts = [t for t in _login_attempts.get(ip, []) if t > now - 300]
            _login_attempts[ip] = attempts
            if len(attempts) >= 10:
                raise ApiError(429, "Too many attempts — try again in a few minutes")
        data = self.read_json()
        username = str(data.get("username") or "")
        password = str(data.get("password") or "")
        row = self.db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row or not hmac.compare_digest(hash_password(password, row["salt"]), row["pass_hash"]):
            with _lock:
                _login_attempts.setdefault(ip, []).append(now)
            raise ApiError(401, "Wrong username or password")
        cookie = self.start_session(row["id"])
        self.send_json({"user": {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}},
                       200, cookie)

    def api_logout(self):
        token = SimpleCookie(self.headers.get("Cookie", "")).get("kf_session")
        if token:
            self.db.execute("DELETE FROM sessions WHERE token = ?", (token.value,))
        self.send_json({"ok": True}, 200,
                       {"Set-Cookie": f"kf_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0{self.secure_flag()}"})

    def api_me(self):
        self.send_json({"user": self.current_user()})

    # ---------------------------------------------------------------- songs
    def api_meta(self):
        cats = self.db.execute("SELECT category, COUNT(*) n FROM songs GROUP BY category").fetchall()
        counts = {r["category"]: r["n"] for r in cats}
        src = {r["source"]: r["n"] for r in self.db.execute("SELECT source, COUNT(*) n FROM songs GROUP BY source")}
        self.send_json({
            "categories": [{"name": c, "count": counts.get(c, 0)} for c in store.CATEGORIES],
            "levels": [name for _, name in midi_info.LEVELS],
            "sources": src,
            "total": sum(counts.values()),
            "user": self.current_user(),
        })

    def api_songs(self):
        q = self.query
        where, args = [], []
        text = (q.get("q") or "").strip()[:100]
        for word in text.split():
            where.append("(s.title LIKE ? ESCAPE '\\' OR s.artist LIKE ? ESCAPE '\\' OR s.arranger LIKE ? "
                         "ESCAPE '\\' OR s.tags LIKE ? ESCAPE '\\' OR s.version LIKE ? ESCAPE '\\')")
            like = "%" + re.sub(r"([\\%_])", r"\\\1", word) + "%"
            args += [like] * 5
        if q.get("category") in store.CATEGORIES:
            where.append("s.category = ?")
            args.append(q["category"])
        if q.get("source") in ("library", "community"):
            where.append("s.source = ?")
            args.append(q["source"])
        if q.get("uploader"):
            where.append("u.username = ?")
            args.append(q["uploader"][:24])
        lv = LEVEL_RANGES.get((q.get("level") or "").lower())
        if lv:
            where.append("s.difficulty >= ? AND s.difficulty < ?")
            args += list(lv)
        sort = q.get("sort") if q.get("sort") in SORTS else "title"
        direction = q.get("dir") if q.get("dir") in ("asc", "desc") else DEFAULT_DIR.get(sort, "desc")
        try:
            limit = min(max(int(q.get("limit", 40)), 1), 100)
            offset = max(int(q.get("offset", 0)), 0)
        except ValueError:
            raise ApiError(400, "Bad paging parameters")
        sql_where = ("WHERE " + " AND ".join(where)) if where else ""
        base = f"FROM songs s LEFT JOIN users u ON u.id = s.uploader_id {sql_where}"
        total = self.db.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
        rows = self.db.execute(
            f"SELECT s.*, u.username AS uploader_name {base} "
            f"ORDER BY {SORTS[sort]} {direction}, s.title COLLATE NOCASE ASC, s.id ASC LIMIT ? OFFSET ?",
            args + [limit, offset],
        ).fetchall()
        self.send_json({"total": total, "offset": offset, "songs": [song_json(r) for r in rows]})

    def api_song(self, sid):
        row = self.get_song(sid)
        d = song_json(row)
        user = self.current_user()
        d["my_vote"] = 0
        d["can_edit"] = bool(self.can_edit(user, row["uploader_id"]))
        if user:
            v = self.db.execute("SELECT value FROM votes WHERE user_id = ? AND song_id = ?",
                                (user["id"], row["id"])).fetchone()
            d["my_vote"] = v["value"] if v else 0
        hist = self.db.execute(
            "SELECT stars, COUNT(*) n FROM reviews WHERE song_id = ? GROUP BY stars", (row["id"],)).fetchall()
        d["histogram"] = {str(i): 0 for i in range(1, 6)} | {str(r["stars"]): r["n"] for r in hist}
        # Other arrangements of the same piece
        others = self.db.execute(
            """SELECT s.*, NULL AS uploader_name FROM songs s WHERE s.id != ? AND s.title = ? COLLATE NOCASE
               AND s.artist = ? COLLATE NOCASE ORDER BY s.difficulty LIMIT 8""",
            (row["id"], row["title"], row["artist"]),
        ).fetchall()
        d["versions"] = [song_json(r) for r in others]
        self.send_json(d)

    def api_notes(self, sid):
        self.get_song(sid)
        self.send_file(os.path.join(store.DIRS["notes"], f"{int(sid)}.json"), "application/json",
                       {"Cache-Control": "public, max-age=86400"})

    def api_cover(self, sid):
        row = self.get_song(sid)
        if row["cover_ext"]:
            ext = row["cover_ext"]
            path = store.cover_path(row["id"], ext)
            thumb = store.cover_path(row["id"], ext, thumb=True)
            if self.query.get("size") == "thumb" and os.path.exists(thumb):
                path = thumb
            ctype = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[ext]
        else:
            path = os.path.join(store.DIRS["covers"], f"{row['id']}.svg")
            ctype = "image/svg+xml"
        self.send_file(path, ctype, {"Cache-Control": "public, max-age=3600"})

    def api_download(self, sid):
        row = self.get_song(sid)
        self.db.execute("UPDATE songs SET downloads = downloads + 1 WHERE id = ?", (row["id"],))
        self.db.commit()
        name = download_name(row)
        ascii_name = name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "")
        self.send_file(os.path.join(store.ROOT, row["path"]), "audio/midi", {
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}",
            "Cache-Control": "no-store",
        })

    def api_play(self, sid):
        row = self.get_song(sid)
        self.db.execute("UPDATE songs SET plays = plays + 1 WHERE id = ?", (row["id"],))
        self.send_json({"plays": row["plays"] + 1})

    def song_meta_from(self, data, partial=False):
        meta = {}
        fields = [("title", 120, True), ("artist", 120, True), ("version", 40, False), ("arranger", 80, False)]
        for name, limit, req in fields:
            if not partial or name in data:
                meta[name] = clean_text(data.get(name), name.capitalize(), limit, required=req)
        if not partial or "description" in data:
            meta["description"] = clean_text(data.get("description"), "Description", 2000, multiline=True)
        if not partial or "tags" in data:
            meta["tags"] = clean_tags(data.get("tags", ""))
        if not partial or "category" in data:
            cat = data.get("category") or "Other"
            if cat not in store.CATEGORIES:
                raise ApiError(400, "Unknown category")
            meta["category"] = cat
        return meta

    @staticmethod
    def parse_cover(b64):
        img = decode_b64(b64, "Cover image", MAX_COVER)
        return img, image_ext(img)

    def save_cover(self, sid, cover):
        img, ext = cover
        store.clear_custom_cover(sid)
        with open(store.cover_path(sid, ext), "wb") as f:
            f.write(img)
        self.db.execute("UPDATE songs SET cover_ext = ?, cover_source = 'upload', album = NULL, cover_link = NULL "
                        "WHERE id = ?", (ext, sid))

    def api_upload(self):
        user = self.require_user()
        data = self.read_json()
        meta = self.song_meta_from(data)
        raw = decode_b64(data.get("midi"), "MIDI file", MAX_MIDI)
        cover = self.parse_cover(data["cover"]) if data.get("cover") else None
        try:
            sid = store.add_song(self.db, raw, meta, "community", uploader_id=user["id"])
        except store.Duplicate as e:
            raise ApiError(409, f"This exact file is already in the library (song #{e.song_id})")
        except midi_info.MidiError as e:
            raise ApiError(400, str(e))
        if cover:
            self.save_cover(sid, cover)
        self.send_json({"id": sid}, 201)

    def api_edit_song(self, sid):
        user = self.require_user()
        row = self.get_song(sid)
        if not self.can_edit(user, row["uploader_id"]):
            raise ApiError(403, "Only the uploader can edit this song")
        data = self.read_json()
        meta = self.song_meta_from(data, partial=True)
        cover = self.parse_cover(data["cover"]) if data.get("cover") else None
        if meta:
            cols = ", ".join(f"{k} = ?" for k in meta)
            self.db.execute(f"UPDATE songs SET {cols} WHERE id = ?", list(meta.values()) + [row["id"]])
        if cover:
            self.save_cover(row["id"], cover)
        elif data.get("remove_cover") and row["cover_ext"]:
            store.clear_custom_cover(row["id"])
            self.db.execute("UPDATE songs SET cover_ext = NULL, cover_source = NULL, album = NULL, cover_link = NULL "
                            "WHERE id = ?", (row["id"],))
        self.api_song(sid)

    def api_delete_song(self, sid):
        user = self.require_user()
        row = self.get_song(sid)
        if not self.can_edit(user, row["uploader_id"]):
            raise ApiError(403, "Only the uploader can delete this song")
        self.db.execute("DELETE FROM songs WHERE id = ?", (row["id"],))
        self.db.commit()
        store.delete_song_files(row)
        self.send_json({"ok": True})

    # ---------------------------------------------------------------- votes, reviews, comments
    def api_vote(self, sid):
        user = self.require_user()
        row = self.get_song(sid)
        value = self.read_json().get("value")
        if value not in (-1, 0, 1):
            raise ApiError(400, "value must be -1, 0 or 1")
        if value == 0:
            self.db.execute("DELETE FROM votes WHERE user_id = ? AND song_id = ?", (user["id"], row["id"]))
        else:
            self.db.execute(
                "INSERT INTO votes VALUES (?,?,?) ON CONFLICT(user_id, song_id) DO UPDATE SET value = excluded.value",
                (user["id"], row["id"], value))
        store.refresh_counts(self.db, row["id"])
        r = self.db.execute("SELECT likes, dislikes FROM songs WHERE id = ?", (row["id"],)).fetchone()
        self.send_json({"likes": r["likes"], "dislikes": r["dislikes"], "my_vote": value})

    def api_reviews(self, sid):
        row = self.get_song(sid)
        user = self.current_user()
        rows = self.db.execute(
            """SELECT r.id, r.stars, r.body, r.created_at, r.updated_at, r.user_id, u.username
               FROM reviews r JOIN users u ON u.id = r.user_id WHERE r.song_id = ?
               ORDER BY r.updated_at DESC""", (row["id"],)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["mine"] = bool(user and user["id"] == r["user_id"])
            d["can_delete"] = bool(self.can_edit(user, r["user_id"]))
            d.pop("user_id")
            out.append(d)
        self.send_json({"reviews": out})

    def api_add_review(self, sid):
        user = self.require_user()
        row = self.get_song(sid)
        data = self.read_json()
        stars = data.get("stars")
        if not isinstance(stars, int) or not 1 <= stars <= 5:
            raise ApiError(400, "Pick a rating from 1 to 5 stars")
        body = clean_text(data.get("body"), "Review", 3000, multiline=True)
        now = int(time.time())
        self.db.execute(
            """INSERT INTO reviews (song_id, user_id, stars, body, created_at, updated_at) VALUES (?,?,?,?,?,?)
               ON CONFLICT(song_id, user_id) DO UPDATE SET stars = excluded.stars, body = excluded.body,
               updated_at = excluded.updated_at""",
            (row["id"], user["id"], stars, body, now, now))
        store.refresh_counts(self.db, row["id"])
        self.api_reviews(sid)

    def api_delete_review(self, rid):
        user = self.require_user()
        r = self.db.execute("SELECT * FROM reviews WHERE id = ?", (int(rid),)).fetchone()
        if not r:
            raise ApiError(404, "Review not found")
        if not self.can_edit(user, r["user_id"]):
            raise ApiError(403, "Not your review")
        self.db.execute("DELETE FROM reviews WHERE id = ?", (r["id"],))
        store.refresh_counts(self.db, r["song_id"])
        self.send_json({"ok": True})

    def api_comments(self, sid):
        row = self.get_song(sid)
        user = self.current_user()
        rows = self.db.execute(
            """SELECT c.id, c.parent_id, c.body, c.created_at, c.user_id, u.username,
                      (c.user_id = ?) AS by_uploader
               FROM comments c JOIN users u ON u.id = c.user_id WHERE c.song_id = ?
               ORDER BY c.created_at ASC""", (row["uploader_id"] or -1, row["id"])).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["can_delete"] = bool(self.can_edit(user, r["user_id"]))
            d["by_uploader"] = bool(d["by_uploader"])
            d.pop("user_id")
            out.append(d)
        self.send_json({"comments": out})

    def api_add_comment(self, sid):
        user = self.require_user()
        row = self.get_song(sid)
        data = self.read_json()
        body = clean_text(data.get("body"), "Comment", 2000, required=True, multiline=True)
        parent = data.get("parent_id")
        if parent is not None:
            p = self.db.execute("SELECT id, parent_id FROM comments WHERE id = ? AND song_id = ?",
                                (parent if isinstance(parent, int) else -1, row["id"])).fetchone()
            if not p:
                raise ApiError(400, "The comment you replied to no longer exists")
            parent = p["parent_id"] or p["id"]  # keep threads one level deep
        self.db.execute("INSERT INTO comments (song_id, user_id, parent_id, body, created_at) VALUES (?,?,?,?,?)",
                        (row["id"], user["id"], parent, body, int(time.time())))
        store.refresh_counts(self.db, row["id"])
        self.api_comments(sid)

    def api_delete_comment(self, cid):
        user = self.require_user()
        c = self.db.execute("SELECT * FROM comments WHERE id = ?", (int(cid),)).fetchone()
        if not c:
            raise ApiError(404, "Comment not found")
        if not self.can_edit(user, c["user_id"]):
            raise ApiError(403, "Not your comment")
        self.db.execute("DELETE FROM comments WHERE id = ?", (c["id"],))
        store.refresh_counts(self.db, c["song_id"])
        self.send_json({"ok": True})


def _r(pattern):
    return re.compile(pattern.replace("{id}", r"(\d{1,9})"))


ROUTES = [
    (_r("/api/meta"), "GET", Handler.api_meta),
    (_r("/api/auth/me"), "GET", Handler.api_me),
    (_r("/api/auth/register"), "POST", Handler.api_register),
    (_r("/api/auth/login"), "POST", Handler.api_login),
    (_r("/api/auth/logout"), "POST", Handler.api_logout),
    (_r("/api/songs"), "GET", Handler.api_songs),
    (_r("/api/songs"), "POST", Handler.api_upload),
    (_r("/api/songs/{id}"), "GET", Handler.api_song),
    (_r("/api/songs/{id}"), "PATCH", Handler.api_edit_song),
    (_r("/api/songs/{id}"), "DELETE", Handler.api_delete_song),
    (_r("/api/songs/{id}/notes"), "GET", Handler.api_notes),
    (_r("/api/songs/{id}/cover"), "GET", Handler.api_cover),
    (_r("/api/songs/{id}/download"), "GET", Handler.api_download),
    (_r("/api/songs/{id}/play"), "POST", Handler.api_play),
    (_r("/api/songs/{id}/vote"), "POST", Handler.api_vote),
    (_r("/api/songs/{id}/reviews"), "GET", Handler.api_reviews),
    (_r("/api/songs/{id}/reviews"), "POST", Handler.api_add_review),
    (_r("/api/reviews/{id}"), "DELETE", Handler.api_delete_review),
    (_r("/api/songs/{id}/comments"), "GET", Handler.api_comments),
    (_r("/api/songs/{id}/comments"), "POST", Handler.api_add_comment),
    (_r("/api/comments/{id}"), "DELETE", Handler.api_delete_comment),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to share on your Wi-Fi")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    store.init().close()
    mimetypes.add_type("application/javascript", ".js")
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.quiet = args.quiet
    srv.daemon_threads = True
    print(f"Keyfall running at http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
