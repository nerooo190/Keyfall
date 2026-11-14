import { synth } from "./synth.js";
import { Transport, PianoRoll, QuickPreview, trackColors } from "./player.js";

/* ====================================================================== helpers */
const $view = document.getElementById("view");
const state = { user: null, meta: null };
const preview = new QuickPreview();
let teardown = [];

const SVG_NS = "http://www.w3.org/2000/svg";
const ICONS = {
  play: '<path d="M7 4.5v15l12.5-7.5z" class="s"/>',
  pause: '<rect x="6" y="4.5" width="4" height="15" rx="1"/><rect x="14" y="4.5" width="4" height="15" rx="1"/>',
  download: '<path d="M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M5 19.5h14"/>',
  up: '<path d="M7 10.5V20H4.5a1 1 0 0 1-1-1v-7.5a1 1 0 0 1 1-1zm0 0 4-7a2.2 2.2 0 0 1 2.8 2.6L13 9.5h5.6a2 2 0 0 1 2 2.4l-1.4 6.5a2 2 0 0 1-2 1.6H7"/>',
  down: '<path d="M7 13.5V4H4.5a1 1 0 0 0-1 1v7.5a1 1 0 0 0 1 1zm0 0 4 7a2.2 2.2 0 0 0 2.8-2.6L13 14.5h5.6a2 2 0 0 0 2-2.4L19.2 5.6a2 2 0 0 0-2-1.6H7"/>',
  star: '<path d="m12 3.2 2.7 5.6 6.1.8-4.5 4.2 1.1 6.1L12 17l-5.4 2.9 1.1-6.1-4.5-4.2 6.1-.8z"/>',
  upload: '<path d="M12 16V4.5m0 0L7.5 9M12 4.5 16.5 9M5 19.5h14"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4"/>',
  trash: '<path d="M4.5 7h15M10 11v6m4-6v6M6.5 7l1 12.5h9l1-12.5M9.5 7V4.5h5V7"/>',
  reply: '<path d="M10 8 5 12.5l5 4.5M5.5 12.5H14a5 5 0 0 1 5 5V19"/>',
  full: '<path d="M4.5 9V4.5H9M15 4.5h4.5V9M19.5 15v4.5H15M9 19.5H4.5V15"/>',
  vol: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4zM15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
  file: '<path d="M14 3.5H7a1.5 1.5 0 0 0-1.5 1.5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8zm0 0V8h4.5M9 13.5h6M9 17h4"/>',
  out: '<path d="M14 4.5h4a1.5 1.5 0 0 1 1.5 1.5v12a1.5 1.5 0 0 1-1.5 1.5h-4M10 16.5 5.5 12 10 7.5M5.5 12H15"/>',
};
const SOLID = new Set(["play", "pause", "star"]);

function icon(name) {
  const s = document.createElementNS(SVG_NS, "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("aria-hidden", "true");
  if (SOLID.has(name)) s.classList.add("solid");
  s.innerHTML = ICONS[name]; // constant markup only
  return s;
}

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "css") for (const [p, val] of Object.entries(v)) el.style.setProperty(p, val);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  append(el, kids);
  return el;
}
function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: { "X-Requested-With": "keyfall" }, credentials: "same-origin" };
  if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch {
    throw Object.assign(new Error("Can't reach the server"), { status: 0 });
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.error || `Request failed (${res.status})`), { status: res.status });
  return data;
}

let toastTimer;
function toast(msg, isError = false) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.toggle("err", isError);
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

