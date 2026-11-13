"""MIDI parsing: musical statistics, a playable note list, and a difficulty estimate."""
import bisect
import hashlib
import io

import mido

# Some files carry out-of-range key signatures; treat them as C major instead of failing.
_ks = mido.midifiles.meta._META_SPEC_BY_TYPE["key_signature"]
_ks_decode = _ks.decode


def _safe_ks_decode(message, data):
    try:
        _ks_decode(message, data)
    except mido.midifiles.meta.KeySignatureError:
        message.key = "C"


_ks.decode = _safe_ks_decode

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
STUCK_NOTE_CAP = 8.0  # seconds; notes that never receive a note-off


class MidiError(ValueError):
    pass


def note_name(n):
    return f"{NOTE_NAMES[n % 12]}{n // 12 - 1}"


def unwrap(data):
    """Return plain SMF bytes; unwraps RIFF/RMID containers."""
    if data[:4] == b"RIFF" and data[8:12] == b"RMID":
        i = data.find(b"MThd")
        if i >= 0:
            return data[i:]
    if data[:4] != b"MThd":
        raise MidiError("Not a Standard MIDI File (missing MThd header)")
    return data


def _tempo_map(mid):
    changes = {}
    for tr in mid.tracks:
        tick = 0
        for m in tr:
            tick += m.time
            if m.type == "set_tempo":
                changes[tick] = m.tempo
    ticks = sorted(changes)
    if not ticks or ticks[0] != 0:
        ticks.insert(0, 0)
        changes.setdefault(0, 500000)
    secs, s = [], 0.0
    for i, t in enumerate(ticks):
        if i:
            s += (t - ticks[i - 1]) * changes[ticks[i - 1]] / (mid.ticks_per_beat * 1e6)
        secs.append(s)
    tempos = [changes[t] for t in ticks]

    def to_sec(tick):
        i = bisect.bisect_right(ticks, tick) - 1
        return secs[i] + (tick - ticks[i]) * tempos[i] / (mid.ticks_per_beat * 1e6)

    return to_sec, tempos


def parse(data):
    """Parse MIDI bytes. Returns (stats dict, playback dict)."""
    data = unwrap(data)
    try:
        mid = mido.MidiFile(file=io.BytesIO(data), clip=True)
    except Exception as e:
        raise MidiError(f"Unreadable MIDI: {e}") from e
    if mid.ticks_per_beat <= 0:
        raise MidiError("Unsupported SMPTE timing")
    to_sec, tempos = _tempo_map(mid)

    key = time_sig = ""
    groups = {}  # (track, channel) -> {"name":..., "notes": [...]}
    track_names = {}
    for ti, tr in enumerate(mid.tracks):
        tick = 0
        open_notes = {}
        last_tick = 0
        for m in tr:
            tick += m.time
            last_tick = tick
            if m.is_meta:
                if m.type == "track_name" and ti not in track_names:
                    track_names[ti] = m.name.strip()
                elif m.type == "key_signature" and not key:
                    key = m.key
                elif m.type == "time_signature" and not time_sig:
                    time_sig = f"{m.numerator}/{m.denominator}"
                continue
            if not hasattr(m, "channel") or m.channel == 9:  # skip percussion
                continue
            k = (m.channel, getattr(m, "note", None))
            if m.type == "note_on" and m.velocity > 0:
                open_notes.setdefault(k, []).append((tick, m.velocity))
            elif m.type in ("note_off", "note_on"):
                stack = open_notes.get(k)
                if stack:
                    start, vel = stack.pop(0)
                    g = groups.setdefault((ti, m.channel), [])
                    g.append((to_sec(start), to_sec(tick), m.note, vel))
        end_sec = to_sec(last_tick)
        for (ch, note), stack in open_notes.items():
            for start, vel in stack:
                s = to_sec(start)
                groups.setdefault((ti, ch), []).append((s, min(max(end_sec, s + 0.25), s + STUCK_NOTE_CAP), note, vel))

    groups = {k: v for k, v in groups.items() if v}
    if not groups:
        raise MidiError("The file contains no playable notes")

    # Hand / colour assignment: lowest average pitch = left hand, highest = right.
    order = sorted(groups, key=lambda k: sum(n[2] for n in groups[k]) / len(groups[k]))
    tracks, idx = [], {}
    for rank, k in enumerate(order):
        if len(order) == 1:
            hand = "R"
        elif rank == 0:
            hand = "L"
        elif rank == len(order) - 1:
            hand = "R"
        else:
            hand = "O"
        name = track_names.get(k[0], "") or f"Track {k[0] + 1}"
        idx[k] = len(tracks)
        tracks.append({"name": name[:60], "hand": hand, "notes": len(groups[k])})

    notes = []
    for k, g in groups.items():
        for s, e, p, v in g:
            notes.append((s, max(e - s, 0.03), p, v, idx[k]))
    notes.sort()
    first = notes[0][0]
    duration = max(s + d for s, d, *_ in notes)
    pitches = [n[2] for n in notes]

    # polyphony
    ev = sorted([(s, 1) for s, *_ in notes] + [(s + d, -1) for s, d, *_ in notes])
    cur = peak = 0
    for _, d in ev:
        cur += d
        peak = max(peak, cur)
    # peak onset density in a 2 s window
    onsets = [n[0] for n in notes]
    j = win = 0
    for i, o in enumerate(onsets):
        while onsets[j] < o - 2.0:
            j += 1
        win = max(win, i - j + 1)
    span = max(onsets[-1] - first, 1.0)

    stats = {
        "md5": hashlib.md5(data).hexdigest(),
        "size": len(data),
        "duration": round(duration, 1),
        "notes": len(notes),
        "tracks": len(tracks),
        "nps": round(len(notes) / span, 2),
        "peak_nps": round(win / 2.0, 1),
        "polyphony": peak,
        "low": min(pitches),
        "high": max(pitches),
        "bpm": round(mido.tempo2bpm(tempos[0]), 1),
        "key": key,
        "time_sig": time_sig or "4/4",
    }
    stats["difficulty"] = difficulty(stats)
    playback = {
        "duration": round(duration, 3),
        "first": round(first, 3),
        "tracks": tracks,
        "notes": [[round(s, 3), round(d, 3), p, v, t] for s, d, p, v, t in notes],
    }
    return data, stats, playback


def _norm(x, lo, hi):
    return min(max((x - lo) / (hi - lo), 0.0), 1.0)


def difficulty(st):
    """0-100 estimate from note density, bursts, chord size and hand span."""
    score = (
        0.45 * _norm(st["nps"], 2, 14)
        + 0.25 * _norm(st["peak_nps"], 5, 30)
        + 0.15 * _norm(min(st["polyphony"], 12), 3, 10)
        + 0.15 * _norm(st["high"] - st["low"], 24, 72)
    )
    return round(score * 100)


LEVELS = [(20, "Beginner"), (40, "Easy"), (60, "Intermediate"), (80, "Advanced"), (101, "Expert")]


def level(score):
    return next(name for cap, name in LEVELS if score < cap)
