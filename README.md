# Keyfall — piano song library

A self-hosted MIDI song database for falling-notes piano players (Synthesia and similar apps).

## Run

```sh
./start.sh                    # then open http://localhost:8080
./start.sh --host 0.0.0.0     # share on your Wi-Fi: http://<phone-ip>:8080
```

Needs Python 3 and `mido` (`start.sh` installs it if it's missing). There's no build step and no internet
connection needed.

## Publish it free on PythonAnywhere

1. Create a free **Beginner** account at pythonanywhere.com.
2. Under **Account → API token**, create a token and save it to `~/.config/keyfall/pythonanywhere_token`
   (or set `PYTHONANYWHERE_TOKEN`).
3. Run `python3 -I deploy/pythonanywhere.py <your-username>`.

The site goes live at `https://<your-username>.pythonanywhere.com`, with your local songs, account and
uploads copied over. Running the script again updates the code only. Online accounts, reviews and uploads
in `data/` are never overwritten, so after the first deploy the online site has its own data.

Free-plan notes: log in at least once every 3 months and press **"Run until 3 months from today"** on
the Web tab, or the site is paused. Free accounts can't reach most outside websites, so upload covers
for new songs yourself (album artwork for the bundled songs is shipped with the deploy).

`app/wsgi.py` also works with any other WSGI server (e.g. `gunicorn --chdir app wsgi:application`).

## Features

- **Library**: 437 songs from `Songs/`, with search across title, artist, arranger and tags, category tabs,
  difficulty and source filters, and 11 sort orders.
- **Quick listen**: tap a cover in the list to hear the first 20 seconds.
- **Falling-notes preview**: a keyboard view with colour-coded hands, played through a built-in synth.
  Tap to play or pause, drag to scrub. You can change the speed (50–150%), mute each hand, set the
  volume, go fullscreen, and use Space / ← → on a keyboard.
- **Download** the original MIDI file. Downloads and plays are counted.
- **Likes and dislikes**, **1–5 star reviews** with a rating histogram, and **threaded comments**.
  The uploader's comments are marked.
- **Uploads**: signed-in users can upload a MIDI with title, artist, version, arranger, category, tags,
  description and an optional cover. Uploaders can edit or delete their own songs.
- **Album covers**: real album artwork, fetched from Deezer, or Apple's iTunes Search when Deezer
  has no good match. A cover is used only when the artist and title genuinely match. Songs with no
  match (mostly Nintendo game music, which isn't on those services, and unknown artists) get a cover
  drawn from their own notes instead. Uploaders can set their own cover at any time.
- **Difficulty** (0–100, Beginner → Expert) is calculated from note density, the busiest moments, chord
  size and hand span.

The first account you register becomes the admin and can delete any song, review or comment.

## Layout

| Path | What it is |
| --- | --- |
| `Songs/` | the imported MIDI files (extracted from `Midi.zip`) |
| `data/keyfall.db` | SQLite database: songs, users, votes, reviews, comments |
| `data/midi/`, `data/notes/`, `data/covers/` | uploaded files, parsed note data, generated or uploaded covers |
| `app/server.py` | HTTP server and JSON API (Python standard library) |
| `app/midi_info.py`, `app/covers.py` | MIDI analysis, difficulty, cover generation |
| `app/names.py`, `app/seed.py` | filename → artist/title cleanup and the library importer |
| `app/fetch_covers.py` | real album artwork lookup (`--dry-run` to preview, `--force` to re-check) |
| `app/web/` | the frontend (plain HTML/CSS/JS modules) |

Album artwork isn't stored in git. On a fresh install, `start.sh` fetches it in the background, which
takes a few minutes. To add more bundled songs, put `.mid` files in `Songs/` and run
`python3 -I app/seed.py`, then `python3 -I app/fetch_covers.py`. The importer skips files that are
already imported and byte-identical duplicates.

## Notes on the import

- 446 MIDI files were found (including the nested `MIDI-Collection.zip`). 8 byte-identical duplicates were
  skipped. `Rocket Man 41k.mid` isn't actually a MIDI file and was skipped too.
- `Coldplay_-_Yellow_(Adrian_Lee_Piano_Version).mid` was a RIFF-wrapped MIDI. It was unwrapped to a plain
  `.mid` so any player can open it.
- Artist and title were cleaned up from the filenames. Where a filename had no artist, one was filled in
  by hand, and a few unidentifiable ones are listed as "Unknown". You can fix any of these in
  `app/names.py` and re-import.
