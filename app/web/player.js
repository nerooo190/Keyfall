// Transport (timing + audio scheduling) and the falling-notes piano roll.
import { synth } from "./synth.js";

export const HAND_COLORS = { R: "#7ccf5b", L: "#4f9be8" };
const OTHER_COLORS = ["#f0a43a", "#c77ce8", "#e8d24f", "#e8705f", "#4fd6c5", "#d9e2ea"];
const WHITE = new Set([0, 2, 4, 5, 7, 9, 11]);
const NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

export function trackColors(tracks) {
  let k = 0;
  return tracks.map((t) => HAND_COLORS[t.hand] || OTHER_COLORS[k++ % OTHER_COLORS.length]);
}

function shade(hex, f) {
  const n = parseInt(hex.slice(1), 16);
  const c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.round(f < 1 ? v * f : v + (255 - v) * (f - 1)));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

function lowerBound(notes, t) {
  let lo = 0, hi = notes.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (notes[mid][0] < t) lo = mid + 1; else hi = mid;
  }
  return lo;
}

export class Transport {
  constructor(playback) {
    this.pb = playback;
    this.notes = playback.notes; // [start, dur, pitch, vel, track]
    this.duration = playback.duration;
    this.speed = 1;
    this.muted = new Set();
    this.playing = false;
    this.pos = 0;
    this.listeners = new Set();
    this.timer = null;
  }

  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  emit(type) { for (const fn of this.listeners) fn(type, this); }

  get time() {
    if (!this.playing) return this.pos;
    return this.anchorSong + (synth.now - this.anchorCtx) * this.speed;
  }

  play(from) {
    synth.ensure();
    if (from !== undefined) this.pos = from;
    if (this.pos >= this.duration - 0.05) this.pos = 0;
    this.anchorCtx = synth.now + 0.06;
    this.anchorSong = this.pos;
    this.cursor = lowerBound(this.notes, this.pos);
    this.playing = true;
    this.schedule();
    clearInterval(this.timer);
    this.timer = setInterval(() => this.schedule(), 25);
    this.emit("play");
  }

  pause() {
    if (!this.playing) return;
    this.pos = Math.min(this.time, this.duration);
    this.playing = false;
    clearInterval(this.timer);
    synth.stopAll();
    this.emit("pause");
  }

  toggle() { this.playing ? this.pause() : this.play(); }

  seek(t) {
    t = Math.max(0, Math.min(t, this.duration));
    const was = this.playing;
    if (was) { this.playing = false; clearInterval(this.timer); synth.stopAll(); }
    this.pos = t;
    if (was) this.play(); else this.emit("seek");
  }

  setSpeed(s) {
    const t = this.time;
    this.speed = s;
    if (this.playing) { this.pause(); this.play(t); } else this.pos = t;
  }

  setMuted(track, muted) {
    muted ? this.muted.add(track) : this.muted.delete(track);
  }

  schedule() {
    if (!this.playing) return;
    const now = this.time;
    if (now >= this.duration + 0.3) {
      this.playing = false;
      this.pos = this.duration;
      clearInterval(this.timer);
      this.emit("end");
      return;
    }
    const horizon = now + 0.25 * this.speed;
    const n = this.notes;
    while (this.cursor < n.length && n[this.cursor][0] < horizon) {
      const [s, d, p, v, tr] = n[this.cursor++];
      if (s < now - 0.03 || this.muted.has(tr)) continue;
      synth.note(p, v, this.anchorCtx + (s - this.anchorSong) / this.speed, d / this.speed);
    }
  }

  destroy() {
    this.pause();
    this.listeners.clear();
  }
}

export class PianoRoll {
  constructor(canvas, transport, opts = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.t = transport;
    this.colors = trackColors(transport.pb.tracks);
    this.hidden = new Set();
    this.window = opts.window || 2.6; // seconds of music visible above the keys
    this.computeRange();
    this.resize();
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(canvas);
    this.frame = this.frame.bind(this);
    this.raf = requestAnimationFrame(this.frame);
    this.bindPointer();
  }

