"""Import the bundled MIDI library (../Songs) into the database.

Usage: python3 -I app/seed.py            (safe to re-run; already-imported files are skipped)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import midi_info  # noqa: E402
import names  # noqa: E402
import store  # noqa: E402


def main():
    songs_dir = os.path.join(store.ROOT, "Songs")
    db = store.init()
    added = dup = bad = 0
    for dirpath, _, files in os.walk(songs_dir):
        for f in sorted(files):
            if not f.lower().endswith((".mid", ".midi")):
                continue
            path = os.path.join(dirpath, f)
            rel = os.path.relpath(path, store.ROOT)
            if db.execute("SELECT 1 FROM songs WHERE path = ?", (rel,)).fetchone():
                continue
            n = names.parse(os.path.splitext(f)[0])
            tags = [t for t in (n["version"], "Hands split" if n["split_hands"] else "") if t]
            meta = {
                "title": n["title"], "artist": n["artist"], "version": n["version"],
                "arranger": n["arranger"], "category": n["category"], "tags": ",".join(tags),
                "created_at": os.path.getmtime(path),
            }
            try:
                with open(path, "rb") as fh:
                    store.add_song(db, fh.read(), meta, "library", path=path)
                added += 1
            except store.Duplicate as e:
                dup += 1
                print(f"  duplicate of #{e.song_id}: {rel}")
            except midi_info.MidiError as e:
                bad += 1
                print(f"  skipped (invalid): {rel} — {e}")
    db.commit()
    total = db.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
    print(f"added {added}, duplicates {dup}, invalid {bad}; library now has {total} songs")


if __name__ == "__main__":
    main()
