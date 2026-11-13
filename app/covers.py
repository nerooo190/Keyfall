"""Generated cover art: a falling-notes snapshot drawn from the song's own notes."""

HAND_COLORS = {"R": "#7ccf5b", "L": "#4f9be8"}
OTHER_COLORS = ["#f0a43a", "#c77ce8", "#e8d24f", "#e8705f", "#4fd6c5", "#d9e2ea"]
WHITE_KEYS = {0, 2, 4, 5, 7, 9, 11}


def track_color(track, i):
    return HAND_COLORS.get(track["hand"]) or OTHER_COLORS[i % len(OTHER_COLORS)]


def _densest_window(notes, length):
    starts = [n[0] for n in notes]
    best, best_t, j = -1, starts[0], 0
    for i, s in enumerate(starts):
        while starts[j] < s - length:
            j += 1
        if i - j + 1 > best:
            best, best_t = i - j + 1, starts[j]
    return best_t


def render(playback, size=240):
    notes = playback["notes"]
    window = 9.0
    t0 = _densest_window(notes, window)
    lo = min(n[2] for n in notes)
    hi = max(n[2] for n in notes)
    lo = max(21, lo - lo % 12)            # start on a C
    hi = min(108, hi + (11 - hi % 12))    # end on a B
    whites = [p for p in range(lo, hi + 1) if p % 12 in WHITE_KEYS]
    kw = size / len(whites)
    kb_h = size * 0.14
    roll_h = size - kb_h

    def x_of(p):
        if p % 12 in WHITE_KEYS:
            return whites.index(p) * kw, kw
        left = whites.index(p - 1) * kw
        return left + kw * 0.65, kw * 0.7

    colors = [track_color(t, i) for i, t in enumerate(playback["tracks"])]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">',
        f'<rect width="{size}" height="{size}" fill="#15191f"/>',
    ]
    # octave guide lines
    for p in range(lo, hi + 1, 12):
        x = whites.index(p) * kw
        out.append(f'<rect x="{x:.1f}" y="0" width="0.6" height="{roll_h:.1f}" fill="#262c35"/>')
    lit = {}
    for s, d, p, v, t in notes:
        if s + d < t0 or s > t0 + window:
            continue
        # time flows downward towards the keyboard: t0 sits at the keys
        y1 = roll_h - (s - t0) / window * roll_h
        y0 = roll_h - (s + d - t0) / window * roll_h
        y0, y1 = max(y0, 0), min(y1, roll_h)
        if y1 - y0 < 1:
            continue
        x, w = x_of(p)
        out.append(
            f'<rect x="{x + 0.5:.1f}" y="{y0:.1f}" width="{max(w - 1, 1):.1f}" height="{y1 - y0:.1f}" rx="1.5" fill="{colors[t]}"/>'
        )
        if s <= t0 + 0.05 and s + d >= t0:
            lit[p] = colors[t]
    # keyboard
    out.append(f'<rect x="0" y="{roll_h:.1f}" width="{size}" height="{kb_h:.1f}" fill="#0c0e11"/>')
    for i, p in enumerate(whites):
        fill = lit.get(p, "#e9ebee")
        out.append(f'<rect x="{i * kw + 0.4:.1f}" y="{roll_h + 1:.1f}" width="{kw - 0.8:.1f}" height="{kb_h - 1:.1f}" rx="1" fill="{fill}"/>')
    for p in range(lo, hi + 1):
        if p % 12 not in WHITE_KEYS:
            x, w = x_of(p)
            fill = lit.get(p, "#1b1f25")
            out.append(f'<rect x="{x:.1f}" y="{roll_h + 1:.1f}" width="{w:.1f}" height="{kb_h * 0.6:.1f}" rx="0.8" fill="{fill}"/>')
    out.append(f'<rect x="0" y="{roll_h - 1.5:.1f}" width="{size}" height="1.5" fill="#d9a441"/>')
    out.append("</svg>")
    return "".join(out)
