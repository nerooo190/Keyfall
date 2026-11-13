"""Fetch real album artwork for library songs from Deezer (fallback: iTunes Search).

Usage:
  python3 -I app/fetch_covers.py              # songs that still have a generated cover
  python3 -I app/fetch_covers.py --force      # also re-check songs with fetched artwork
  python3 -I app/fetch_covers.py --dry-run    # show matches, change nothing

Only confident matches are used: the artist and title must both match. For classical
pieces (where catalogues list the performer) the composer's surname and the piece's
key words must appear in the result. Anything else keeps its generated cover.
User-uploaded covers are never touched.
"""
import argparse
import difflib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store  # noqa: E402

UA = {"User-Agent": "Keyfall/1.0 (self-hosted song library; cover lookup)"}
CACHE_PATH = os.path.join(store.DATA, "cover_cache.json")
# Only for classical do catalogues list performers instead of the composer. For film and
# game music the composer is the credited artist, and anything else is a fan cover.
COMPOSER_CATEGORIES = {"Classical"}
UNKNOWN_ARTISTS = {"unknown", "various", "traditional"}
STOP = {"the", "a", "an", "of", "in", "no", "op", "and", "for", "to", "major", "minor", "movement",
        "piano", "theme", "main", "i", "ii", "iii", "iv", "v", "sonata", "version", "from", "de", "la", "le"}
BAD_ALBUM = re.compile(r"karaoke|tribute|made famous|in the style of|originally (by|performed)|lullab|8-bit|"
                       r"ringtone|workout|relax|meditat|sleep|dormire|rilassante|study|focus|spa music|yoga|baby|"
                       r"for kids|calm|chill out|background music", re.I)
VARIANT = re.compile(r"\blive\b|remix|\brework|club mix|club edit|radio edit|extended mix|\bmix\)|acoustic|"
                     r"instrumental|\bdemo\b|sped up|slowed|unplugged|karaoke", re.I)
GOOD_ENOUGH = 3.5  # exact artist + title match with no variant penalty

# Better search phrases for songs whose stored title doesn't search well.
QUERY_OVERRIDES = {
    "Moonlight Sonata (Sonata No. 14, Op. 27)": "Beethoven Moonlight Sonata",
    "Moonlight Sonata – I.": "Beethoven Moonlight Sonata Adagio sostenuto",
    "Prelude in C Major, BWV 846": "Bach Prelude in C major BWV 846",
    "Comptine d'un autre été – L'après-midi": "Yann Tiersen Comptine d'un autre ete",
    "Unravel (Tokyo Ghoul OP)": "TK from Ling tosite sigure unravel",
    "Startear (Sword Art Online II ED)": "Luna Haruna Startear",
    "Game of Thrones – Main Theme": "Ramin Djawadi Main Title Game of Thrones",
    "Star Wars – Main Theme": "John Williams Star Wars Main Title",
    "The Office – Opening Theme": "The Office theme Jay Ferguson",
    "Gravity Falls – Opening": "Gravity Falls Main Title Brad Breeck",
    "Time (Inception)": "Hans Zimmer Time Inception",
    "First Step (Interstellar)": "Hans Zimmer First Step Interstellar",
    "Interstellar – Main Theme": "Hans Zimmer Interstellar Main Theme",
    "See You Tomorrow (How to Train Your Dragon)": "John Powell See You Tomorrow",
    "My Heart Will Go On (Titanic)": "James Horner Titanic",
    "My Life Is Going On (La Casa de Papel)": "Cecilia Krull My Life Is Going On",
    "Cara Mia Addio (Turret Opera)": "Cara Mia Addio Portal 2",
    "Requiem for a Dream – Lux Aeterna": "Clint Mansell Lux Aeterna",
    "Love Story (Where Do I Begin)": "Love Story Where Do I Begin",
    "The Good, the Bad and the Ugly": "Ennio Morricone The Good the Bad and the Ugly",
    "Pokémon Theme": "Jason Paige Pokemon Theme",
    "Transformers Theme (2007)": "Steve Jablonsky Arrival to Earth",
    "Harry Potter Medley": "John Williams Hedwig's Theme",
    "Happy Birthday (Chopin & Liszt Style)": None,  # no real album
    "Last Christmas (Quick Riff)": "Wham! Last Christmas",
    "See You Again (No Rap)": "Wiz Khalifa See You Again Charlie Puth",
    "Gangsta's Paradise (Remake)": "Coolio Gangsta's Paradise",
    "Good Riddance (Time of Your Life)": "Green Day Good Riddance Time of Your Life",
}


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[\(\[].*?[\)\]]", " ", s)
    s = re.sub(r"\b(feat|ft|featuring|with)\b.*", " ", s)
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b or (len(a) > 3 and a in b) or (len(b) > 3 and b in a):
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def primary_artists(artist):
    parts = re.split(r"\s+(?:feat\.?|ft\.?|x|&|and|vs\.?)\s+|,\s*", artist, flags=re.I)
    return [p for p in parts if p.strip()]


def surname(artist):
    return norm(artist).split()[-1] if norm(artist) else ""


def keywords(title):
    return [w for w in norm(title).split() if w not in STOP and not w.isdigit() and len(w) > 2]


def http_json(url):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                return json.load(r)
        except Exception as e:  # rate limit / transient network error
            if attempt == 3:
                print(f"    ! {e}")
                return None
            time.sleep(2 + attempt * 3)