const fmtDur = (s) => { s = Math.max(0, Math.round(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const fmtNum = (n) => n.toLocaleString("en-US");
function fmtAgo(ts) {
  const d = Date.now() / 1000 - ts;
  if (d < 60) return "just now";
  const steps = [[3600, 60, "min"], [86400, 3600, "h"], [604800, 86400, "d"], [2629800, 604800, "w"], [31557600, 2629800, "mo"]];
  for (const [lim, div, unit] of steps) if (d < lim) return `${Math.floor(d / div)} ${unit} ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
const fmtDate = (ts) => new Date(ts * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });

function avatar(name) {
  let hash = 0;
  for (const c of name) hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
  return h("span", { class: "avatar", "aria-hidden": "true", css: { background: `hsl(${hash % 360} 52% 64%)` } },
    name[0].toUpperCase());
}

function stars(value, size) {
  const pct = value ? (value / 5) * 100 : 0;
  const row = (cls) => h("span", { class: `row ${cls}` }, [0, 1, 2, 3, 4].map(() => icon("star")));
  const el = h("span", { class: "stars", role: "img", "aria-label": value ? `${value.toFixed(1)} out of 5 stars` : "No ratings yet" },
    row("base"), h("span", { class: "row fill", css: { width: `${pct}%` } }, [0, 1, 2, 3, 4].map(() => icon("star"))));
  if (size) {
    el.style.setProperty("width", `${size * 5}px`);
    el.style.setProperty("height", `${size}px`);
    el.querySelectorAll("svg").forEach((s) => { s.style.width = `${size}px`; s.style.height = `${size}px`; });
  }
  return el;
}

const LEVELS = ["Beginner", "Easy", "Intermediate", "Advanced", "Expert"];
function diffMeter(song, withLabel = true) {
  const l = LEVELS.indexOf(song.level) + 1;
  return h("span", { class: "diff", "data-l": String(l), title: `Difficulty ${song.difficulty}/100` },
    h("span", { class: "diff-bar", "aria-hidden": "true" }, [1, 2, 3, 4, 5].map(() => h("i"))),
    withLabel ? h("span", null, song.level) : null);
}

function link(href, attrs, ...kids) {
  return h("a", { href, "data-link": true, ...attrs }, ...kids);
}

/* ====================================================================== auth */
function renderTop() {
  const nav = document.getElementById("top-actions");
  nav.replaceChildren();
  nav.append(link("/upload", { class: "btn btn-primary", title: "Upload a song" }, icon("upload"), h("span", { class: "label" }, "Upload")));
  if (state.user) {
    nav.append(
      link(`/u/${encodeURIComponent(state.user.username)}`, { class: "user-chip", title: "Your uploads" },
        avatar(state.user.username), h("span", { class: "label" }, state.user.username)),
      h("button", {
        class: "icon-btn", title: "Sign out", "aria-label": "Sign out",
        onclick: async () => {
          await api("/api/auth/logout", { method: "POST" }).catch(() => {});
          state.user = null;
          renderTop();
          render();
          toast("Signed out");
        },
      }, icon("out")));
  } else {
    nav.append(h("button", { class: "btn", onclick: () => openAuth("login") }, "Sign in"));
  }
}

function openAuth(mode = "login", reason = "") {
  return new Promise((resolve) => {
    let current = mode;
    const err = h("p", { class: "error", hidden: true });
    const user = h("input", { class: "input", name: "username", autocomplete: "username", required: true, maxlength: "24" });
    const pass = h("input", { class: "input", name: "password", type: "password", required: true, minlength: "8" });
    const submit = h("button", { class: "btn btn-primary", type: "submit" });
    const tabs = h("div", { class: "tabs", role: "tablist" });
    const title = h("h2");
    const lede = h("p", { class: "lede" });
    const sync = () => {
      title.textContent = current === "login" ? "Welcome back" : "Create an account";
      lede.textContent = reason || (current === "login" ? "Sign in to rate, review, comment and upload." : "Pick a username. No email needed.");
      submit.textContent = current === "login" ? "Sign in" : "Create account";
      pass.setAttribute("autocomplete", current === "login" ? "current-password" : "new-password");
      [...tabs.children].forEach((b) => b.classList.toggle("on", b.dataset.mode === current));
      err.hidden = true;
    };
    for (const [m, label] of [["login", "Sign in"], ["register", "Create account"]]) {
      tabs.append(h("button", { type: "button", "data-mode": m, onclick: () => { current = m; sync(); } }, label));
    }
    const form = h("form", {
      class: "modal-body",
      onsubmit: async (e) => {
        e.preventDefault();
        submit.disabled = true;
        try {
          const r = await api(`/api/auth/${current}`, { method: "POST", body: { username: user.value.trim(), password: pass.value } });
          state.user = r.user;
          renderTop();
          dlg.close();
          toast(current === "login" ? `Signed in as ${r.user.username}` : `Welcome, ${r.user.username}`);
          resolve(true);
          render(true);
        } catch (ex) {
          err.textContent = ex.message;
          err.hidden = false;
        } finally {
          submit.disabled = false;
        }
      },
    }, title, lede, tabs, err,
      h("div", { class: "field" }, h("label", null, "Username"), user),
      h("div", { class: "field" }, h("label", null, "Password"), pass,
        h("span", { class: "hint" }, "At least 8 characters.")),
      h("div", { class: "form-row" },
        h("button", { class: "btn btn-ghost", type: "button", onclick: () => dlg.close() }, "Cancel"), submit));
    const dlg = h("dialog", { class: "modal" }, form);
    dlg.addEventListener("close", () => { dlg.remove(); resolve(false); });
    document.body.append(dlg);
    sync();
    dlg.showModal();
    user.focus();
  });
}

async function needUser(reason) {
  if (state.user) return true;
  return openAuth("login", reason);
}

/* ====================================================================== router */
const ROUTES = [
  [/^\/$/, () => libraryView()],
  [/^\/u\/([^/]+)$/, (m) => libraryView(decodeURIComponent(m[1]))],
  [/^\/song\/(\d+)$/, (m) => songView(+m[1])],
  [/^\/song\/(\d+)\/edit$/, (m) => songForm(+m[1])],
  [/^\/upload$/, () => songForm(null)],
];

function navigate(url, replace = false) {
  history[replace ? "replaceState" : "pushState"](null, "", url);
  render();
}

function render(keepScroll = false) {
  for (const fn of teardown) fn();
  teardown = [];
  preview.stop();
  const path = location.pathname;
  for (const [re, fn] of ROUTES) {
    const m = path.match(re);
    if (m) {
      if (!keepScroll) window.scrollTo(0, 0);
      fn(m);
      return;
    }
  }
  $view.replaceChildren(h("div", { class: "empty" }, h("h2", null, "Page not found"),
    h("p", null, link("/", { class: "btn" }, "Back to the library"))));
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-link]");
  if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
  e.preventDefault();
  navigate(a.getAttribute("href"));
});
window.addEventListener("popstate", () => render(true));

const searchInput = document.getElementById("search");
let searchTimer;
searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    const p = location.pathname === "/" ? new URLSearchParams(location.search) : new URLSearchParams();
    const q = searchInput.value.trim();
    if (location.pathname === "/" && q === (p.get("q") || "")) return; // e.g. only a space was added
    q ? p.set("q", q) : p.delete("q");
    const url = "/" + (p.toString() ? `?${p}` : "");
    if (location.pathname === "/") { history.replaceState(null, "", url); render(true); } else navigate(url);
  }, 220);
});
document.getElementById("search-form").addEventListener("submit", (e) => { e.preventDefault(); searchInput.blur(); });

/* ====================================================================== library */
const SORT_OPTIONS = [
  ["title:asc", "Title A–Z"], ["artist:asc", "Artist A–Z"], ["newest:desc", "Newest"],
  ["rating:desc", "Top rated"], ["likes:desc", "Most liked"], ["downloads:desc", "Most downloaded"],
  ["plays:desc", "Most played"], ["difficulty:asc", "Easiest first"], ["difficulty:desc", "Hardest first"],
  ["duration:asc", "Shortest"], ["duration:desc", "Longest"],
];

function libraryView(uploader = null) {
  const params = new URLSearchParams(location.search);
  if (uploader) params.set("uploader", uploader);
  // Only sync the box when the query really differs (e.g. back button); never strip what the user
  // is typing, otherwise a trailing space disappears before the next word can be typed.
  if (searchInput.value.trim() !== (params.get("q") || "")) searchInput.value = params.get("q") || "";
  const setParam = (k, v) => {
    const p = new URLSearchParams(location.search);
    v ? p.set(k, v) : p.delete(k);
    history.replaceState(null, "", location.pathname + (p.toString() ? `?${p}` : ""));
    render(true);
  };
  const meta = state.meta;
  const cat = params.get("category") || "";
  const sortKey = `${params.get("sort") || "title"}:${params.get("dir") || (["title", "artist", "difficulty", "duration"].includes(params.get("sort") || "title") ? "asc" : "desc")}`;

  const countEl = h("span", { class: "count num" });
  const title = uploader ? `Uploads by ${uploader}` : params.get("q") ? "Search results" : "Library";
  const head = h("div", { class: "lib-head" }, h("h1", null, title, countEl));

  const chips = uploader ? null : h("div", { class: "chips", role: "tablist", "aria-label": "Category" },
    h("button", { class: `chip${cat ? "" : " on"}`, onclick: () => setParam("category", "") }, "All", h("b", null, meta.total)),
    meta.categories.filter((c) => c.count).map((c) =>
      h("button", { class: `chip${cat === c.name ? " on" : ""}`, onclick: () => setParam("category", c.name) }, c.name, h("b", null, c.count))));

  const sel = (name, value, options, onchange, label) => h("select", { class: "select", "aria-label": label, onchange },
    options.map(([v, t]) => h("option", { value: v, selected: v === value }, t)));
  const filters = h("div", { class: "filters" },
    sel("level", params.get("level") || "", [["", "Any difficulty"], ...LEVELS.map((l) => [l.toLowerCase(), l])],
      (e) => setParam("level", e.target.value), "Difficulty"),
    uploader ? null : sel("source", params.get("source") || "", [["", "All songs"], ["library", "Bundled library"], ["community", `Community uploads (${meta.sources.community || 0})`]],
      (e) => setParam("source", e.target.value), "Source"),
    h("span", { class: "spacer" }),
    sel("sort", sortKey, SORT_OPTIONS, (e) => {
      const [s, d] = e.target.value.split(":");
      const p = new URLSearchParams(location.search);
      p.set("sort", s); p.set("dir", d);
      history.replaceState(null, "", location.pathname + `?${p}`);
      render(true);
    }, "Sort by"));

  const list = h("ul", { class: "song-list" });
  const more = h("div", { class: "load-more" });
  const listHead = h("div", { class: "list-head", "aria-hidden": "true" },
    h("span"), h("span", null, "Song"), h("span", { class: "col-diff" }, "Difficulty"), h("span", { class: "col-dur r" }, "Length"),
    h("span", { class: "r" }, "Rating"), h("span", { class: "col-votes r" }, "Votes"));
  $view.replaceChildren(head, chips, filters, listHead, list, more);
  for (let i = 0; i < 8; i++) list.append(h("li", { class: "skeleton" }));

  let offset = 0;
  const load = async () => {
    const q = new URLSearchParams(params);
    q.set("offset", offset);
    q.set("limit", 40);
    const btn = more.firstChild;
    if (btn) btn.disabled = true;
    try {
      const r = await api(`/api/songs?${q}`);
      if (offset === 0) list.replaceChildren();
      countEl.textContent = fmtNum(r.total) + (r.total === 1 ? " song" : " songs");
      r.songs.forEach((s) => list.append(songRow(s)));
      offset += r.songs.length;
      more.replaceChildren(offset < r.total
        ? h("button", { class: "btn", onclick: load }, `Show more (${fmtNum(r.total - offset)} left)`) : "");
      if (!r.total) {
        list.replaceChildren(h("li", { class: "empty" },
          h("h2", null, uploader ? "No uploads yet" : "Nothing matches"),
          h("p", null, uploader ? "Songs this user uploads will show up here." : "Try a different spelling, or clear the filters."),
          uploader ? null : link("/", { class: "btn" }, "Clear filters")));
      }
    } catch (e) {
      list.replaceChildren(h("li", { class: "empty" }, h("h2", null, "Couldn't load songs"), h("p", null, e.message)));
    }
  };
  load();
}

function songRow(s) {
  const url = `/song/${s.id}`;
  const ring = h("span", { class: "ring" });
  const btnIcon = h("span", null, icon("play"));
  const qp = h("button", {
    class: "qp-btn", "aria-label": `Preview ${s.title}`, title: "Quick listen",
    onclick: (e) => {
      e.stopPropagation();
      preview.toggle(s.id, (st, p) => {
        if (st === "progress") { ring.style.setProperty("--p", p); return; }
        const on = st === "playing" || st === "loading";
        qp.classList.toggle("active", on);
        btnIcon.replaceChildren(icon(on ? "pause" : "play"));
        if (!on) ring.style.setProperty("--p", 0);
        if (st === "error") toast("Couldn't play this song", true);
      });
    },
  }, ring, btnIcon);
  const sub = [s.artist, s.arranger ? `arr. ${s.arranger}` : null].filter(Boolean).join(" · ");
  const ratingText = s.rating ? `${s.rating.toFixed(1)} (${s.review_count})` : "No reviews";
  return h("li", { class: "song-row", onclick: () => navigate(url) },
    h("div", { class: "cover-wrap" }, h("img", { src: s.thumb, alt: "", loading: "lazy", width: "56", height: "56" }), qp),
    h("div", { class: "song-main" },
      h("div", { class: "song-title" }, link(url, { onclick: (e) => {
        e.stopPropagation();
        if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) { e.preventDefault(); navigate(url); }
      } }, s.title),
        s.version ? h("span", { class: "badge" }, s.version) : null,
        s.source === "community" ? h("span", { class: "badge community" }, "Community") : null),
      h("div", { class: "song-sub" }, sub),
      h("div", { class: "mobile-meta" }, diffMeter(s), h("span", null, "·"), h("span", { class: "num" }, fmtDur(s.duration)))),
    h("div", { class: "col-diff" }, diffMeter(s)),
    h("div", { class: "col-dur r num muted" }, fmtDur(s.duration)),
    h("div", { class: "rating-cell" }, stars(s.rating), h("span", null, ratingText)),
    h("div", { class: "col-votes r votes-cell num" },
      h("span", { title: "Likes" }, icon("up"), s.likes), h("span", { title: "Dislikes" }, icon("down"), s.dislikes)),
    h("div", { class: "mobile-end" },
      s.rating ? h("span", null, `★ ${s.rating.toFixed(1)}`) : null,
      h("span", { class: "num" }, `▲ ${s.likes}`)));
}

/* ====================================================================== song page */
async function songView(id) {
  $view.replaceChildren(h("div", { class: "skeleton" }), h("div", { class: "skeleton" }));
  let song, pb;
  try {
    [song, pb] = await Promise.all([api(`/api/songs/${id}`), api(`/api/songs/${id}/notes`)]);
  } catch (e) {
    $view.replaceChildren(h("div", { class: "empty" }, h("h2", null, e.status === 404 ? "Song not found" : "Couldn't load this song"),
      h("p", null, e.message), link("/", { class: "btn" }, "Back to the library")));
    return;
  }
  if (location.pathname !== `/song/${id}`) return; // navigated away while loading
  document.title = `${song.title} — ${song.artist} · Keyfall`;
  teardown.push(() => { document.title = "Keyfall — piano song library"; });

  const colors = trackColors(pb.tracks);
  const transport = new Transport(pb);
  teardown.push(() => transport.destroy());

  /* ---- hero */
  const voteBox = h("div", { class: "vote" });
  const drawVotes = () => {
    voteBox.replaceChildren(
      h("button", { class: `up${song.my_vote === 1 ? " on" : ""}`, "aria-pressed": String(song.my_vote === 1), title: "Like", onclick: () => vote(1) }, icon("up"), song.likes),
      h("button", { class: `down${song.my_vote === -1 ? " on" : ""}`, "aria-pressed": String(song.my_vote === -1), title: "Dislike", onclick: () => vote(-1) }, icon("down"), song.dislikes));
  };
  const vote = async (v) => {
    if (!(await needUser("Sign in to like or dislike songs."))) return;
    try {
      const r = await api(`/api/songs/${id}/vote`, { method: "POST", body: { value: song.my_vote === v ? 0 : v } });
      Object.assign(song, r);
      drawVotes();
    } catch (e) { toast(e.message, true); }
  };
  drawVotes();

  const ratingInline = h("span", { class: "rating-inline" });
  const drawRatingInline = () => ratingInline.replaceChildren(stars(song.rating),
    song.review_count ? `${song.rating.toFixed(1)} · ${song.review_count} review${song.review_count > 1 ? "s" : ""}` : "No reviews yet");
  drawRatingInline();

  const stat = (k, v) => h("div", { class: "stat" }, h("dt", null, k), h("dd", null, v));
  const playerEl = h("section", { class: "player", "aria-label": "Song preview" });
  const hero = h("div", { class: "hero" },
    h("div", { class: "hero-cover" }, h("img", { src: song.cover, alt: `Cover for ${song.title}` })),
    h("div", null,
      h("div", null,
        h("span", { class: "badge", css: { "margin-left": "0" } }, song.category),
        song.source === "community" ? h("span", { class: "badge community" }, "Community upload") : null,
        song.version ? h("span", { class: "badge" }, song.version) : null),
      h("h1", null, song.title),
      h("div", { class: "by" },
        link(`/?q=${encodeURIComponent(song.artist)}`, null, song.artist),
        song.arranger ? h("span", null, " · arranged by ", link(`/?q=${encodeURIComponent(song.arranger)}`, null, song.arranger)) : null),
      song.uploader ? h("div", { class: "muted", css: { "margin-top": "4px", "font-size": "14px" } },
        "Uploaded by ", link(`/u/${encodeURIComponent(song.uploader)}`, { css: { color: "var(--text)" } }, song.uploader), ` · ${fmtDate(song.created_at)}`) : null,
      albumCredit(song),
      song.tags.length ? h("div", { class: "tags" }, song.tags.map((t) => link(`/?q=${encodeURIComponent(t)}`, { class: "badge" }, t))) : null,
      h("dl", { class: "stat-grid" },
        stat("Difficulty", diffMeter(song)),
        stat("Length", fmtDur(song.duration)),
        stat("Notes", fmtNum(song.notes)),
        stat("Tempo", `${Math.round(song.bpm)} BPM`),
        stat("Range", song.range),
        stat("Plays", fmtNum(song.plays))),
      h("div", { class: "actions" },
        h("button", { class: "btn btn-primary", onclick: () => { playerEl.scrollIntoView({ behavior: "smooth", block: "center" }); transport.play(); } }, icon("play"), "Play preview"),
        h("a", { class: "btn", href: `/api/songs/${id}/download`, download: "" }, icon("download"), "Download MIDI"),
        voteBox,
        song.can_edit ? link(`/song/${id}/edit`, { class: "btn btn-ghost" }, icon("edit"), "Edit") : null,
        ratingInline)));

  /* ---- player */
  const canvas = h("canvas", { class: "roll", "aria-label": "Falling notes. Tap to play or pause, drag up or down to scrub." });
  const playBtn = h("button", { class: "play", "aria-label": "Play", onclick: () => transport.toggle() }, icon("play"));
  const timeEl = h("span", { class: "time" });
  const seek = h("input", { type: "range", class: "seek", min: "0", max: String(pb.duration), step: "0.05", value: "0", "aria-label": "Position" });
  let seeking = false;
  seek.addEventListener("pointerdown", () => { seeking = true; });
  seek.addEventListener("input", () => { transport.seek(+seek.value); });
  seek.addEventListener("change", () => { seeking = false; });
  const speed = h("select", { class: "select", "aria-label": "Speed", onchange: (e) => transport.setSpeed(+e.target.value) },
    [0.5, 0.75, 1, 1.25, 1.5].map((v) => h("option", { value: String(v), selected: v === 1 }, `${Math.round(v * 100)}%`)));
  const handBtns = pb.tracks.map((t, i) => {
    const label = t.hand === "R" ? "Right" : t.hand === "L" ? "Left" : t.name;
    const b = h("button", {
      class: "hand-toggle", css: { "--c": colors[i] }, "aria-pressed": "true", title: `${t.name} — tap to mute`,
      onclick: () => {
        const off = !transport.muted.has(i);
        transport.setMuted(i, off);
        b.classList.toggle("off", off);
        b.setAttribute("aria-pressed", String(!off));
      },
    }, h("i"), label.length > 14 ? label.slice(0, 13) + "…" : label);
    return b;
  });
  const vol = h("input", { type: "range", class: "vol", min: "0", max: "1", step: "0.01", value: String(synth.volume), "aria-label": "Volume",
    oninput: (e) => synth.setVolume(+e.target.value) });
  const fsBtn = h("button", { class: "icon-btn", title: "Fullscreen", "aria-label": "Fullscreen",
    onclick: () => (document.fullscreenElement ? document.exitFullscreen() : playerEl.requestFullscreen?.()) }, icon("full"));
  append(playerEl, [canvas, h("div", { class: "ctl" }, playBtn, timeEl, seek,
    h("div", { class: "ctl-group" }, handBtns.length <= 4 ? handBtns : handBtns.slice(0, 4)),
    speed, h("span", { class: "vol-ico muted" }, icon("vol")), vol, fsBtn)]);

  /* ---- details + side */
  const descBlock = h("div", { class: "section" }, h("h2", null, "About this arrangement"),
    song.description ? h("p", { class: "description" }, song.description)
      : h("p", { class: "placeholder" }, song.source === "library" ? "Part of the bundled library — no description yet." : "The uploader didn't add a description."));
  const reviewsBlock = h("section", { class: "section", id: "reviews" });
  const commentsBlock = h("section", { class: "section", id: "comments" });

  const kv = (k, v) => [h("dt", null, k), h("dd", { class: "num" }, v)];
  const side = h("aside", null,
    h("div", { class: "side-block" }, h("h3", null, "Details"),
      h("dl", { class: "kv" },
        kv("Difficulty score", `${song.difficulty} / 100`),
        kv("Avg. density", `${song.nps} notes/s`),
        kv("Busiest moment", `${song.peak_nps} notes/s`),
        kv("Largest chord", `${song.polyphony} notes`),
        kv("Time signature", song.time_sig),
        song.key ? kv("Key", song.key.replace("m", " minor").replace(/^([A-G][#b]?)$/, "$1 major")) : null,
        kv("Downloads", fmtNum(song.downloads)),
        kv("File size", `${(song.size / 1024).toFixed(1)} KB`))),
    h("div", { class: "side-block" }, h("h3", null, `Tracks (${pb.tracks.length})`),
      h("ul", { class: "track-list" }, pb.tracks.map((t, i) => h("li", null, h("i", { css: { "--c": colors[i] } }),
        h("span", null, t.hand === "R" ? `Right hand · ${t.name}` : t.hand === "L" ? `Left hand · ${t.name}` : t.name),
        h("small", null, fmtNum(t.notes)))))),
    song.versions.length ? h("div", { class: "side-block" }, h("h3", null, "Other versions"),
      h("ul", { class: "mini-list" }, song.versions.map((v) => h("li", null, link(`/song/${v.id}`, null,
        h("img", { src: v.thumb, alt: "", loading: "lazy" }),
        h("div", null, h("div", { class: "t" }, v.version || v.arranger || "Version " + v.id),
          h("div", { class: "s" }, `${v.level} · ${fmtDur(v.duration)}${v.arranger ? " · " + v.arranger : ""}`))))))) : null);

  $view.replaceChildren(
    h("nav", { class: "crumbs" }, link("/", null, "Library"), "/", link(`/?category=${encodeURIComponent(song.category)}`, null, song.category), "/", h("span", null, song.title)),
    hero, playerEl,
    h("p", { class: "player-hint" }, "Tap the notes to play or pause, drag them up or down to scrub. Keyboard: Space plays, ← → skip 5 seconds."),
    h("div", { class: "cols" }, h("div", null, descBlock, reviewsBlock, commentsBlock), side));

  const roll = new PianoRoll(canvas, transport);
  teardown.push(() => roll.destroy());

  let counted = false;
  let raf;
  const tick = () => {
    raf = requestAnimationFrame(tick);
    const t = Math.min(transport.time, pb.duration);
    timeEl.textContent = `${fmtDur(t)} / ${fmtDur(pb.duration)}`;
    if (!seeking) seek.value = String(t);
    seek.style.setProperty("--fill", `${(t / pb.duration) * 100}%`);
  };
  tick();
  teardown.push(() => cancelAnimationFrame(raf));
  transport.on((type) => {
    playBtn.replaceChildren(icon(transport.playing ? "pause" : "play"));
    playBtn.setAttribute("aria-label", transport.playing ? "Pause" : "Play");
    if (type === "play" && !counted) {
      counted = true;
      api(`/api/songs/${id}/play`, { method: "POST" }).catch(() => {});
    }
  });
  const onKey = (e) => {
    if (e.target.closest("input, textarea, select, button, [contenteditable]")) return;
    if (e.code === "Space") { e.preventDefault(); transport.toggle(); }
    else if (e.key === "ArrowRight") transport.seek(transport.time + 5);
    else if (e.key === "ArrowLeft") transport.seek(transport.time - 5);
  };
  document.addEventListener("keydown", onKey);
  teardown.push(() => document.removeEventListener("keydown", onKey));
  teardown.push(() => { if (document.fullscreenElement) document.exitFullscreen().catch(() => {}); });

  const refreshSong = async () => {
    try {
      Object.assign(song, await api(`/api/songs/${id}`));
      drawRatingInline();
    } catch { /* non-critical */ }
  };
  renderReviews(reviewsBlock, song, refreshSong);
  renderComments(commentsBlock, song);
}

function albumCredit(song) {
  if (!song.album) return null;
  const sources = { deezer: "Deezer", itunes: "Apple Music" };
  const safe = /^https:\/\//.test(song.cover_link || "");
  return h("div", { class: "album-line" }, "From the album ", h("cite", null, song.album),
    sources[song.cover_source] ? h("span", { class: "credit" }, " · artwork via ",
      safe ? h("a", { href: song.cover_link, target: "_blank", rel: "noopener noreferrer" }, sources[song.cover_source])
        : sources[song.cover_source]) : null);
}

/* ---- reviews */
async function renderReviews(box, song, onChange) {
  const id = song.id;
  let data;
  try { data = await api(`/api/songs/${id}/reviews`); } catch (e) {
    box.replaceChildren(h("h2", null, "Reviews"), h("p", { class: "error" }, e.message));
    return;
  }
  const mine = data.reviews.find((r) => r.mine);
  const count = data.reviews.length;
  const avg = count ? data.reviews.reduce((a, r) => a + r.stars, 0) / count : null;
  const hist = [5, 4, 3, 2, 1].map((n) => {
    const c = data.reviews.filter((r) => r.stars === n).length;
    return h("div", null, h("span", null, n), h("span", { class: "bar" }, h("span", { css: { width: count ? `${(c / count) * 100}%` : "0%" } })), h("span", { class: "num" }, c));
  });
  const summary = h("div", { class: "summary" },
    h("div", null, h("div", { class: "big num" }, avg ? avg.toFixed(1) : "–"), h("div", { class: "big-sub" }, stars(avg)),
      h("div", { class: "big-sub" }, count ? `${count} review${count > 1 ? "s" : ""}` : "No reviews yet")),
    h("div", { class: "hist" }, hist));

  let form;
  if (state.user) {
    let picked = mine ? mine.stars : 0;
    const starBtns = [1, 2, 3, 4, 5].map((n) => h("button", {
      type: "button", "aria-label": `${n} star${n > 1 ? "s" : ""}`,
      onclick: () => { picked = n; paint(); },
    }, icon("star")));
    const paint = () => starBtns.forEach((b, i) => { b.classList.toggle("on", i < picked); b.setAttribute("aria-pressed", String(i < picked)); });
    paint();
    const body = h("textarea", { rows: "3", maxlength: "3000", placeholder: "How does it play? Is the arrangement accurate, are the hands split well, is it fun?" });
    body.value = mine ? mine.body : "";
    const btn = h("button", { class: "btn btn-primary btn-sm", type: "submit" }, mine ? "Update review" : "Post review");
    form = h("form", {
      class: "card", css: { "margin-bottom": "8px" },
      onsubmit: async (e) => {
        e.preventDefault();
        if (!picked) { toast("Pick a star rating first", true); return; }
        btn.disabled = true;
        try {
          await api(`/api/songs/${id}/reviews`, { method: "POST", body: { stars: picked, body: body.value } });
          toast(mine ? "Review updated" : "Thanks for the review");
          await onChange();
          renderReviews(box, song, onChange);
        } catch (ex) { toast(ex.message, true); btn.disabled = false; }
      },
    }, h("div", { class: "entry-head" }, avatar(state.user.username), h("span", { class: "who" }, mine ? "Your review" : "Rate this song"),
      h("span", { class: "star-input", role: "group", "aria-label": "Your rating" }, starBtns)),
    h("div", { css: { "margin-top": "10px" } }, body),
    h("div", { class: "form-row" }, h("span", { class: "left" }, "Text is optional."), btn));
  } else {
    form = h("div", { class: "card" }, h("p", { css: { margin: "0 0 10px" }, class: "muted" }, "Played this one? Leave a rating and tell others how it went."),
      h("button", { class: "btn btn-sm", onclick: () => openAuth("login", "Sign in to review songs.") }, "Sign in to review"));
  }

  const list = h("ul", { class: "feed" }, data.reviews.map((r) => h("li", null,
    h("div", { class: "entry-head" }, avatar(r.username),
      link(`/u/${encodeURIComponent(r.username)}`, { class: "who" }, r.username), stars(r.stars, 14),
      h("span", { class: "when", title: new Date(r.updated_at * 1000).toLocaleString() }, fmtAgo(r.updated_at) + (r.updated_at > r.created_at + 60 ? " · edited" : "")),
      r.can_delete ? h("span", { class: "tools" }, h("button", {
        class: "icon-btn", title: "Delete review", "aria-label": "Delete review",
        onclick: async () => {
          if (!confirm("Delete this review?")) return;
          try { await api(`/api/reviews/${r.id}`, { method: "DELETE" }); await onChange(); renderReviews(box, song, onChange); } catch (e) { toast(e.message, true); }
        },
      }, icon("trash"))) : null),
    r.body ? h("p", { class: "entry-body" }, r.body) : null)));

  box.replaceChildren(h("h2", null, "Reviews", h("small", null, count || "")), summary, form, list);
}

/* ---- comments */
async function renderComments(box, song) {
  const id = song.id;
  let data;
  try { data = await api(`/api/songs/${id}/comments`); } catch (e) {
    box.replaceChildren(h("h2", null, "Comments"), h("p", { class: "error" }, e.message));
    return;
  }
  const post = async (body, parent_id, btn) => {
    if (!(await needUser("Sign in to join the discussion."))) return;
    btn.disabled = true;
    try {
      data = await api(`/api/songs/${id}/comments`, { method: "POST", body: { body, parent_id } });
      draw();
    } catch (e) { toast(e.message, true); btn.disabled = false; }
  };
  const composer = (parent_id, placeholder, onCancel) => {
    const ta = h("textarea", { rows: parent_id ? "2" : "3", maxlength: "2000", placeholder });
    const btn = h("button", { class: "btn btn-primary btn-sm", type: "submit" }, parent_id ? "Reply" : "Post comment");
    const f = h("form", {
      class: parent_id ? "reply-form" : null,
      onsubmit: (e) => { e.preventDefault(); if (ta.value.trim()) post(ta.value, parent_id, btn); },
    }, ta, h("div", { class: "form-row" }, onCancel ? h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: onCancel }, "Cancel") : null, btn));
    return [f, ta];
  };
  const entry = (c, isReply) => {
    const li = h("li", null);
    const head = h("div", { class: "entry-head" }, avatar(c.username),
      link(`/u/${encodeURIComponent(c.username)}`, { class: "who" }, c.username),
      c.by_uploader ? h("span", { class: "op", title: "Uploaded this song" }, "UPLOADER") : null,
      h("span", { class: "when", title: new Date(c.created_at * 1000).toLocaleString() }, fmtAgo(c.created_at)),
      h("span", { class: "tools" },
        isReply ? null : h("button", {
          class: "btn btn-ghost btn-sm", onclick: async () => {
            if (!(await needUser("Sign in to reply."))) return;
            if (li.querySelector(".reply-form")) return;
            const [f, ta] = composer(c.id, `Reply to ${c.username}`, () => f.remove());
            li.insertBefore(f, li.querySelector(".replies"));
            ta.focus();
          },
        }, icon("reply"), "Reply"),
        c.can_delete ? h("button", {
          class: "icon-btn", title: "Delete comment", "aria-label": "Delete comment",
          onclick: async () => {
            if (!confirm(isReply ? "Delete this reply?" : "Delete this comment and its replies?")) return;
            try {
              await api(`/api/comments/${c.id}`, { method: "DELETE" });
              data = await api(`/api/songs/${id}/comments`);
              draw();
            } catch (e) { toast(e.message, true); }
          },
        }, icon("trash")) : null));
    append(li, [head, h("p", { class: "entry-body" }, c.body)]);
    return li;
  };
  const draw = () => {
    const top = data.comments.filter((c) => !c.parent_id);
    const replies = (pid) => data.comments.filter((c) => c.parent_id === pid);
    const [form] = state.user ? composer(null, "Share tips, fingering ideas or questions…") : [null];
    const list = h("ul", { class: "feed" }, top.map((c) => {
      const li = entry(c, false);
      const rs = replies(c.id);
      if (rs.length) li.append(h("ul", { class: "replies" }, rs.map((r) => entry(r, true))));
      return li;
    }));
    box.replaceChildren(h("h2", null, "Comments", h("small", null, data.comments.length || "")),
      form || h("div", { class: "card" }, h("button", { class: "btn btn-sm", onclick: () => openAuth("login", "Sign in to join the discussion.") }, "Sign in to comment")),
      top.length ? list : h("p", { class: "placeholder" }, "No comments yet."));
  };
  draw();
}

/* ====================================================================== upload / edit */
const VERSION_HINTS = ["Beginner", "Easy", "Simple", "Intermediate", "Advanced", "Hard", "Piano solo", "Duet"];

function readDataUrl(file) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.onerror = () => rej(new Error("Couldn't read the file"));
    r.readAsDataURL(file);
  });
}

function guessFromName(name) {
  let s = name.replace(/\.(mid|midi)$/i, "").replace(/_/g, " ").replace(/\s+/g, " ").trim();
  const parts = s.split(" - ");
  return parts.length >= 2 ? { artist: parts[0].trim(), title: parts.slice(1).join(" - ").trim() } : { artist: "", title: s };
}

async function songForm(editId) {
  if (!state.user) {
    $view.replaceChildren(h("div", { class: "empty" }, h("h2", null, editId ? "Sign in to edit" : "Share an arrangement"),
      h("p", null, "You need an account to upload songs. It takes ten seconds and no email."),
      h("button", { class: "btn btn-primary", onclick: () => openAuth("register") }, "Create an account"), " ",
      h("button", { class: "btn", onclick: () => openAuth("login") }, "Sign in")));
    return;
  }
  let song = null;
  if (editId) {
    try { song = await api(`/api/songs/${editId}`); } catch (e) {
      $view.replaceChildren(h("div", { class: "empty" }, h("h2", null, "Song not found"), h("p", null, e.message)));
      return;
    }
    if (!song.can_edit) {
      $view.replaceChildren(h("div", { class: "empty" }, h("h2", null, "You can't edit this song"), h("p", null, "Only the person who uploaded it can.")));
      return;
    }
  }

  let midi = null, cover = null, removeCover = false;
  const err = h("p", { class: "error", hidden: true });
  const input = (name, attrs = {}) => h("input", { class: "input", name, value: song ? (Array.isArray(song[name]) ? song[name].join(", ") : song[name] ?? "") : "", ...attrs });
  const f = {
    title: input("title", { required: true, maxlength: "120" }),
    artist: input("artist", { required: true, maxlength: "120", placeholder: "Composer or performer" }),
    version: input("version", { maxlength: "40", list: "version-hints", placeholder: "e.g. Easy, Advanced" }),
    arranger: input("arranger", { maxlength: "80", placeholder: song ? "" : state.user.username }),
    tags: input("tags", { maxlength: "200", placeholder: "e.g. ballad, anime, left-hand workout" }),
    category: h("select", { class: "input select", name: "category" },
      state.meta.categories.map((c) => h("option", { value: c.name, selected: song ? song.category === c.name : c.name === "Other" }, c.name))),
    description: h("textarea", { name: "description", rows: "5", maxlength: "2000", placeholder: "What's special about this arrangement? Tempo changes, fingering, which section is hardest…" }),
  };
  f.description.value = song ? song.description : "";

  const fileInput = h("input", { type: "file", accept: ".mid,.midi,audio/midi,audio/x-midi", class: "sr-only", id: "midi-file" });
  const dropLabel = h("strong", null, "Choose a MIDI file");
  const dropSub = h("span", null, "or drop it here · .mid up to 2 MB");
  const drop = h("label", { class: "drop", for: "midi-file" }, icon("file"), dropLabel, dropSub, fileInput);
  const takeMidi = async (file) => {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { toast("That file is over 2 MB", true); return; }
    const head = new Uint8Array(await file.slice(0, 4).arrayBuffer());
    const sig = String.fromCharCode(...head);
    if (sig !== "MThd" && sig !== "RIFF") { toast("That doesn't look like a MIDI file", true); return; }
    midi = { name: file.name, data: await readDataUrl(file) };
    drop.classList.add("has-file");
    dropLabel.textContent = file.name;
    dropSub.textContent = `${(file.size / 1024).toFixed(1)} KB · tap to choose another`;
    const g = guessFromName(file.name);
    if (!f.title.value) f.title.value = g.title;
    if (!f.artist.value) f.artist.value = g.artist;
  };
  fileInput.addEventListener("change", () => takeMidi(fileInput.files[0]));
  for (const ev of ["dragenter", "dragover"]) drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); });
  for (const ev of ["dragleave", "drop"]) drop.addEventListener(ev, () => drop.classList.remove("drag"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); takeMidi(e.dataTransfer.files[0]); });

  const thumb = h("div", { class: "thumb" }, song ? h("img", { src: song.cover, alt: "" }) : "Drawn from your notes");
  const coverInput = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", class: "sr-only", id: "cover-file" });
  coverInput.addEventListener("change", async () => {
    const file = coverInput.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { toast("Cover image must be under 2 MB", true); return; }
    cover = await readDataUrl(file);
    removeCover = false;
    thumb.replaceChildren(h("img", { src: URL.createObjectURL(file), alt: "" }));
  });
  const coverRow = h("div", { class: "cover-pick" }, thumb,
    h("div", null,
      h("label", { class: "btn btn-sm", for: "cover-file" }, "Choose image"), coverInput,
      song && song.custom_cover ? h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => {
        removeCover = true; cover = null;
        thumb.replaceChildren("Generated cover will be restored");
      } }, "Use generated cover") : null,
      h("p", { class: "note" }, "PNG, JPEG or WebP, square works best. Skip it and the cover is drawn from your song's own notes.")));

  const submit = h("button", { class: "btn btn-primary", type: "submit" }, song ? "Save changes" : "Publish song");
  const form = h("form", {
    onsubmit: async (e) => {
      e.preventDefault();
      err.hidden = true;
      if (!song && !midi) { err.textContent = "Choose a MIDI file to upload."; err.hidden = false; return; }
      const body = {
        title: f.title.value, artist: f.artist.value, version: f.version.value, arranger: f.arranger.value,
        category: f.category.value, tags: f.tags.value, description: f.description.value,
      };
      if (cover) body.cover = cover;
      if (removeCover) body.remove_cover = true;
      if (!song) body.midi = midi.data;
      submit.disabled = true;
      try {
        const r = song ? await api(`/api/songs/${song.id}`, { method: "PATCH", body }) : await api("/api/songs", { method: "POST", body });
        state.meta = await api("/api/meta");
        toast(song ? "Saved" : "Your song is live");
        navigate(`/song/${r.id}`, true);
      } catch (ex) {
        err.textContent = ex.message;
        err.hidden = false;
        submit.disabled = false;
        err.scrollIntoView({ block: "center" });
      }
    },
  },
  song ? null : drop,
  err,
  h("div", { class: "grid-2" },
    h("div", { class: "field" }, h("label", null, "Title *"), f.title),
    h("div", { class: "field" }, h("label", null, "Artist / composer *"), f.artist),
    h("div", { class: "field" }, h("label", null, "Version"), f.version,
      h("datalist", { id: "version-hints" }, VERSION_HINTS.map((v) => h("option", { value: v })))),
    h("div", { class: "field" }, h("label", null, "Arranged by"), f.arranger),
    h("div", { class: "field" }, h("label", null, "Category"), f.category),
    h("div", { class: "field" }, h("label", null, "Tags"), f.tags, h("span", { class: "hint" }, "Comma separated, up to 8."))),
  h("div", { class: "field" }, h("label", null, "Description"), f.description),
  h("div", { class: "field" }, h("label", null, "Cover"), coverRow),
  h("p", { class: "note" }, "Only upload arrangements you made yourself or have permission to share. Difficulty, length and tracks are worked out from the file automatically."),
  h("div", { class: "form-row" },
    song ? h("button", {
      class: "btn btn-ghost btn-danger", type: "button", css: { "margin-right": "auto" },
      onclick: async () => {
        if (!confirm(`Delete "${song.title}"? Reviews and comments go with it.`)) return;
        try {
          await api(`/api/songs/${song.id}`, { method: "DELETE" });
          state.meta = await api("/api/meta");
          toast("Song deleted");
          navigate("/", true);
        } catch (ex) { toast(ex.message, true); }
      },
    }, icon("trash"), "Delete song") : null,
    link(song ? `/song/${song.id}` : "/", { class: "btn btn-ghost" }, "Cancel"), submit));

  $view.replaceChildren(h("div", { class: "form-page" },
    h("h1", null, song ? "Edit song" : "Upload a song"),
    h("p", { class: "lede" }, song ? song.title : "Share a MIDI arrangement with everyone. It gets a falling-notes preview, ratings and comments."),
    form));
}

synth.onUnavailable = () => toast("This browser has no audio support — playing without sound", true);

/* ====================================================================== boot */
(async function boot() {
  try {
    state.meta = await api("/api/meta");
    state.user = state.meta.user;
  } catch (e) {
    $view.replaceChildren(h("div", { class: "empty" }, h("h2", null, "Can't reach the server"), h("p", null, e.message)));
    return;
  }
  renderTop();
  render();
})();