  computeRange() {
    let lo = 127, hi = 0;
    for (const n of this.t.notes) { if (n[2] < lo) lo = n[2]; if (n[2] > hi) hi = n[2]; }
    lo -= lo % 12;
    hi += 11 - (hi % 12);
    while (hi - lo + 1 < 48) { if (lo >= 33) lo -= 12; else hi += 12; } // at least four octaves
    this.lo = Math.max(21, lo);
    this.hi = Math.min(108, hi);
    this.whites = [];
    for (let p = this.lo; p <= this.hi; p++) if (WHITE.has(p % 12)) this.whites.push(p);
    this.whiteIndex = new Map(this.whites.map((p, i) => [p, i]));
  }

  resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    const r = this.canvas.getBoundingClientRect();
    this.w = r.width;
    this.h = r.height;
    this.canvas.width = Math.round(r.width * dpr);
    this.canvas.height = Math.round(r.height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.kw = this.w / this.whites.length;
    this.kbH = Math.min(Math.max(this.kw * 5, 56), this.h * 0.26);
    this.hitY = this.h - this.kbH;
  }

  keyX(p) {
    if (WHITE.has(p % 12)) return [this.whiteIndex.get(p) * this.kw, this.kw];
    const left = this.whiteIndex.get(p - 1) * this.kw;
    return [left + this.kw * 0.64, this.kw * 0.72];
  }

  bindPointer() {
    // Tap = play/pause. Vertical drag scrubs, as if dragging the falling notes.
    let startY = null, startT = 0, moved = false, resume = false;
    const c = this.canvas;
    c.addEventListener("pointerdown", (e) => {
      startY = e.clientY; startT = this.t.time; moved = false; resume = false;
      c.setPointerCapture(e.pointerId);
    });
    c.addEventListener("pointermove", (e) => {
      if (startY === null) return;
      const dy = e.clientY - startY;
      if (!moved && Math.abs(dy) > 6) {
        moved = true;
        resume = this.t.playing;
        this.t.pause();
      }
      if (moved) this.t.seek(startT + dy / (this.hitY / this.window));
    });
    c.addEventListener("pointerup", () => {
      if (startY === null) return;
      if (!moved) this.t.toggle();
      else if (resume) this.t.play();
      startY = null;
    });
    c.addEventListener("pointercancel", () => {
      if (resume) this.t.play();
      startY = null;
    });
  }

  frame() {
    this.raf = requestAnimationFrame(this.frame);
    this.draw(this.t.time);
  }