def http_bytes(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return r.read(3 * 1024 * 1024)
        except Exception:
            time.sleep(2)
    return None


def deezer(query):
    time.sleep(0.15)  # Deezer allows 50 requests / 5 s
    d = http_json("https://api.deezer.com/search?" + urllib.parse.urlencode({"q": query, "limit": 25}))
    out = []
    for x in (d or {}).get("data", []):
        al = x.get("album") or {}
        if al.get("cover_big"):
            out.append({"artist": x["artist"]["name"], "title": x["title"], "album": al.get("title", ""),
                        "full": al["cover_big"], "thumb": al.get("cover_medium") or al["cover_big"],
                        "link": x.get("link", ""), "source": "deezer", "rank": x.get("rank", 0)})
    return out


_last_itunes = [0.0]


def itunes(query):
    wait = 3.2 - (time.time() - _last_itunes[0])  # ~20 requests / minute
    if wait > 0:
        time.sleep(wait)
    _last_itunes[0] = time.time()
    d = http_json("https://itunes.apple.com/search?" + urllib.parse.urlencode({"term": query, "entity": "song", "limit": 25}))
    out = []
    for x in (d or {}).get("results", []):
        art = x.get("artworkUrl100")
        if art:
            out.append({"artist": x.get("artistName", ""), "title": x.get("trackName", ""),
                        "album": x.get("collectionName", ""), "full": art.replace("100x100bb", "500x500bb"),
                        "thumb": art.replace("100x100bb", "250x250bb"), "link": x.get("trackViewUrl", ""),
                        "source": "itunes", "rank": 0})
    return out


def score(song, c):
    """Return a match score, or None when the candidate isn't the same song."""
    if BAD_ALBUM.search(c["album"]) or BAD_ALBUM.search(c["artist"]):
        return None
    title_sim = similar(song["title"], c["title"])
    artist_sim = max(similar(a, c["artist"]) for a in primary_artists(song["artist"]))
    if artist_sim >= 0.8 and title_sim >= 0.8:
        s = 2.0 + title_sim + artist_sim
    elif song["category"] in COMPOSER_CATEGORIES:
        # Catalogues list performers; require the composer + the piece's key words instead.
        hay = norm(" ".join((c["artist"], c["title"], c["album"])))
        sn = surname(song["artist"])
        kws = keywords(song["title"]) or norm(song["title"]).split()
        if not sn or sn not in hay.split() or not all(k in hay for k in kws):
            return None
        s = 1.0 + 0.5 * title_sim
    else:
        return None
    if VARIANT.search(c["title"]) and not VARIANT.search(song["title"]):
        s -= 0.6
    if VARIANT.search(c["album"]) and not VARIANT.search(song["title"]):
        s -= 0.6
    return s + min(c["rank"], 1_000_000) / 10_000_000


def find(song, cache):
    key = f"{song['artist']}|{song['title']}"
    if key in cache:
        return cache[key]
    if song["title"] in QUERY_OVERRIDES:
        query = QUERY_OVERRIDES[song["title"]]
    elif song["artist"].lower() in UNKNOWN_ARTISTS:
        query = None
    else:
        title = re.sub(r"\s*[\(\[].*?[\)\]]", "", song["title"])
        query = f"{primary_artists(song['artist'])[0]} {title}"
    best = None
    if query:
        # Deezer first; ask iTunes too when Deezer only has a remix/live version or a weak match.
        scored = []
        for search in (deezer, itunes):
            scored += [(s, c) for c in search(query) if (s := score(song, c)) is not None]
            if scored and max(s for s, _ in scored) >= GOOD_ENOUGH:
                break
        if scored:
            best = max(scored, key=lambda x: x[0])[1]
    cache[key] = best
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-check songs that already have fetched artwork")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    db = store.init()
    cache = {}
    if os.path.exists(CACHE_PATH) and not args.force:
        with open(CACHE_PATH) as f:
            cache = json.load(f)
    rows = db.execute("SELECT * FROM songs ORDER BY artist, title").fetchall()
    todo = [r for r in rows if r["cover_source"] != "upload" and (args.force or not r["cover_ext"])]
    if args.limit:
        todo = todo[: args.limit]
    found = missed = 0
    misses = []
    for i, r in enumerate(todo, 1):
        m = find(r, cache)
        label = f"[{i}/{len(todo)}] {r['artist']} – {r['title']}"
        if not m:
            missed += 1
            misses.append(f"{r['artist']} – {r['title']}")
            print(f"{label}\n    – no confident match, keeping generated cover")
            continue
        print(f"{label}\n    → {m['artist']} – {m['title']}  [{m['album']}] ({m['source']})")
        if args.dry_run:
            found += 1
            continue
        full, thumb = http_bytes(m["full"]), http_bytes(m["thumb"])
        if not full or not full.startswith(b"\xff\xd8\xff"):
            missed += 1
            misses.append(f"{r['artist']} – {r['title']} (download failed)")
            continue
        store.clear_custom_cover(r["id"])
        with open(store.cover_path(r["id"], "jpg"), "wb") as f:
            f.write(full)
        if thumb and thumb.startswith(b"\xff\xd8\xff"):
            with open(store.cover_path(r["id"], "jpg", thumb=True), "wb") as f:
                f.write(thumb)
        db.execute("UPDATE songs SET cover_ext = 'jpg', cover_source = ?, album = ?, cover_link = ? WHERE id = ?",
                   (m["source"], m["album"][:200], m["link"][:300], r["id"]))
        db.commit()
        found += 1
        if i % 20 == 0:
            with open(CACHE_PATH, "w") as f:
                json.dump(cache, f)
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f)
    print(f"\nartwork found for {found}, kept generated cover for {missed} (of {len(todo)} checked)")
    if misses:
        print("No match:\n  " + "\n  ".join(misses))


if __name__ == "__main__":
    main()
