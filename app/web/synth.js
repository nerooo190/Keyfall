// A small additive piano-ish synthesizer built on the Web Audio API.
// No samples: each note is three partials through a velocity-dependent low-pass,
// with a pitch-dependent decay, plus a short generated room reverb.

export class Synth {
  constructor() {
    this.ctx = null;
    this.voices = new Set();
    this.maxVoices = 56;
    this.volume = 0.8;
  }

  ensure() {
    if (this.ctx) {
      if (this.ctx.state === "suspended") this.ctx.resume();
      return this.ctx;
    }
    const Ctor = window.AudioContext || window.webkitAudioContext;
    let ctx;
    try {
      ctx = new Ctor({ latencyHint: "interactive" });
    } catch {
      // No Web Audio: visuals still run on a wall clock (see `now`), silently.
      if (!this.warned) { this.warned = true; this.onUnavailable?.(); }
      return null;
    }
    this.ctx = ctx;
    this.master = ctx.createGain();
    this.master.gain.value = this.volume;
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -14;
    comp.knee.value = 10;
    comp.ratio.value = 4;
    this.bus = ctx.createGain();
    this.bus.gain.value = 0.32;
    const wet = ctx.createGain();
    wet.gain.value = 0.2;
    const verb = ctx.createConvolver();
    verb.buffer = this.impulse(1.9, 2.6);
    this.bus.connect(comp);
    this.bus.connect(verb);
    verb.connect(wet);
    wet.connect(comp);
    comp.connect(this.master);
    this.master.connect(ctx.destination);
    return ctx;
  }

  impulse(seconds, decay) {
    const rate = this.ctx.sampleRate;
    const len = Math.floor(rate * seconds);
    const buf = this.ctx.createBuffer(2, len, rate);
    for (let c = 0; c < 2; c++) {
      const d = buf.getChannelData(c);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, decay);
    }
    return buf;
  }

  setVolume(v) {
    this.volume = v;
    if (this.master) this.master.gain.setTargetAtTime(v, this.ctx.currentTime, 0.02);
  }

  get now() {
    return this.ctx ? this.ctx.currentTime : performance.now() / 1000;
  }

  // Schedule one note. `when` and `dur` are in AudioContext seconds.
  note(pitch, velocity, when, dur) {
    const ctx = this.ctx;
    if (!ctx) return;
    if (this.voices.size >= this.maxVoices) {
      const oldest = this.voices.values().next().value;
      this.kill(oldest, when);
    }
    const f = 440 * Math.pow(2, (pitch - 69) / 12);
    const v = Math.max(0.08, velocity / 127);
    const t0 = Math.max(when, ctx.currentTime);
    const end = t0 + Math.max(dur, 0.06);
    // Low notes ring longer; high notes die faster, like real strings.
    const tau = 0.25 + 1.6 * Math.pow(1 - (pitch - 21) / 87, 1.6);

    const out = ctx.createGain();
    out.gain.setValueAtTime(0, t0);
    out.gain.linearRampToValueAtTime(v * v * 0.9 + 0.05, t0 + 0.006);
    out.gain.setTargetAtTime(v * 0.18, t0 + 0.006, tau);
    out.gain.setTargetAtTime(0, end, 0.09);

    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.Q.value = 0.4;
    const bright = Math.min(14000, f * (3 + 9 * v) + 600);
    lp.frequency.setValueAtTime(bright, t0);
    lp.frequency.setTargetAtTime(Math.max(f * 1.5, 500), t0 + 0.01, tau * 0.8);
    lp.connect(out);
    out.connect(this.bus);

    const partials = [
      [1, "triangle", 0.75],
      [2, "sine", 0.22 * v + 0.08],
      [3, "sine", 0.07 * v],
    ];
    const oscs = [];
    for (const [mult, type, amp] of partials) {
      if (f * mult > 16000) continue;
      const o = ctx.createOscillator();
      o.type = type;
      o.frequency.value = f * mult;
      o.detune.value = (Math.random() - 0.5) * 4;
      const g = ctx.createGain();
      g.gain.value = amp;
      o.connect(g);
      g.connect(lp);
      o.start(t0);
      o.stop(end + 0.6);
      oscs.push(o);
    }
    const voice = { out, oscs, end: end + 0.6 };
    this.voices.add(voice);
    oscs[0].onended = () => {
      this.voices.delete(voice);
      out.disconnect();
    };
  }

  kill(voice, at) {
    const t = Math.max(at ?? this.ctx.currentTime, this.ctx.currentTime);
    voice.out.gain.cancelScheduledValues(t);
    voice.out.gain.setTargetAtTime(0, t, 0.015);
    for (const o of voice.oscs) {
      try { o.stop(t + 0.1); } catch { /* already stopped */ }
    }
    this.voices.delete(voice);
  }

  stopAll() {
    if (!this.ctx) return;
    for (const v of [...this.voices]) this.kill(v);
  }
}

export const synth = new Synth();