  draw(t) {
    const { ctx, w, hitY } = this;
    const pps = hitY / this.window;
    ctx.fillStyle = "#12161c";
    ctx.fillRect(0, 0, w, this.h);

    // lanes: subtle shading under black keys, a line at every C
    for (let p = this.lo; p <= this.hi; p++) {
      if (!WHITE.has(p % 12)) {
        const [x, kw] = this.keyX(p);
        ctx.fillStyle = "#0f1217";
        ctx.fillRect(x, 0, kw, hitY);
      } else if (p % 12 === 0) {
        ctx.fillStyle = "#222833";
        ctx.fillRect(this.whiteIndex.get(p) * this.kw, 0, 1, hitY);
      }
    }

    const notes = this.t.notes;
    const active = new Map();
    let i = lowerBound(notes, t - 8.5);
    const until = t + this.window + 0.1;
    // draw white-key notes first so black-key notes sit on top
    const blacks = [];
    for (; i < notes.length && notes[i][0] < until; i++) {
      const n = notes[i];
      if (n[0] + n[1] < t) continue;
      if (n[0] <= t && t < n[0] + n[1]) active.set(n[2], n[4]);
      if (WHITE.has(n[2] % 12)) this.drawNote(n, t, pps, false); else blacks.push(n);
    }
    for (const n of blacks) this.drawNote(n, t, pps, true);

    // hit line
    const grad = ctx.createLinearGradient(0, hitY - 14, 0, hitY);
    grad.addColorStop(0, "rgba(217,164,65,0)");
    grad.addColorStop(1, "rgba(217,164,65,0.16)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, hitY - 14, w, 14);
    this.drawKeyboard(active);
    ctx.fillStyle = "#d9a441";
    ctx.fillRect(0, hitY - 2, w, 2);
  }

  drawNote(n, t, pps, black) {
    const [s, d, p, , tr] = n;
    if (this.hidden.has(tr)) return;
    const ctx = this.ctx;
    let y1 = this.hitY - (s - t) * pps;
    let y0 = this.hitY - (s + d - t) * pps;
    y1 = Math.min(y1, this.hitY);
    if (y1 - y0 < 2) y0 = y1 - 2;
    if (y1 <= 0) return;
    const [x, kw] = this.keyX(p);
    const color = this.colors[tr];
    const muted = this.t.muted.has(tr);
    const pad = Math.max(1, kw * 0.08);
    const nx = x + pad, nw = kw - pad * 2;
    const r = Math.min(4, nw / 3, (y1 - y0) / 2);
    ctx.globalAlpha = muted ? 0.28 : 1;
    ctx.fillStyle = black ? shade(color, 0.72) : color;
    ctx.beginPath();
    ctx.roundRect(nx, y0, nw, y1 - y0, r);
    ctx.fill();
    ctx.strokeStyle = shade(color, 0.45);
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  drawKeyboard(active) {
    const { ctx, kw, hitY, kbH } = this;
    ctx.fillStyle = "#07090b";
    ctx.fillRect(0, hitY, this.w, kbH);
    for (let i = 0; i < this.whites.length; i++) {
      const p = this.whites[i];
      const tr = active.get(p);
      const x = i * kw;
      if (tr !== undefined && !this.hidden.has(tr)) {
        ctx.fillStyle = this.colors[tr];
      } else {
        const g = ctx.createLinearGradient(0, hitY, 0, hitY + kbH);
        g.addColorStop(0, "#cfd3d8");
        g.addColorStop(0.08, "#f2f3f5");
        g.addColorStop(1, "#e3e5e8");
        ctx.fillStyle = g;
      }
      ctx.beginPath();
      ctx.roundRect(x + 0.5, hitY, kw - 1, kbH - 1, [0, 0, 3, 3]);
      ctx.fill();
      if (p % 12 === 0 && kw > 11) {
        ctx.fillStyle = "#8b929c";
        ctx.font = `${Math.min(11, kw * 0.55)}px system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.fillText(`C${p / 12 - 1}`, x + kw / 2, hitY + kbH - 6);
      }
    }
    const bh = kbH * 0.62;
    for (let p = this.lo; p <= this.hi; p++) {
      if (WHITE.has(p % 12)) continue;
      const [x, bw] = this.keyX(p);
      const tr = active.get(p);
      if (tr !== undefined && !this.hidden.has(tr)) {
        ctx.fillStyle = shade(this.colors[tr], 0.8);
      } else {
        const g = ctx.createLinearGradient(0, hitY, 0, hitY + bh);
        g.addColorStop(0, "#2a2f36");
        g.addColorStop(1, "#14171b");
        ctx.fillStyle = g;
      }
      ctx.beginPath();
      ctx.roundRect(x, hitY, bw, bh, [0, 0, 2, 2]);
      ctx.fill();
    }
  }

  destroy() {
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
  }
}

export function noteName(p) {
  return NAMES[p % 12] + (Math.floor(p / 12) - 1);
}

// Short audio-only preview used by the library list.
export class QuickPreview {
  constructor() { this.current = null; }

  async toggle(id, onState) {
    if (this.current && this.current.id === id) { this.stop(); return; }
    this.stop();
    const token = (this.current = { id, onState, transport: null });
    onState("loading");
    try {
      const res = await fetch(`/api/songs/${id}/notes`);
      if (!res.ok) throw new Error("load failed");
      const pb = await res.json();
      if (this.current !== token) return;
      const tr = new Transport(pb);
      token.transport = tr;
      const start = pb.first;
      const length = Math.min(20, pb.duration - start);
      tr.on((type) => { if (type === "end") this.stop(); });
      tr.play(start);
      onState("playing");
      token.timer = setInterval(() => {
        const frac = (tr.time - start) / length;
        onState("progress", Math.min(frac, 1));
        if (frac >= 1) this.stop();
      }, 100);
    } catch {
      if (this.current === token) { this.current = null; onState("error"); }
    }
  }

  stop() {
    const c = this.current;
    if (!c) return;
    this.current = null;
    clearInterval(c.timer);
    if (c.transport) c.transport.destroy();
    c.onState("stopped");
  }
}
