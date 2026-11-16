/* Snapsift dashboard. Plain JS, no build step. Everything shown comes from this computer's own server;
   names and captions are only ever set as text (never as HTML), because they can come from photos.
   States: setup (choose folders) -> running (live sort) -> done (results, replay).
   ?demo   the fake camera roll in demo/      ?d=20  replay length in seconds      ?auto  replay by itself */
const params = new URLSearchParams(location.search);
const DEMO = params.has("demo");
const BASE = DEMO ? "demo/" : "data/";
const REPLAY_MS = (+params.get("d") || 12) * 1000;
const TOKENS_PER_FILE = 980;
const $ = id => document.getElementById(id);
const fmt = n => Math.round(n).toLocaleString("en-US");
const size = b => b >= 1e9 ? (b / 1e9).toFixed(1) + " GB" : b >= 1e6 ? Math.round(b / 1e6) + " MB" : b > 0 ? Math.max(1, Math.round(b / 1e3)) + " KB" : "0 MB";
const mmss = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const roughly = s => s < 50 ? "under a minute" : s < 90 ? "about a minute" : `about ${Math.round(s / 60)} min`;
const tilde = p => (p || "").replace(/^\/Users\/[^/]+/, "~");
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k.startsWith("aria-")) e.setAttribute(k, String(v));
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
};

/* lucide icons, inlined */
const ICONS = {
  images: '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  pencil: '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>',
  folder: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
  left: '<path d="m15 18-6-6 6-6"/>', right: '<path d="m9 18 6-6-6-6"/>', down: '<path d="m6 9 6 6 6-6"/>',
  reveal: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  arrow: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  broom: '<path d="m13 11 9-9"/><path d="M14.6 12.6c.8.8.9 2.1.2 3L10 22l-8-8 6.4-4.8c.9-.7 2.2-.6 3 .2Z"/><path d="m6.8 10.4 6.8 6.8"/>',
  compass: '<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>',
  map: '<polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21"/><line x1="9" x2="9" y1="3" y2="18"/><line x1="15" x2="15" y1="6" y2="21"/>',
  film: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 3v18"/><path d="M3 7.5h4"/><path d="M3 12h18"/><path d="M3 16.5h4"/><path d="M17 3v18"/><path d="M17 7.5h4"/><path d="M17 16.5h4"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
  lock: '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  stop: '<rect width="14" height="14" x="5" y="5" rx="2"/>',
  minus: '<path d="M5 12h14"/>',
  spark: '<path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z" fill="currentColor" stroke="none"/>',
  photo: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/>',
  copy: '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  disk: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  keyboard: '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10"/>',
};
const svg = n => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[n]}</svg>`;
const icon = n => { const s = el("span", { "data-icon": n }); s.innerHTML = svg(n); return s; };
const paintIcons = (root = document) => root.querySelectorAll("[data-icon]").forEach(e => { if (!e.firstChild) e.innerHTML = svg(e.dataset.icon); });
function toast(t, label, fn) {
  const e = $("toast");
  e.replaceChildren(el("span", {}, t));
  if (label) e.append(el("button", { onclick: () => { e.classList.remove("on"); fn(); } }, label));
  e.classList.add("on");
  clearTimeout(e.t);
  e.t = setTimeout(() => e.classList.remove("on"), label ? 6500 : 3200);
}
/* ---------- theme: one sun / moon button ---------- */
function setTheme(t) {
  try { localStorage.setItem("theme", t); } catch (e) {}
  document.documentElement.dataset.theme = t;
  $("theme").innerHTML = svg(t === "dark" ? "sun" : "moon") + `<span>${t === "dark" ? "Light" : "Dark"}</span>`;
  $("theme").setAttribute("aria-label", t === "dark" ? "Switch to light mode" : "Switch to dark mode");
}
const toggleTheme = () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
let theme = "light";
try { theme = localStorage.getItem("theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); } catch (e) {}
setTheme(theme === "system" ? "light" : theme);
$("theme").onclick = () => toggleTheme();

/* ---------- state ---------- */
let S = {};                                 // server state
let mode = "loading";                       // setup | running | done
let cats = [], catBy = {}, items = [], byId = {}, dupeIds = new Set(), labels = {}, events = [], report = null;
const pick = { source: null, dest: null, peek: null, advanced: false, labeler: "claude", sample: false, typing: null,
  accounts: false, model: "sonnet", layout: "flat", fix_dates: true, albums: true, second_look: true };
const REVIEWS = { dupe: "_dupes", private: "_private", junk: "_junk", unsure: "_unsure" };
let tiles = [], run = "idle", order = [], released = 0, landed = 0, t0 = 0;
const queue = [], flown = new Set();
const stats = { photos: 0, videos: 0, dupes: 0, saved: 0 };

async function api(path, body) {
  if (DEMO) { toast("This is the demo. Run ./start.sh to sort your own photos."); throw new Error("demo"); }
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
  const j = await r.json();
  if (j && j.error) { toast(j.error); throw new Error(j.error); }
  return j;
}
const getJSON = f => fetch(BASE + f, { cache: "no-store" }).then(r => r.ok ? r.json() : null).catch(() => null);

const PALETTE = ["#7b5cff", "#3d7bff", "#14b8c4", "#12a36b", "#f59e0b", "#ef6b4a", "#e0559a", "#a855f7", "#0ea5e9", "#65a30d", "#f97316", "#0d9488", "#6366f1", "#ca8a04",
  "#db2777", "#2563eb", "#059669", "#9333ea"];
function setCats(c) {
  cats = c || [];
  cats.forEach((x, i) => x.color = PALETTE[i % PALETTE.length]);
  catBy = Object.fromEntries(cats.map(x => [x.key, x]));
  catBy._dupes = { key: "_dupes", label: "Duplicates", emoji: "🗂️", kind: "review", color: "#64748b" };
  catBy._private = { key: "_private", label: "Private", emoji: "🔒", kind: "review", color: "#e5484d" };
  catBy._junk = { key: "_junk", label: "Junk", emoji: "🗑️", kind: "review", color: "#8b8fa3" };
  catBy._unsure = { key: "_unsure", label: "Not sure", emoji: "🤔", kind: "review", color: "#d97706" };
  $("k-ftotal").textContent = cats.length;
}
async function loadLibrary(withLabels) {
  const st = S.steps || {}, has = { "meta.json": !DEMO && st.apply, "events.json": !DEMO && st.events, "report.json": !DEMO && st.report, "trashed.json": !DEMO && S.trashed > 0,
    "labels.json": DEMO || st.apply, "dupes.json": DEMO || st.dupes, "source.json": true, "inventory.json": true };
  const [inv, lab, dupes, src, meta, ev, rep, trashed] = await Promise.all(
    ["inventory.json", "labels.json", "dupes.json", "source.json", "meta.json", "events.json", "report.json", "trashed.json"].map(f => has[f] ? getJSON(f) : null));
  dupeIds = new Set((dupes || []).flatMap(g => g.dupes));
  labels = withLabels && lab ? lab : {};
  events = ev || []; report = rep;
  const keptBy = {}; (dupes || []).forEach(g => g.dupes.forEach(d => keptBy[d] = g));
  const inEvent = {}; events.forEach(e => e.ids.forEach(i => inEvent[i] = inEvent[i] || e));
  const gone = new Set(trashed || []);
  items = (inv || []).map(r => {
    const m = withLabels && meta ? meta[r.id] || {} : {};
    return { ...r, cat: labels[r.id], dupe: dupeIds.has(r.id), review: m.review && m.review !== "dupe" ? m.review : null,
      caption: m.c || "", flags: m.f || "", group: keptBy[r.id] || null, event: inEvent[r.id] || null, trashed: gone.has(r.id),
      mini: `${BASE}mini/${r.id}.jpg`, src: `${BASE}thumbs/${r.id}.jpg` };
  });
  byId = Object.fromEntries(items.map(it => [it.id, it]));
  return { inv, lab, src };
}
function miniImg(it) {  // small copy for the animation; falls back to the bigger preview for older scans
  const img = el("img", { src: it.mini, alt: "" });
  img.onerror = () => { img.onerror = null; img.src = it.src; };
  return img;
}

/* ---------- header ---------- */
function setPill(kind, text) {
  $("pill").querySelector(".dot").className = "dot" + (kind ? " " + kind : "");
  $("pilltext").textContent = text + (DEMO ? " · demo" : "");
}
function setHeader() {
  const src = mode === "setup" ? pick.source : S.source;
  $("source").textContent = src ? tilde(src) + (S.limit && mode !== "setup" ? ` · sample of ${fmt(S.limit)}` : "") : "";
  $("total").hidden = !items.length || mode === "setup";
  $("total").textContent = fmt(items.length);
  $("btnOpen").hidden = !(mode === "done" && S.sorted);
  $("btnNew").hidden = mode !== "done";
  $("libname").textContent = src ? String(src).replace(/\/+$/, "").split("/").pop() || "Snapsift" : "Snapsift";
  $("tAccounts").hidden = !(S.accounts && S.accounts.length > 1);
  ["tClean", "tTrips", "tMap", "tHigh", "tShare", "tAccounts"].forEach(id => $(id).classList.toggle("locked", mode !== "done" || DEMO));
  const flagged = items.filter(i => !i.trashed && (i.dupe || i.review)).length;
  $("nClean").hidden = !(mode === "done" && flagged);
  $("nClean").textContent = flagged > 99 ? "99+" : flagged;
  $("k-checked-s").textContent = items.length && mode !== "setup" ? size(items.reduce((s, r) => s + r.bytes, 0)) + " in total" : "photos & videos";
  document.body.dataset.mode = mode;
}

/* ---------- folder cards ---------- */
function card(c, i = 0) {
  const review = c.kind === "review";
  const e = el("button", { class: "card" + (review ? " review" : ""), style: `--c:${c.color || "var(--accent)"};--i:${i}`,
      onclick: () => mode === "setup" ? null : openFolder(c),
      onmouseenter: () => mode === "done" && focusCat(c), onmouseleave: () => mode === "done" && focusCat(null) },
    el("div", { class: "ch" }, el("span", { class: "em" }, c.emoji || "📁"), el("span", { class: "name" }, c.label), el("span", { class: "mx-count" }, "0")),
    el("div", { class: "grid" }, Array.from({ length: review ? 6 : 12 }, () => el("div", { class: "slot" }))));
  Object.assign(c, { el: e, badge: e.querySelector(".mx-count"), slots: [...e.querySelectorAll(".slot")], queued: 0, landed: [] });
  return e;
}
function buildCards() {
  $("photos").replaceChildren(...cats.filter(c => c.kind === "photo").map((c, i) => card(c, i)));
  const vids = cats.filter(c => c.kind === "video");
  $("videos").replaceChildren(...vids.map((c, i) => card(c, i)), el("div", { class: "sub-h" }, "Review"),
    ...["_dupes", "_private", "_junk", "_unsure"].map((k, i) => card(catBy[k], vids.length + i)));
  Object.assign(stats, { photos: 0, videos: 0, dupes: 0, saved: 0 });
  released = landed = 0;
  flown.clear();
}
const targetOf = it => it.dupe ? catBy._dupes : it.review ? catBy[REVIEWS[it.review]] : (catBy[it.cat] || catBy._unsure);
const inFolder = (c, i) => c.key === "_dupes" ? i.dupe : c.key.startsWith("_") ? !i.dupe && REVIEWS[i.review] === c.key : !i.dupe && !i.review && i.cat === c.key;

/* ---------- sphere ---------- */
let rot = 0;
function buildSphere(srcs) {  // srcs: [{img element factory}] , at most 320 tiles
  $("sphere").replaceChildren();
  tiles = [];
  const T = Math.min(srcs.length, 320), golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < T; i++) {
    const y = 1 - (i / Math.max(1, T - 1)) * 2, r = Math.sqrt(1 - y * y), th = golden * i;
    const img = srcs[i]();
    $("sphere").append(img);
    tiles.push({ el: img, x: Math.cos(th) * r, y, z: Math.sin(th) * r, left: 0, sx: 0, sy: 0, s: 1, alive: true });
  }
}
function sphereFromItems() {
  order = shuffle(items.map((_, i) => i));
  buildSphere(order.map(i => () => miniImg(items[i])));
  order.forEach((idx, k) => { if (tiles.length) { tiles[k % tiles.length].left++; items[idx].tile = tiles[k % tiles.length]; } });
}
function geom() {
  const r = $("stage").getBoundingClientRect();
  const lift = mode === "running" ? 0.42 : 0.5;
  return { cx: r.left + r.width / 2, cy: r.top + r.height * lift, R: Math.min(r.width, r.height) * (mode === "running" ? 0.32 : 0.36) };
}
function drawSphere(dt) {
  if (!tiles.length) return;
  rot += dt * 0.00035;
  const tilt = Math.sin(performance.now() / 4000) * 0.35;
  const { cx, cy, R } = geom();
  const ca = Math.cos(rot), sa = Math.sin(rot), cb = Math.cos(tilt), sb = Math.sin(tilt);
  for (const t of tiles) {
    if (!t.alive) continue;
    const x = t.x * ca + t.z * sa; let z = -t.x * sa + t.z * ca;
    const y = t.y * cb - z * sb; z = t.y * sb + z * cb;
    const depth = (z + 1) / 2;
    t.s = 0.45 + depth * 0.75; t.sx = cx + x * R; t.sy = cy + y * R;
    t.el.style.transform = `translate3d(${(t.sx - 14).toFixed(1)}px,${(t.sy - 14).toFixed(1)}px,0) scale(${t.s.toFixed(3)})`;
    t.el.style.opacity = (0.2 + depth * 0.8).toFixed(2);
    t.el.style.zIndex = Math.round(depth * 100);
  }
}

/* ---------- flying into folders ---------- */
function release(it) {
  if (flown.has(it.id)) return;
  flown.add(it.id);
  released++;
  const c = targetOf(it);
  const to = c.slots[c.queued++ % c.slots.length].getBoundingClientRect();
  const t = it.tile || { sx: geom().cx, sy: geom().cy, s: 1, left: 1, el: null };
  const s = 28 * (t.s || 1), img = miniImg(it);
  img.style.width = img.style.height = s + "px";
  $("fly").append(img);
  if (t.el && --t.left <= 0) { t.alive = false; t.el.style.opacity = 0; }
  const mx = (t.sx + to.left) / 2 + (Math.random() - .5) * 120, my = (t.sy + to.top) / 2 - 60 - Math.random() * 80;
  const a = img.animate([
    { transform: `translate3d(${t.sx - s / 2}px,${t.sy - s / 2}px,0) scale(1)` },
    { transform: `translate3d(${mx - s / 2}px,${my - s / 2}px,0) scale(1.2) rotate(${(Math.random() - .5) * 50}deg)`, offset: .45 },
    { transform: `translate3d(${to.left}px,${to.top}px,0) scale(${to.width / s})` },
  ], { duration: 650 + Math.random() * 400, easing: "cubic-bezier(.55,0,.25,1)" });
  a.onfinish = () => { img.remove(); land(it, c, true); };
}
function land(it, c, live) {
  c.landed.push(it);
  if (live) {
    const recent = c.landed.slice(-c.slots.length).reverse();
    c.slots.forEach((s, i) => { const w = recent[i]; if (w && s.dataset.id !== String(w.id)) { s.dataset.id = w.id; s.replaceChildren(miniImg(w)); } });
    c.badge.classList.remove("pop"); void c.badge.offsetWidth; c.badge.classList.add("pop");
    c.el.classList.add("hit"); clearTimeout(c.hitT); c.hitT = setTimeout(() => c.el.classList.remove("hit"), 260);
  }
  c.badge.textContent = fmt(c.landed.length); c.badge.classList.add("on");
  if (it.dupe) { stats.dupes++; stats.saved += it.bytes; } else if (it.kind === "video") stats.videos++; else stats.photos++;
  landed++;
  if (live && run === "replay" && landed === items.length) celebrate();
  if (live && run === "live" && finishing && landed >= items.length) celebrate();
}
function fillStatic() {  // results without animation
  buildCards();
  tiles.forEach(t => { t.alive = false; t.el.style.opacity = 0; });
  items.forEach(it => { flown.add(it.id); released++; land(it, targetOf(it), false); });
  cats.concat(catBy._dupes, catBy._private, catBy._junk, catBy._unsure).forEach(c => {
    const recent = c.landed.slice(-c.slots.length).reverse();
    c.slots.forEach((s, i) => s.replaceChildren(...(recent[i] ? [miniImg(recent[i])] : [])));
  });
}
function showDone(celebrateNow) {
  document.body.classList.add("is-done");
  $("bigF").textContent = `${cats.length} folders`;
  $("chipD").textContent = `🗂️ ${fmt(stats.dupes)} duplicates`;
  $("chipS").textContent = `💾 ${size(stats.saved)} to free`;
  if (celebrateNow) { countUp($("bigN"), items.length, 900); confetti(); } else $("bigN").textContent = fmt(items.length);
  $("bigL").textContent = "sorted";
  renderDonut();
  setPill("live", "Sorted");
  setHeader();
}
const SVGNS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs) => { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
function renderDonut() {
  const all = cats.concat(catBy._dupes, catBy._private, catBy._junk, catBy._unsure);
  const groups = all.map(c => ({ c, n: (c.landed || []).length })).filter(g => g.n);
  const total = groups.reduce((s, g) => s + g.n, 0) || 1, R = 48, C = 2 * Math.PI * R;
  const d = $("donut");
  d.replaceChildren(svgEl("circle", { class: "track", cx: 60, cy: 60, r: R }));
  let off = 0;
  groups.forEach((g, i) => {
    const len = g.n / total * C, gap = groups.length > 1 ? Math.min(1.6, len * .3) : 0;
    const seg = svgEl("circle", { class: "seg", cx: 60, cy: 60, r: R, stroke: g.c.color, "stroke-dasharray": `${Math.max(.1, len - gap)} ${C}`,
      style: `--off:${-off}px;--i:${i}`, tabindex: 0, "aria-label": `${g.c.label}: ${g.n}` });
    seg.addEventListener("mouseenter", () => focusCat(g.c));
    seg.addEventListener("mouseleave", () => focusCat(null));
    seg.addEventListener("click", () => openFolder(g.c));
    g.c.seg = seg;
    d.append(seg);
    off += len;
  });
  $("legend").replaceChildren(...groups.slice().sort((a, b) => b.n - a.n).slice(0, 8).map(g => {
    const b = el("button", { style: `--c:${g.c.color}`, onclick: () => openFolder(g.c), onmouseenter: () => focusCat(g.c), onmouseleave: () => focusCat(null) },
      el("i"), g.c.label, el("b", {}, fmt(g.n)));
    g.c.leg = b;
    return b;
  }));
}
function focusCat(c) {
  const all = cats.concat(catBy._dupes, catBy._private, catBy._junk, catBy._unsure);
  $("donut").classList.toggle("focus", !!(c && c.seg));
  all.forEach(x => {
    if (x.seg) x.seg.classList.toggle("on", x === c);
    if (x.leg) x.leg.classList.toggle("on", x === c);
    if (x.el) x.el.classList.toggle("glow", x === c);
  });
  if (!document.body.classList.contains("is-done")) return;
  $("bigN").textContent = fmt(c ? (c.landed || []).length : items.length);
  $("bigL").textContent = c ? c.label : "sorted";
}
function celebrate() {
  const wasLive = run === "live";
  run = "idle"; finishing = false; mode = "done"; setHeader(); renderPanel();
  if (wasLive) fillStatic();  // review folders and hand moves are only known at the end
  showDone(true);
}

/* ---------- replay (after sorting, for recording) ---------- */
function replay() {
  document.body.classList.remove("is-done");
  buildCards(); sphereFromItems();
  run = "replay"; t0 = performance.now(); released = 0;
  setPill("busy", "Claude is looking at every photo & video");
}

/* ---------- KPIs and the frame loop ---------- */
const ease = x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
function updateStats() {
  const scanning = mode === "running" && S.job && S.job.phase === "scan";
  $("k-checked").textContent = fmt(scanning ? S.job.done : Math.max(released, mode === "running" ? S.files || 0 : 0));
  $("k-photos").textContent = fmt(stats.photos);
  $("k-videos").textContent = fmt(stats.videos);
  $("k-folders").textContent = cats.filter(c => c.landed && c.landed.length).length;
  $("k-dupes").textContent = fmt(stats.dupes);
  $("k-saved").textContent = size(stats.saved);
  $("pcount").textContent = fmt(stats.photos);
  $("vcount").textContent = fmt(stats.videos);
  $("bar").style.width = (mode === "running" ? overallProgress() * 100 : items.length ? landed / items.length * 100 : 0) + "%";
}
let last = performance.now();
function tick(now) {
  const dt = now - last; last = now;
  drawSphere(dt);
  if (run === "replay") {
    const want = Math.min(items.length, Math.floor(items.length * ease(Math.min(1, (now - t0) / REPLAY_MS))));
    while (released < want) release(items[order[released]]);
  }
  if (run === "live" && queue.length) {  // labels arrive in batches: spread them out so it flows
    const n = Math.max(1, Math.ceil(queue.length / 45));
    for (let i = 0; i < n && queue.length; i++) release(queue.shift());
  }
  updateStats();
  if (mode === "running") paintTimer();
  requestAnimationFrame(tick);
}
function countUp(e, to, ms) {
  const s = performance.now();
  (function f(n) { const p = Math.min(1, (n - s) / ms); e.textContent = fmt(to * ease(p)); if (p < 1) requestAnimationFrame(f); })(s);
}
function confetti() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const cv = $("confetti"), ctx = cv.getContext("2d"), dpr = devicePixelRatio || 1;
  cv.width = innerWidth * dpr; cv.height = innerHeight * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const css = getComputedStyle(document.documentElement);
  const cols = ["--brand-solid", "--green", "--accent", "--faint", "--ink"].map(v => css.getPropertyValue(v).trim());
  const { cx, cy } = geom(), s = performance.now();
  const ps = Array.from({ length: 200 }, () => ({ x: cx, y: cy - 40, vx: (Math.random() - .5) * 14, vy: -Math.random() * 13 - 3,
    w: 5 + Math.random() * 5, h: 3 + Math.random() * 4, r: Math.random() * 6, vr: (Math.random() - .5) * .3, c: cols[Math.floor(Math.random() * cols.length)] }));
  (function f(n) {
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    const a = Math.max(0, 1 - (n - s) / 3200);
    ps.forEach(p => { p.vy += .32; p.vx *= .985; p.x += p.vx; p.y += p.vy; p.r += p.vr;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r); ctx.globalAlpha = a; ctx.fillStyle = p.c; ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h); ctx.restore(); });
    if (a > 0) requestAnimationFrame(f);
  })(s);
}

/* ---------- time estimate ----------
   Measured on a 2020 MacBook with 1,136 files (10.7 GB): scan 125 s, duplicates 6 s,
   Claude labels about 12 s per 90 files with 4 at a time, building folders 20 s. */
function phaseEstimates(files, bytes, scan = true) {
  const batches = Math.ceil(Math.ceil(files / 30) / 3);
  return {
    scan: scan ? 4 + files * 0.025 + bytes / 1e9 * 9 : 0,
    dupes: 2 + Math.pow(files / 1000, 2) * 4,
    label: 12 + files * 0.012 + Math.ceil(batches / 4) * 14,
    events: 1 + files * 0.001,
    apply: 2 + files * 0.018,
    report: 1 + files * 0.001,
  };
}
const NAMES = { scan: "Looking at every file", dupes: "Finding duplicates", label: "Claude is sorting your photos", events: "Finding trips & events",
  apply: "Building your folders", report: "Writing the clean-up report", highlights: "Making highlights", events_name: "Claude is naming trips",
  google_login: "Waiting for Google sign-in", google_upload: "Uploading to Google Photos", apple_import: "Importing into Apple Photos",
  trash: "Moving duplicates to the Trash" };
function overallProgress() {
  const j = S.job || {}; if (!j.phases || !j.phases.length) return 0;
  const est = runEstimates(), total = j.phases.reduce((s, p) => s + (est[p] || 1), 0) || 1;
  let done = 0;
  for (const p of j.phases) {
    if (p === j.phase) { done += (est[p] || 1) * (j.total ? j.done / j.total : 0); break; }
    done += est[p] || 1;
  }
  return j.phase === "done" ? 1 : Math.min(1, done / total);
}
let runInfo = { files: 0, bytes: 0 };
function runEstimates() { return phaseEstimates(runInfo.files, runInfo.bytes, (S.job.phases || []).includes("scan")); }
function remaining() {
  const j = S.job, est = runEstimates();
  let left = 0, seen = false;
  for (const p of j.phases) {
    if (p === j.phase) {
      seen = true;
      const spent = (j.now - j.phase_started), frac = j.total ? j.done / j.total : 0;
      const guess = frac > 0.15 ? spent / frac - spent : est[p] - spent;
      left += Math.max(2, guess);
    } else if (seen) left += est[p] || 1;
  }
  return left;
}

/* ---------- the center panel: setup, running, done ---------- */
function renderPanel() {
  const panel = $("panel");
  panel.className = "panel is-" + mode;
  if (mode === "setup") return panel.replaceChildren(setupCard());
  if (mode === "running") return panel.replaceChildren(runCard());
  panel.replaceChildren();
}

function setupCard() {
  const box = el("div", { class: "setup mx-rise" });
  const mac = S.platform === "darwin";
  const pathBox = (key, placeholder) => {
    const input = el("input", { class: "field", placeholder, value: pick[key] || "" });
    const use = el("button", { class: "mx-btn small solid", onclick: () => choose(key, input.value.trim()) }, "Use");
    input.onkeydown = e => { if (e.key === "Enter") use.click(); };
    setTimeout(() => input.focus(), 30);
    return el("div", { class: "typed" }, input, use);
  };
  const typeLink = key => el("button", { class: "linkish", onclick: () => { pick.typing = key; renderPanel(); } }, "or type a path");

  // 1. photos
  if (!pick.source) {
    box.append(el("div", { class: "q" }, el("span", { class: "n" }, "1"), el("div", {},
      el("h2", {}, "Choose your photos"),
      el("p", {}, "A Google Photos or Apple Photos export, or any folder with photos and videos. Nothing in it gets moved or deleted."))));
    if (mac && pick.typing !== "source") box.append(el("div", { class: "acts" },
      el("button", { class: "mx-btn solid big-btn", onclick: () => pickFolder("source") }, icon("folder"), "Choose folder"), typeLink("source")));
    else box.append(pathBox("source", "/Users/you/Pictures/Camera roll"));
    if (S.source && S.source !== pick.source) box.append(el("button", { class: "linkish recent", onclick: () => choose("source", S.source) }, `Last time: ${tilde(S.source)}`));
    return box;
  }
  const pk = pick.peek;
  box.append(el("div", { class: "q done" }, el("span", { class: "n" }, icon("check")), el("div", {},
    el("h3", {}, "Photos"), el("div", { class: "picked", title: pick.source }, icon("folder"), el("span", {}, tilde(pick.source))),
    pk ? el("p", { class: "meta" }, `${fmt(pk.photos)} photos · ${fmt(pk.videos)} videos · ${size(pk.bytes)}`) : el("p", { class: "meta" }, "Counting…"),
    pk && pk.subfolders && pk.subfolders.length > 1 ? el("label", { class: "check-row acct" },
      el("input", { type: "checkbox", checked: pick.accounts, onchange: e => { pick.accounts = e.target.checked; renderPanel(); } }),
      el("span", {}, el("b", {}, "Each subfolder is a different account"), el("small", {},
        pk.subfolders.slice(0, 6).map(x => x.name).join(", ") + (pk.subfolders.length > 6 ? "…" : "") +
        (pick.accounts ? ". Duplicates across accounts get a delete list per account." : "")))) : null),
    el("button", { class: "linkish", onclick: () => { pick.source = pick.peek = pick.dest = null; pick.typing = null; resetStageForSetup(); renderPanel(); } }, "Change")));

  // 2. where to save
  if (!pick.dest) {
    box.append(el("div", { class: "q" }, el("span", { class: "n" }, "2"), el("div", {},
      el("h2", {}, "Where should the sorted copies go?"),
      el("p", {}, "Your originals stay where they are. On a Mac the copies take no extra space."))));
    const sug = (pk && pk.suggested_dest) || pick.source + " (sorted)";
    if (mac && pick.typing !== "dest") box.append(el("div", { class: "acts col" },
      el("button", { class: "mx-btn solid big-btn", onclick: () => choose("dest", sug) }, icon("check"), "Next to my photos"),
      el("p", { class: "meta mono", title: sug }, tilde(sug)),
      el("div", { class: "row" }, el("button", { class: "mx-btn small", onclick: () => pickFolder("dest") }, icon("folder"), "Choose another folder"), typeLink("dest"))));
    else box.append(pathBox("dest", sug), el("button", { class: "linkish", onclick: () => choose("dest", sug) }, `Use ${tilde(sug)}`));
    return box;
  }
  box.append(el("div", { class: "q done" }, el("span", { class: "n" }, icon("check")), el("div", {},
    el("h3", {}, "Sorted copies go to"), el("div", { class: "picked", title: pick.dest }, icon("folder"), el("span", {}, tilde(pick.dest)))),
    el("button", { class: "linkish", onclick: () => { pick.dest = null; pick.typing = null; renderPanel(); } }, "Change")));

  // 3. start
  const files = pk ? (pick.sample ? Math.min(200, pk.photos + pk.videos) : pk.photos + pk.videos) : 0;
  const bytes = pk ? pk.bytes * (files / Math.max(1, pk.photos + pk.videos)) : 0;
  const est = phaseEstimates(files, bytes, true), total = Object.values(est).reduce((a, b) => a + b, 0);
  box.append(el("div", { class: "start" },
    el("button", { class: "mx-btn solid big-btn wide", onclick: startSorting }, icon("play"), "Start sorting"),
    el("p", { class: "meta" }, icon("clock"), pk ? ` Usually ${roughly(total)} for ${fmt(files)} files` : " Counting files…")));

  // advanced
  box.append(el("button", { class: "adv-toggle", "aria-expanded": pick.advanced, onclick: () => { pick.advanced = !pick.advanced; renderPanel(); } },
    "Advanced", icon("down")));
  if (pick.advanced) box.append(advancedBox(files));
  return box;
}

function advancedBox(files) {
  const chips = kind => cats.filter(c => c.kind === kind).map(c => el("span", { class: "fchip" }, `${c.emoji || "📁"} ${c.label}`,
    el("button", { "aria-label": `Remove ${c.label}`, onclick: () => saveCats(cats.filter(x => x !== c)) }, icon("x"))));
  const adder = kind => {
    const box = el("span", { class: "fchip add" });
    box.append(el("button", { "aria-label": `Add a ${kind} folder`, onclick: () => {
      const name = el("input", { placeholder: "Folder name", "aria-label": "Folder name" });
      const rule = el("input", { placeholder: "What goes in it", "aria-label": "What goes in it" });
      const add = () => {
        const label = name.value.trim(); if (!label) return name.focus();
        let key = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 24) || "folder", i = 2;
        while (catBy[key]) key = key.replace(/-\d+$/, "") + "-" + i++;
        const at = cats.map(c => c.kind).lastIndexOf(kind);  // keep the catch-all folder last
        const next = cats.slice(); next.splice(Math.max(0, at), 0, { key, kind, label, emoji: kind === "photo" ? "📁" : "🎬", rule: rule.value.trim() || label });
        saveCats(next);
      };
      [name, rule].forEach(i => i.onkeydown = e => { if (e.key === "Enter") add(); if (e.key === "Escape") renderPanel(); });
      box.replaceWith(el("span", { class: "newf" }, name, rule, el("button", { class: "mx-btn small solid", onclick: add }, "Add")));
      name.focus();
    } }, icon("plus")));
    return box;
  };
  const lab = (k, title, text, extra) => el("label", { class: "opt" + (pick.labeler === k ? " on" : "") },
    el("input", { type: "radio", name: "labeler", checked: pick.labeler === k, onchange: () => { pick.labeler = k; renderPanel(); } }),
    el("span", {}, el("b", {}, title, extra || ""), el("small", {}, text)));
  return el("div", { class: "adv" },
    el("h4", {}, "Photo folders"), el("div", { class: "fchips" }, chips("photo"), adder("photo")),
    el("h4", {}, "Video folders"), el("div", { class: "fchips" }, chips("video"), adder("video")),
    el("p", { class: "meta" }, "The last folder of each kind catches everything that fits nowhere else."),
    el("h4", {}, "Who looks at the photos"),
    lab("claude", "Claude", "Uses your Claude plan. No key needed."),
    lab("jev", "Jev by TypeSafe ", S.jev_key ? `Fast image model, billed per file: about ${fmt(files * TOKENS_PER_FILE)} tokens.` : "Needs JEV_KEY=your-key in a .env file in this folder.",
      el("span", { class: "paid" }, "PAID")),
    pick.labeler === "claude" ? el("div", { class: "segrow" }, el("span", {}, "Claude model"), seg("model", [["haiku", "Haiku · fastest"], ["sonnet", "Sonnet"], ["opus", "Opus · most careful"]])) : null,
    el("h4", {}, "Folders on disk"),
    el("div", { class: "segrow" }, el("span", {}, "Inside each folder"), seg("layout", [["flat", "Just files"], ["year", "By year"], ["month", "By month"]])),
    toggle("fix_dates", "Fix dates on the copies", "Puts the real date taken back, so they sort right if you upload them again."),
    toggle("albums", "Albums for trips & events", "Extra copies in Albums/. On a Mac they take no space."),
    toggle("second_look", "Second look at unsure photos", "Claude looks again, larger, at the ones it wasn't sure about."),
    el("label", { class: "check-row" }, el("input", { type: "checkbox", checked: pick.sample, onchange: e => { pick.sample = e.target.checked; renderPanel(); } }), "Try 200 random files first"));
}
function seg(key, opts) {
  return el("div", { class: "mx-seg" }, opts.map(([v, t]) => el("button", { "aria-pressed": pick[key] === v, onclick: () => { pick[key] = v; renderPanel(); } }, t)));
}
function toggle(key, title, text) {
  return el("label", { class: "check-row tog" }, el("input", { type: "checkbox", checked: pick[key], onchange: e => { pick[key] = e.target.checked; } }),
    el("span", {}, el("b", {}, title), el("small", {}, text)));
}

async function saveCats(next) {
  try { S = await api("/api/categories", { categories: next.map(({ key, kind, label, emoji, rule }) => ({ key, kind, label, emoji, rule })) }); }
  catch (e) { return; }
  setCats(S.categories); buildCards(); renderPanel();
}

async function pickFolder(key) {
  const prompt = key === "source" ? "Choose the folder with your photos" : "Choose where to save the sorted folders";
  try {
    const r = await api("/api/pick", { prompt });
    if (r.path) await choose(key, r.path);
  } catch (e) {}
}
async function choose(key, path) {
  if (!path) return toast("Pick a folder first.");
  pick[key] = path; pick.typing = null;
  if (key === "source") {
    pick.peek = null; pick.dest = null; renderPanel(); setHeader();
    try { pick.peek = await api("/api/peek", { source: path }); pick.source = pick.peek.source; }
    catch (e) { pick.source = null; renderPanel(); return; }
    pick.accounts = !!pick.peek.accounts_likely;
    if (!pick.peek.photos && !pick.peek.videos) { toast("No photos or videos in that folder."); pick.source = null; }
    else buildSphere(pick.peek.previews.map(u => () => el("img", { src: u, alt: "" })));
  }
  renderPanel(); setHeader();
}

function resetStageForSetup() {
  $("sphere").replaceChildren(); tiles = [];
  $("fly").replaceChildren();
  document.body.classList.remove("is-done");
  run = "idle";
  buildCards();
}

/* Top-bar button: asks for whatever is missing, then starts. After sorting it replays. */
function sortWithClaude() {
  if (mode === "running") return;
  if (mode === "done") return replay();
  if (!pick.source) return S.platform === "darwin" ? pickFolder("source") : (pick.typing = "source", renderPanel());
  if (!pick.dest) return S.platform === "darwin" ? pickFolder("dest") : (pick.typing = "dest", renderPanel());
  startSorting();
}

async function startSorting() {
  if (!pick.source || !pick.dest) return sortWithClaude();
  const files = pick.peek ? pick.peek.photos + pick.peek.videos : 0;
  if (pick.labeler === "jev") {
    if (!S.jev_key) return toast("Add JEV_KEY=your-key to a .env file in this folder to use Jev.");
    if (!await confirmPaid(Math.min(files, pick.sample ? 200 : files))) return;
  }
  if (pick.labeler === "claude" && S.claude_cli === false) return toast("Claude Code isn't installed on this computer. Install it, or pick Jev under Advanced.");
  try {
    S = await api("/api/sort", { source: pick.source, dest: pick.dest, labeler: pick.labeler, limit: pick.sample ? 200 : 0,
      accounts: pick.accounts, model: pick.model, layout: pick.layout, fix_dates: pick.fix_dates, albums: pick.albums, second_look: pick.second_look });
  } catch (e) { return; }
  runInfo = { files: pick.sample ? Math.min(200, files) : files, bytes: pick.peek ? pick.peek.bytes * (pick.sample ? Math.min(1, 200 / Math.max(1, files)) : 1) : 0 };
  beginRunning();
}

/* ---------- running: poll the server and animate as labels arrive ---------- */
let monitor, lastLabelsAt = 0, libraryLoaded = false, dupesMarked = false, finishing = false;
function beginRunning() {
  mode = "running"; run = "live"; libraryLoaded = false; dupesMarked = false; finishing = false;
  queue.length = 0;
  document.body.classList.remove("is-done");
  $("fly").replaceChildren();
  setHeader(); renderPanel(); buildCards();
  clearInterval(monitor);
  monitor = setInterval(pollRun, 900);
  pollRun();
}
async function pollRun() {
  let s;
  try { s = await fetch("/api/state", { cache: "no-store" }).then(r => r.json()); } catch (e) { return; }
  S = s;
  const j = S.job;
  if (!runInfo.files) runInfo = { files: S.files || 0, bytes: S.bytes || 0 };
  setPill("busy", NAMES[j.phase] || "Working");
  // after the scan, swap the preview sphere for the real library
  if (!libraryLoaded && j.phase && j.phase !== "scan") {
    libraryLoaded = true;
    await loadLibrary(false);
    runInfo = { files: items.length, bytes: items.reduce((s, r) => s + r.bytes, 0) };
    buildCards(); sphereFromItems(); setHeader();
  }
  if (libraryLoaded && !dupesMarked && ["label", "apply", "done"].includes(j.phase)) {
    dupesMarked = true;
    const d = await getJSON("dupes.json");
    dupeIds = new Set((d || []).flatMap(g => g.dupes));
    items.forEach(it => it.dupe = dupeIds.has(it.id));
  }
  if (libraryLoaded && ["label", "apply", "done"].includes(j.phase) && performance.now() - lastLabelsAt > 1200) {
    lastLabelsAt = performance.now();
    const live = await fetch("/api/labels", { cache: "no-store" }).then(r => r.json()).catch(() => ({}));
    for (const [id, key] of Object.entries(live)) {
      const it = byId[id];
      if (it && !flown.has(it.id) && !queue.includes(it)) { it.cat = key; queue.push(it); }
    }
  }
  renderPanel();
  if (!j.running) {
    clearInterval(monitor);
    const byIdOld = byId;
    if (j.code !== 0) { setPill(null, "Stopped"); toast("Sorting stopped. See the details in the panel."); return; }
    // final labels (with any hand moves), then let the rest fly in
    await loadLibrary(true);  // final labels, review folders, captions, trips
    queue.length = 0;  // the waiting ones fly with their final folder
    items.forEach(it => { it.tile = (byIdOld[it.id] || {}).tile; if (!flown.has(it.id)) queue.push(it); });
    finishing = true;
    if (landed >= items.length) celebrate();
  }
}
function runCard() {
  const j = S.job || {};
  const failed = !j.running && j.code && j.code !== 0;
  const steps = (j.phases || []).map(p => {
    const idx = j.phases.indexOf(p), cur = j.phases.indexOf(j.phase);
    const state = j.phase === "done" || idx < cur ? "ok" : p === j.phase ? (failed ? "bad" : "now") : "";
    return el("li", { class: state }, state === "ok" ? icon("check") : el("i", {}), { scan: "Scan", dupes: "Duplicates", label: "Label", events: "Trips", apply: "Folders", report: "Report" }[p] || p);
  });
  const pct = j.total ? Math.round(j.done / j.total * 100) : 0;
  return el("div", { class: "run" },
    el("div", { class: "run-h" }, el("b", {}, failed ? "Something went wrong" : NAMES[j.phase] || "Getting ready"),
      el("span", { class: "num", id: "timer" }, "")),
    el("div", { class: "pbar" }, el("i", { style: `width:${failed ? 100 : pct}%` })),
    el("ol", { class: "phases" }, steps),
    failed ? el("pre", { class: "log" }, (j.log || []).slice(-8).join("\n")) : null,
    failed ? el("button", { class: "mx-btn small solid", onclick: startSorting }, "Try again") : null,
    j.running ? el("button", { class: "linkish stop", onclick: () => api("/api/stop", {}).then(() => toast("Stopping… finished batches are kept.")).catch(() => {}) }, "Stop") : null);
}
function paintTimer() {
  const t = $("timer"); if (!t || !S.job || !S.job.started) return;
  const now = Date.now() / 1000;
  const elapsed = S.job.running ? now - S.job.started : S.job.now - S.job.started;
  const left = S.job.running ? remaining() - (now - S.job.now) : 0;
  t.textContent = `${mmss(Math.max(0, elapsed))} · ${S.job.running ? (left > 5 ? roughly(left) + " left" : "almost done") : "done"}`;
}

/* ---------- dialogs: edit folders, browse a folder, view a photo, paid confirm ---------- */
function closeAll() { $("overlay").replaceChildren(); document.removeEventListener("keydown", lbKeys); setNav("tLibrary"); }
function overlay(...nodes) {  // replaces whatever is open, keeps the rail's highlight
  $("overlay").replaceChildren(...nodes);
  document.removeEventListener("keydown", lbKeys);
  paintIcons($("overlay"));
}
addEventListener("keydown", e => { if (e.key === "Escape" && !document.querySelector(".lightbox")) closeAll(); });

function confirmPaid(n) {
  return new Promise(res => {
    const done = v => { closeAll(); res(v); };
    overlay(el("div", { class: "fb-scrim", onclick: e => e.target === e.currentTarget && done(false) },
      el("div", { class: "fb-dialog pc", role: "dialog" },
        el("div", { class: "fb-head" }, el("h2", {}, "Label with Jev"), el("button", { class: "mx-icon", onclick: () => done(false), "aria-label": "Close" }, icon("x"))),
        el("div", { class: "pc-list" }, el("div", { class: "pc-choice" },
          el("div", {}, el("b", {}, `${fmt(n)} files, about ${fmt(n * TOKENS_PER_FILE)} tokens`),
            el("p", {}, "Sends a small 280px preview and the file name of each file to TypeSafe's Jev model, never the original. Check the per-token price on console.typesafe.ai.")),
          el("button", { class: "mx-btn solid", onclick: () => done(true) }, "Spend tokens"))),
        el("p", { class: "pc-note" }, "Already-labelled files are skipped, so you can stop and resume."))));
  });
}

function openFolders() {
  const draft = cats.map(c => ({ ...c }));
  const list = el("div", { class: "folder-list" });
  const slug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 24) || "folder";
  function row(c) {
    const seg = el("div", { class: "mx-seg" }, ["photo", "video"].map(k => el("button", { "aria-pressed": c.kind === k, onclick: () => { c.kind = k; render(); } }, k === "photo" ? "Photos" : "Videos")));
    return el("div", { class: "folder-row" },
      el("input", { class: "emoji", value: c.emoji || "📁", "aria-label": "Emoji", oninput: e => c.emoji = e.target.value }),
      el("input", { value: c.label, placeholder: "Folder name", "aria-label": "Folder name", oninput: e => c.label = e.target.value }),
      el("input", { class: "rule", value: c.rule || "", placeholder: "What goes in here, in plain words", "aria-label": "Rule", oninput: e => c.rule = e.target.value }),
      seg,
      el("button", { class: "mx-icon", "aria-label": `Delete ${c.label}`, onclick: () => { draft.splice(draft.indexOf(c), 1); render(); } }, icon("trash")));
  }
  function render() {
    list.replaceChildren(el("h4", {}, "Photo folders"), ...draft.filter(c => c.kind === "photo").map(row),
      el("h4", {}, "Video folders"), ...draft.filter(c => c.kind === "video").map(row));
    paintIcons(list);
  }
  const add = kind => () => { draft.push({ key: "", kind, label: "", emoji: kind === "photo" ? "📁" : "🎬", rule: "" }); render(); };
  async function saveIt() {
    for (const c of draft) {
      if (!c.label.trim()) return toast("Every folder needs a name.");
      c.label = c.label.trim(); c.rule = (c.rule || "").trim() || c.label;
      if (!c.key) { let k = slug(c.label), i = 2; while (draft.some(d => d !== c && d.key === k)) k = slug(c.label) + "-" + i++; c.key = k; }
    }
    await saveCats(draft);
    closeAll();
    if (mode === "done") toast("Saved. Press New sort and sort again so files can use the new folders.");
  }
  render();
  overlay(el("div", { class: "fb-scrim", onclick: e => e.target === e.currentTarget && closeAll() },
    el("div", { class: "fb-dialog", role: "dialog", "aria-label": "Edit folders" },
      el("div", { class: "fb-head" }, el("h2", {}, "Folders"), el("button", { class: "mx-icon", onclick: closeAll, "aria-label": "Close" }, icon("x"))),
      el("div", { class: "fb-rows" }, list,
        el("p", { class: "note" }, "The rule is what Claude reads, so describe each folder the way you'd explain it to a friend.")),
      el("div", { class: "fb-foot" },
        el("button", { class: "mx-btn", onclick: add("photo") }, icon("plus"), "Photo folder"),
        el("button", { class: "mx-btn", onclick: add("video") }, icon("plus"), "Video folder"),
        el("span", { class: "spacer" }),
        el("button", { class: "mx-btn ghost", onclick: closeAll }, "Cancel"),
        el("button", { class: "mx-btn solid", onclick: saveIt }, "Save folders")))));
}

function openFolder(c) {
  setNav(null);
  browse(`${c.emoji || "📁"} ${c.label}`, () => items.filter(i => !i.trashed && inFolder(c, i)), {
    empty: "Nothing in this folder yet.",
    actions: S.sorted && !DEMO ? [el("button", { class: "mx-btn small", onclick: () => api("/api/open", { folder: c.key }).catch(() => {}) }, icon("folder"), "Open in Finder")] : [] });
}
let lbKeys = () => {};
function lightbox(list, i, opts = {}) {
  const it = list[i];
  if (!it) return;
  const go = j => j >= 0 && j < list.length && lightbox(list, j, opts);
  const full = DEMO ? it.src : `/api/file/${it.id}`;
  const media = el("div", { class: "media" });
  const node = it.kind === "video" && !DEMO ? el("video", { src: full, controls: true, autoplay: true, playsinline: true, poster: it.src })
    : el("img", { src: full, alt: it.name, draggable: "false" });
  media.append(node);
  let z = 1, px = 0, py = 0, drag = null, startX = 0;
  const paint = () => { node.style.transform = z > 1 ? `translate(${px}px,${py}px) scale(${z})` : ""; media.classList.toggle("zoomed", z > 1); };
  if (node.tagName === "IMG") {
    node.addEventListener("dblclick", e => {
      if (z > 1) { z = 1; px = py = 0; }
      else { const r = node.getBoundingClientRect(); z = 2.4; px = (r.left + r.width / 2 - e.clientX) * 1.4; py = (r.top + r.height / 2 - e.clientY) * 1.4; }
      paint();
    });
    media.addEventListener("wheel", e => {
      if (z === 1 && !e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      z = Math.min(6, Math.max(1, z * (e.deltaY < 0 ? 1.15 : 0.87)));
      if (z === 1) px = py = 0;
      paint();
    }, { passive: false });
  }
  media.addEventListener("pointerdown", e => { if (e.target.tagName === "VIDEO") return; drag = [e.clientX, e.clientY, px, py]; startX = e.clientX; });
  media.addEventListener("pointermove", e => { if (!drag || z === 1) return; px = drag[2] + e.clientX - drag[0]; py = drag[3] + e.clientY - drag[1]; paint(); });
  media.addEventListener("pointerup", e => {
    if (drag && z === 1) { const dx = e.clientX - startX; if (dx > 70) go(i - 1); else if (dx < -70) go(i + 1); }
    drag = null;
  });
  const from = Math.max(0, Math.min(i - 7, list.length - 15));
  const film = el("div", { class: "film" }, list.slice(from, from + 15).map((x, k) =>
    el("button", { class: from + k === i ? "on" : "", onclick: () => go(from + k), "aria-label": x.name }, miniImg(x))));
  const where = it.dupe ? "Duplicates" : it.review ? (catBy[REVIEWS[it.review]] || {}).label : (catBy[it.cat] || {}).label;
  const kept = it.group && it.dupe ? byId[it.group.keep] : null;
  const row = (h, v) => v ? [el("h4", {}, h), el("p", {}, v)] : [];
  const info = el("aside", { class: "info" },
    row("Caption", it.caption), row("Folder", where),
    row("Taken", it.taken ? new Date(it.taken * 1000).toLocaleString(undefined, { dateStyle: "full", timeStyle: "short" }) : "Unknown"),
    row("Camera", [it.camera, it.lens].filter(Boolean).join(" · ")),
    row("File", `${it.name} · ${size(it.bytes)}${it.w ? ` · ${it.w}×${it.h}` : ""}${it.duration ? " · " + mmss(it.duration) : ""}`),
    row("Account", it.account), row("Takeout album", it.album), row("Trip or event", it.event && it.event.name),
    row("Duplicate of", kept ? `${kept.name}${kept.account ? " in " + kept.account : ""} (kept: ${it.group.why})` : ""),
    row("Place", it.geo ? `${it.geo[0].toFixed(3)}, ${it.geo[1].toFixed(3)}` : ""));
  let showInfo = pref("info") === "1";
  const infoBtn = el("button", { class: "mx-icon" + (showInfo ? " on" : ""), "aria-label": "Details (i)", onclick: () => toggleInfo() }, icon("info"));
  const toggleInfo = () => { showInfo = !showInfo; setPref("info", showInfo ? "1" : "0"); info.hidden = !showInfo; infoBtn.classList.toggle("on", showInfo); };
  info.hidden = !showInfo;
  const move = DEMO ? null : el("select", { class: "mx-select", "aria-label": "Move to folder", onchange: e => {
    const key = e.target.value;
    moveItems([it], key, () => { if (opts.onChange) opts.onChange(); });
  } }, cats.filter(c => c.kind === it.kind).map(c => el("option", { value: c.key, selected: c.key === it.cat && !it.review && !it.dupe }, `${c.emoji || ""} ${c.label}`)));
  const close = () => { box.remove(); document.removeEventListener("keydown", lbKeys); if (opts.onChange) opts.onChange(); };
  const box = el("div", { class: "lightbox", role: "dialog", "aria-label": it.name },
    el("div", { class: "lbtop" }, el("span", { class: "count" }, `${fmt(i + 1)} of ${fmt(list.length)}`), el("span", { class: "spacer" }), infoBtn,
      DEMO ? null : el("button", { class: "mx-icon", "aria-label": "Show the original in Finder", onclick: () => api("/api/open", { id: it.id }).catch(() => {}) }, icon("reveal")),
      el("button", { class: "mx-icon", "aria-label": "Close", onclick: close }, icon("x"))),
    media, info,
    el("div", { class: "bar" },
      el("div", { class: "lbtext" }, el("b", {}, it.name), it.caption ? el("span", { class: "cap" }, it.caption) : null),
      el("span", { class: "spacer" }), move ? el("small", {}, "Move to") : null, move),
    film);
  media.append(el("button", { class: "nav prev", "aria-label": "Previous", disabled: i === 0, onclick: () => go(i - 1) }, icon("left")),
    el("button", { class: "nav next", "aria-label": "Next", disabled: i === list.length - 1, onclick: () => go(i + 1) }, icon("right")));
  document.querySelector(".lightbox")?.remove();
  document.removeEventListener("keydown", lbKeys);
  lbKeys = e => {
    if (e.target.matches("input, select, textarea")) return;
    if (e.key === "ArrowLeft") go(i - 1);
    if (e.key === "ArrowRight") go(i + 1);
    if (e.key === "i") toggleInfo();
    if (e.key === "Escape") { e.stopPropagation(); close(); }
  };
  document.addEventListener("keydown", lbKeys);
  $("overlay").append(box);
  paintIcons(box);
  film.querySelector(".on")?.scrollIntoView({ inline: "center", block: "nearest" });
}
function shuffle(a) { for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; }

/* ---------- tools after sorting: search, accounts, clean up, trips, map, highlights, upload, privacy ---------- */
let jobWatch = null;
const pref = k => { try { return localStorage.getItem("snapsift." + k); } catch (e) { return null; } };
const setPref = (k, v) => { try { localStorage.setItem("snapsift." + k, v); } catch (e) {} };
const live = () => items.filter(i => !i.trashed);
const dayName = t => new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

function setNav(id) {
  document.querySelectorAll(".rail .nav-i").forEach(b => b.classList.toggle("on", b.id === id));
}
function initTools() {
  const tool = (id, fn, needsDone = true) => $(id).onclick = () => {
    if (needsDone && (mode !== "done" || DEMO)) return toast(DEMO ? "This is the demo. Run ./start.sh to use it on your photos." : "Sort a folder first, then this opens.");
    setNav(id); fn();
  };
  tool("tLibrary", () => { closeAll(); $("app").scrollTo({ top: 0, behavior: "smooth" }); }, false);
  tool("tSearch", () => palette(), false);
  tool("tAccounts", accountsDialog); tool("tClean", () => cleanupDialog()); tool("tTrips", eventsDialog); tool("tMap", mapDialog);
  tool("tHigh", highlightsDialog); tool("tShare", shareDialog); tool("tPrivacy", privacyDialog, false);
  $("q").onclick = () => palette();
  $("btnReplay").onclick = () => replay();
  $("chipD").onclick = () => mode === "done" && !DEMO ? cleanupDialog("dupes") : null;
  $("chipS").onclick = () => mode === "done" && !DEMO ? cleanupDialog("dupes") : null;
  $("jobstop").innerHTML = svg("stop");
  $("jobstop").onclick = () => api("/api/stop", {}).then(() => toast("Stopping…")).catch(() => {});
  if (!/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)) $("q").querySelector("kbd").textContent = "Ctrl K";
  paintIcons();
  addEventListener("keydown", e => {
    const typing = e.target.matches("input, textarea, select");
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); palette(); return; }
    if (typing || document.querySelector(".lightbox")) return;
    if (e.key === "/" && !$("overlay").children.length) { e.preventDefault(); palette(); }
    if (e.key === "?" && !$("overlay").children.length) { e.preventDefault(); shortcutsDialog(); }
  });
}

/* ---------- command palette (⌘K) ---------- */
function fuzzy(text, q) {
  text = text.toLowerCase();
  const i = text.indexOf(q);
  if (i >= 0) return 100 - i;
  let t = 0;
  for (const ch of q) { t = text.indexOf(ch, t); if (t < 0) return -1; t++; }
  return 10;
}
function palette(initial = "") {
  const input = el("input", { placeholder: "Search photos, folders, trips and tools…", value: initial, "aria-label": "Search", autocomplete: "off", spellcheck: "false" });
  const listEl = el("div", { class: "plist", role: "listbox" });
  let sel = 0, runs = [];
  const done = mode === "done" && !DEMO;
  const actions = [
    ["Clean up duplicates, junk and private photos", "broom", () => cleanupDialog(), done],
    ["Accounts and delete lists", "users", accountsDialog, done && S.accounts && S.accounts.length > 1],
    ["Trips & events", "compass", eventsDialog, done], ["Map", "map", mapDialog, done], ["Highlights", "film", highlightsDialog, done],
    ["Upload to Google Photos or Apple Photos", "upload", shareDialog, done], ["Privacy", "lock", privacyDialog, true],
    ["Edit folders", "pencil", openFolders, true], ["New sort", "plus", newSort, mode === "done"],
    ["Open the sorted folder in Finder", "folder", () => api("/api/open", {}).catch(() => {}), done],
    ["Replay the sorting animation", "play", replay, mode === "done"], ["Switch light / dark", "moon", toggleTheme, true],
    ["Keyboard shortcuts", "keyboard", shortcutsDialog, true],
  ].filter(a => a[3]);
  const render = () => {
    const q = input.value.trim().toLowerCase();
    const out = [];
    runs = [];
    const item = (ic, label, sub, run) => {
      const k = runs.length;
      runs.push(run);
      const b = el("button", { class: "it", role: "option", onclick: () => run(), onmousemove: () => { if (sel !== k) { sel = k; mark(); } } },
        el("span", { class: "ic" }, typeof ic === "string" && ICONS[ic] ? icon(ic) : ic), el("span", {}, label), sub ? el("small", {}, sub) : null);
      out.push(b);
    };
    if (q.length >= 2 && mode === "done") {
      const words = q.split(/\s+/);
      const hits = live().filter(it => words.every(w => haystack(it).includes(w)));
      if (hits.length) {
        out.push(el("div", { class: "grp" }, `Photos · ${fmt(hits.length)}`));
        out.push(el("div", { class: "thumbs" }, hits.slice(0, 16).map((it, k) =>
          el("button", { "aria-label": it.name, title: it.caption || it.name, onclick: () => { closeAll(); lightbox(hits, k); } }, el("img", { src: it.src, alt: "", loading: "lazy" })))));
        item("search", `Show all ${fmt(hits.length)} results for “${q}”`, "↵", () => searchFor(q));
      }
    }
    const folders = mode === "done" ? cats.concat(catBy._dupes, catBy._private, catBy._junk, catBy._unsure)
      .map(c => ({ c, s: q ? fuzzy(c.label, q) : 1 })).filter(x => x.s >= 0 && (x.c.landed || []).length).sort((a, b) => b.s - a.s).slice(0, q ? 6 : 4) : [];
    if (folders.length) {
      out.push(el("div", { class: "grp" }, "Folders"));
      folders.forEach(({ c }) => item(c.emoji || "📁", c.label, fmt((c.landed || []).length), () => openFolder(c)));
    }
    const evs = mode === "done" ? events.map(e => ({ e, s: q ? fuzzy(e.name, q) : -1 })).filter(x => x.s >= 0).slice(0, 5) : [];
    if (evs.length) {
      out.push(el("div", { class: "grp" }, "Trips & events"));
      evs.forEach(({ e }) => item(e.kind === "trip" ? "🧭" : "🎉", e.name, fmt(e.ids.length), () => browse(e.name, e.ids.map(i => byId[i]).filter(Boolean))));
    }
    const acts = actions.map(a => ({ a, s: q ? fuzzy(a[0], q) : 1 })).filter(x => x.s >= 0).sort((a, b) => b.s - a.s);
    if (acts.length) {
      out.push(el("div", { class: "grp" }, "Actions"));
      acts.forEach(({ a }) => item(a[1], a[0], null, () => { closeAll(); a[2](); }));
    }
    if (!out.length) out.push(el("div", { class: "empty" }, mode === "done" ? "Nothing matches." : "Sort a folder first to search your photos."));
    listEl.replaceChildren(...out);
    paintIcons(listEl);
    sel = Math.min(sel, Math.max(0, runs.length - 1));
    mark();
  };
  const mark = () => {
    const its = listEl.querySelectorAll(".it");
    its.forEach((b, k) => b.classList.toggle("on", k === sel));
    its[sel]?.scrollIntoView({ block: "nearest" });
  };
  input.oninput = () => { sel = 0; render(); };
  input.onkeydown = e => {
    if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(runs.length - 1, sel + 1); mark(); }
    if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(0, sel - 1); mark(); }
    if (e.key === "Enter" && runs[sel]) { e.preventDefault(); runs[sel](); }
  };
  setNav("tSearch");
  overlay(el("div", { class: "fb-scrim", onclick: e => e.target === e.currentTarget && closeAll() },
    el("div", { class: "palette", role: "dialog", "aria-label": "Search" },
      el("div", { class: "pin" }, icon("search"), input, el("kbd", {}, "esc")), listEl,
      el("div", { class: "pfoot" }, el("span", {}, "↑↓ move"), el("span", {}, "↵ open"), el("span", {}, "esc close"), el("span", {}, "? shortcuts")))));
  render();
  input.focus();
}

function shortcutsDialog() {
  const k = (keys, what) => [el("span", {}, ...keys.map(x => el("kbd", {}, x))), el("span", {}, what)];
  const mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  dialog("Keyboard shortcuts", [el("div", { class: "keys" },
    k([mac ? "⌘" : "Ctrl", "K"], "Search photos, folders and tools"), k(["/"], "Search too"), k(["?"], "This list"),
    k(["←", "→"], "Previous / next photo"), k(["i"], "Photo details"), k(["Double-click"], "Zoom in on a photo; drag to look around"),
    k(["Shift", "click"], "Select a range of photos"), k([mac ? "⌘" : "Ctrl", "A"], "Select everything in a folder"),
    k(["Space"], "Replay the animation"), k(["Esc"], "Close"))]);
}
function dialog(title, body, foot, cls = "") {
  overlay(el("div", { class: "fb-scrim", onclick: e => e.target === e.currentTarget && closeAll() },
    el("div", { class: "fb-dialog " + cls, role: "dialog", "aria-label": typeof title === "string" ? title : "" },
      el("div", { class: "fb-head" }, el("h2", {}, title), el("button", { class: "mx-icon", onclick: closeAll, "aria-label": "Close" }, icon("x"))),
      el("div", { class: "fb-rows dlg" }, body),
      foot ? el("div", { class: "fb-foot" }, foot) : null)));
}

function confirmBox(title, lines, ok, danger) {
  return new Promise(res => {
    const done = v => { closeAll(); res(v); };
    dialog(title, [...lines.map(l => typeof l === "string" ? el("p", { class: "para" }, l) : l)],
      [el("span", { class: "spacer" }), el("button", { class: "mx-btn ghost", onclick: () => done(false) }, "Cancel"),
       el("button", { class: "mx-btn solid" + (danger ? " danger" : ""), onclick: () => done(true) }, ok)], "pc");
  });
}

/* a grid of photos, like a folder */
function browse(title, source, opts = {}) {
  const get = typeof source === "function" ? source : () => source;
  let list = get(), shown = 120, last = -1;
  const sel = new Set();
  const grid = el("div", { class: "browse" });
  const count = el("b");
  const mover = el("select", { class: "mx-select", "aria-label": "Move the selected files to" });
  const bar = el("div", { class: "selbar", role: "region", "aria-label": "Selection" }, count, mover,
    el("button", { class: "mx-btn small", onclick: () => { list.forEach(x => sel.add(x.id)); paintSel(); } }, "Select all"),
    el("button", { class: "mx-btn small", onclick: () => { sel.clear(); paintSel(); } }, "Clear"));
  mover.onchange = () => {
    const key = mover.value;
    if (!key) return;
    const its = [...sel].map(id => byId[id]).filter(x => x && catBy[key] && catBy[key].kind === x.kind);
    sel.clear();
    moveItems(its, key, refresh);
    refresh();
  };
  function refresh() { list = get(); render(); paintSel(); }
  function paintSel() {
    grid.classList.toggle("selecting", sel.size > 0);
    bar.classList.toggle("on", sel.size > 0);
    count.textContent = `${fmt(sel.size)} selected`;
    grid.querySelectorAll(".tile").forEach(t => t.classList.toggle("sel", sel.has(+t.dataset.id)));
    const kinds = new Set([...sel].map(id => (byId[id] || {}).kind));
    mover.replaceChildren(el("option", { value: "" }, "Move to…"),
      ...cats.filter(c => kinds.has(c.kind)).map(c => el("option", { value: c.key }, `${c.emoji || ""} ${c.label}`)));
  }
  function toggle(idx, range) {
    const ids = range && last >= 0 ? list.slice(Math.min(last, idx), Math.max(last, idx) + 1).map(x => x.id) : [list[idx].id];
    const on = !sel.has(list[idx].id);
    ids.forEach(id => on ? sel.add(id) : sel.delete(id));
    last = idx;
    paintSel();
  }
  function render() {
    grid.replaceChildren(...list.slice(0, shown).map((it, k) => el("button", { class: "tile", "data-id": it.id, style: `--i:${k}`, "aria-label": it.name, title: it.caption || it.name,
      onclick: e => {
        if (!DEMO && (e.target.closest(".pick") || sel.size || e.shiftKey || e.metaKey || e.ctrlKey)) return toggle(k, e.shiftKey);
        lightbox(list, k, { onChange: refresh });
      } },
      DEMO ? null : el("span", { class: "pick", "aria-hidden": "true" }, icon("check")),
      el("img", { src: it.src, alt: "", loading: "lazy" }),
      it.kind === "video" ? el("span", { class: "vid" }, "▶ " + (it.duration ? mmss(it.duration) : "video")) : null,
      opts.badge ? el("span", { class: "badge" }, opts.badge(it)) : null)));
    if (shown < list.length) grid.append(el("button", { class: "mx-btn more", onclick: () => { shown += 240; render(); paintSel(); } }, `Show ${fmt(Math.min(240, list.length - shown))} more`));
    paintIcons(grid);
    head.querySelector(".mx-count").textContent = fmt(list.length);
    empty.hidden = list.length > 0;
  }
  const head = el("div", { class: "fb-head" }, el("h2", {}, title, el("span", { class: "mx-count" }, fmt(list.length))),
    el("div", { class: "acts" }, ...(opts.actions || []), el("button", { class: "mx-icon", onclick: closeAll, "aria-label": "Close" }, icon("x"))));
  const empty = el("p", { class: "mx-empty", style: "padding:22px" }, opts.empty || "Nothing here.");
  const dlg = el("div", { class: "fb-dialog wide", role: "dialog", "aria-label": String(title) }, head,
    opts.note ? el("p", { class: "browse-note" }, opts.note) : null, empty, grid, bar);
  dlg.addEventListener("keydown", e => {
    if ((e.metaKey || e.ctrlKey) && e.key === "a" && !e.target.matches("input, select")) { e.preventDefault(); list.forEach(x => sel.add(x.id)); paintSel(); }
    if (e.key === "Escape" && sel.size) { e.stopPropagation(); sel.clear(); paintSel(); }
  });
  overlay(el("div", { class: "fb-scrim", onclick: e => e.target === e.currentTarget && closeAll() }, dlg));
  render();
  paintSel();
  dlg.tabIndex = -1;
  dlg.focus();
}

/* move one or many files, with Undo */
async function moveItems(its, key, after) {
  if (!its.length) return;
  const before = its.map(it => ({ it, cat: it.cat, review: it.review, dupe: it.dupe }));
  let ok = 0;
  for (const it of its) {
    try { await api("/api/move", { id: it.id, key }); } catch (e) { continue; }
    it.cat = key; it.review = null; it.dupe = false; dupeIds.delete(it.id); it._hay = null; ok++;
  }
  fillStatic(); showDone(false);
  if (after) after();
  if (!ok) return;
  toast(`Moved ${ok === 1 ? its[0].name : fmt(ok) + " files"} to ${catBy[key].label}. It moves on disk next time you sort.`, "Undo", async () => {
    for (const b of before) {
      try { await api("/api/unmove", { id: b.it.id }); } catch (e) { continue; }
      Object.assign(b.it, { cat: b.cat, review: b.review, dupe: b.dupe, _hay: null });
      if (b.dupe) dupeIds.add(b.it.id);
    }
    fillStatic(); showDone(false);
    if (after) after();
    toast("Undone.");
  });
}
/* ---------- background jobs: a small progress pill ---------- */
function watchJob(label, onDone) {
  $("jobpill").hidden = false;
  $("jobtext").textContent = label;
  $("jobbar").style.width = "0%";
  clearInterval(jobWatch);
  jobWatch = setInterval(async () => {
    let s;
    try { s = await fetch("/api/state", { cache: "no-store" }).then(r => r.json()); } catch (e) { return; }
    S = s;
    const j = s.job, pct = j.total ? j.done / j.total : 0;
    $("jobtext").textContent = (NAMES[j.phase] || label) + (j.total ? ` · ${Math.round(pct * 100)}%` : "");
    $("jobbar").style.width = pct * 100 + "%";
    if (j.running) return;
    clearInterval(jobWatch);
    $("jobpill").hidden = true;
    if (j.code === 0) { await refreshLibrary(); if (onDone) onDone(s); }
    else toast((j.log || []).filter(l => l && !l.startsWith("$")).slice(-1)[0] || "That didn't work.");
  }, 1000);
}
async function refreshLibrary() {
  try { S = await api("/api/state"); } catch (e) { return; }
  setCats(S.categories);
  await loadLibrary(true);
  fillStatic(); showDone(false); setHeader();
}
function runJob(step, args, label, onDone) {
  return api("/api/run", { step, ...args }).then(() => { closeAll(); watchJob(label, onDone); }).catch(() => {});
}

/* ---------- search ---------- */
function haystack(it) {
  if (!it._hay) {
    const d = it.taken ? new Date(it.taken * 1000) : null;
    it._hay = [it.name, it.caption, (catBy[it.cat] || {}).label, it.account, it.album, it.event && it.event.name, it.event && it.event.auto_name,
      it.review === "private" ? "private" : it.review, it.dupe ? "duplicate" : "", it.kind, it.camera,
      d ? d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" }) + " " + d.toISOString().slice(0, 7) : "undated"]
      .filter(Boolean).join(" ").toLowerCase();
  }
  return it._hay;
}
function searchFor(q) {
  q = q.trim().toLowerCase();
  if (!q) return;
  const words = q.split(/\s+/);
  setNav("tSearch");
  browse(`“${q}”`, () => live().filter(it => words.every(w => haystack(it).includes(w))), {
    empty: "Nothing matches. Try fewer words, a year like 2023, a month, or a folder name.",
    note: !items.some(i => i.caption) ? "Searching names, folders and dates. Sort again to add Claude's captions." : null });
}
/* ---------- accounts ---------- */
function accountsDialog() {
  const accts = (report && report.accounts) || [];
  if (accts.length < 2) return toast("Only one account here. Choose a folder with one subfolder per account and tick “different account” to compare.");
  const main = S.main_account;
  const kept = it => (byId[it.group.keep] || {}).account;
  const rows = accts.map(a => el("tr", {},
    el("td", {}, el("label", { class: "radio" }, el("input", { type: "radio", name: "main", checked: main === a.name, onchange: () => setMain(a.name) }), el("b", {}, a.name))),
    el("td", { class: "num" }, fmt(a.files)), el("td", { class: "num" }, size(a.bytes)),
    el("td", { class: "num" }, a.elsewhere ? `${fmt(a.elsewhere)} · ${size(a.elsewhere_bytes)}` : "—"),
    el("td", {}, a.dupes ? el("button", { class: "mx-btn small", onclick: () => {
      const list = live().filter(i => i.dupe && i.account === a.name && i.group);
      browse(`Delete from ${a.name}`, list, { badge: i => "kept in " + (kept(i) || "?"),
        note: `Each of these is also kept elsewhere. In photos.google.com, signed in to ${a.name}, search each file name and delete it. The full list with dates is in _Review/Delete lists.`,
        actions: [el("button", { class: "mx-btn small", onclick: () => api("/api/open", { folder: "_delete" }).catch(() => {}) }, icon("folder"), "Delete lists")] });
    } }, "Show") : null)));
  dialog("Accounts", [
    el("p", { class: "para" }, main ? `Copies in ${main} are always kept. The other accounts' copies of the same photo are listed to delete.`
      : "Pick your main account: its copy of a photo is always the one kept, and the other accounts get a list of copies to delete."),
    el("table", { class: "tbl" }, el("thead", {}, el("tr", {}, el("th", {}, "Main account"), el("th", {}, "Files"), el("th", {}, "Size"),
      el("th", {}, "Also kept elsewhere"), el("th", {}))), el("tbody", {}, rows)),
    el("p", { class: "meta" }, `Deleting the “also kept elsewhere” copies frees ${size(accts.reduce((s, a) => s + a.elsewhere_bytes, 0))} across your accounts. Google doesn't let apps delete photos, so you delete them in Google Photos; Trash there keeps them 60 days.`),
  ], [el("button", { class: "mx-btn", onclick: () => api("/api/open", { folder: "_delete" }).catch(() => {}) }, icon("folder"), "Open delete lists"),
      el("span", { class: "spacer" }), el("button", { class: "mx-btn solid", onclick: closeAll }, "Done")]);
}
async function setMain(name) {
  try { await api("/api/main_account", { account: name }); } catch (e) { return; }
  closeAll();
  watchJob(`Making ${name} the main account`, () => { toast(`${name} is the main account now.`); accountsDialog(); });
}

/* ---------- clean up ---------- */
function cleanupDialog(tab) {
  const L = live();
  const dupes = L.filter(i => i.dupe), junk = L.filter(i => i.review === "junk"), priv = L.filter(i => i.review === "private"),
    unsure = L.filter(i => i.review === "unsure"), vids = L.filter(i => i.kind === "video").sort((a, b) => b.bytes - a.bytes).slice(0, 40);
  const tiles = [["dupes", "🗂️", "Duplicates", dupes.length, size(dupes.reduce((s, i) => s + i.bytes, 0))],
    ["junk", "🗑️", "Junk", junk.length, "blurry, dark, accidental"], ["private", "🔒", "Private", priv.length, "IDs, cards, passwords"],
    ["unsure", "🤔", "Not sure", unsure.length, "pick a folder"], ["videos", "🎬", "Biggest videos", vids.length, size(vids.reduce((s, i) => s + i.bytes, 0))]];
  tab = typeof tab === "string" ? tab : "dupes";
  const body = el("div", { class: "clean-body" });
  const show = t => {
    tab = t;
    head.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", b.dataset.t === t));
    const open = (title, list, note) => () => browse(title, list, { note });
    const parts = {
      dupes: () => [el("p", { class: "para" }, "Extra copies of photos you also have elsewhere. The copy kept is the one in your main account, then the sharpest and largest."),
        el("div", { class: "row" }, el("button", { class: "mx-btn", onclick: open("Duplicates", dupes, "Each tile is an extra copy; open one to see which file was kept.") }, "Look at them"),
          S.platform === "darwin" ? el("button", { class: "mx-btn", onclick: trashFlow }, icon("trash"), "Move to Trash…") : null),
        el("p", { class: "meta" }, "From a Google Takeout export? Deleting the downloaded copies doesn't free Google storage. Use Accounts for per-account delete lists.")],
      junk: () => [el("p", { class: "para" }, "Very blurry or dark shots, accidental pocket photos, expired codes and chain forwards. Nothing was deleted: they're in _Review/Junk."),
        el("button", { class: "mx-btn", onclick: open("Junk", junk, "Not junk? Open it and use Move to put it in a folder.") }, "Look at them")],
      private: () => [el("p", { class: "para" }, "Photos of IDs, passports, cards, medical papers or passwords. Think about deleting them from cloud accounts, or keeping them in a locked album."),
        el("button", { class: "mx-btn", onclick: open("Private", priv) }, "Look at them")],
      unsure: () => [el("p", { class: "para" }, "Claude looked twice and still wasn't sure. Open each one and use Move to choose its folder; it's remembered next time."),
        el("button", { class: "mx-btn", onclick: open("Not sure", unsure) }, "Sort them by hand")],
      videos: () => [el("p", { class: "para" }, "Videos take the most space. The biggest ones:"),
        el("div", { class: "vlist" }, vids.map(v => el("button", { class: "vrow", onclick: () => lightbox(vids, vids.indexOf(v)) },
          el("img", { src: v.src, alt: "" }), el("span", { class: "nm" }, v.name), el("span", { class: "num" }, v.duration ? mmss(v.duration) : ""),
          el("b", { class: "num" }, size(v.bytes)))))],
    };
    body.replaceChildren(...parts[t]());
  };
  const head = el("div", { class: "clean-tiles" }, tiles.map(([t, e, name, n, sub]) =>
    el("button", { "data-t": t, onclick: () => show(t) }, el("span", { class: "e" }, e), el("b", {}, fmt(n)), el("span", {}, name), el("small", {}, sub))));
  dialog("Clean up", [head, body], null, "wide-ish");
  show(tab);
}
async function trashFlow() {
  let near = false, info;
  const load_ = async () => { try { info = await fetch(`/api/trash?near=${near ? 1 : 0}`, { cache: "no-store" }).then(r => r.json()); } catch (e) { info = null; } };
  await load_();
  if (!info || info.error) return toast((info && info.error) || "Couldn't list the duplicates.");
  const render = () => dialog("Move duplicates to the Trash", [
    el("p", { class: "para" }, `${fmt(info.files)} extra copies (${size(info.bytes)}) from your photos folder go to the Mac's Trash. The copy that's kept stays. Until you empty the Trash, Finder's “Put Back” undoes it.`),
    el("label", { class: "check-row" }, el("input", { type: "checkbox", checked: near, onchange: async e => { near = e.target.checked; await load_(); render(); } }),
      "Also look-alikes (burst shots, resized copies). They are different files, so look first."),
    info.files ? el("div", { class: "row" }, el("div", { class: "trash-strip" }, info.ids.slice(0, 14).map(i => byId[i] ? el("img", { src: byId[i].mini, alt: "" }) : null)),
      el("button", { class: "mx-btn small", onclick: () => { const list = info.ids.map(i => byId[i]).filter(Boolean);
        browse("Going to the Trash", list, { badge: i => "keeps " + ((byId[i.group && i.group.keep] || {}).name || "a copy"),
          note: "Each of these goes to the Trash; the file named on it is kept.", actions: [el("button", { class: "mx-btn small", onclick: trashFlow }, "Back")] }); } },
        `Look at all ${fmt(info.files)}`)) : null,
    el("p", { class: "meta" }, "Each file is checked again right before: unchanged since the scan, and its kept copy still there."),
  ], [el("span", { class: "spacer" }), el("button", { class: "mx-btn ghost", onclick: closeAll }, "Cancel"),
      el("button", { class: "mx-btn solid danger", disabled: !info.files, onclick: () => runJob("trash", { confirm: info.files, near }, "Moving to the Trash",
        () => toast("Done. They're in the Trash.")) }, `Move ${fmt(info.files)} to Trash`)], "pc");
  render();
}

/* ---------- trips & events ---------- */
function eventsDialog() {
  if (!events.length) return toast("No trips or events found. They need photos with dates (and locations for trips).");
  const list = el("div", { class: "evlist" }, events.slice().reverse().map(e => {
    const its = e.ids.map(i => byId[i]).filter(Boolean);
    return el("button", { class: "ev", onclick: () => browse(e.name, its) },
      el("div", { class: "strip" }, its.slice(0, 4).map(i => el("img", { src: i.mini, alt: "", loading: "lazy" }))),
      el("div", {}, el("b", {}, e.name), el("small", {}, `${e.kind === "trip" ? "🧭 Trip" : "🎉 Event"} · ${e.named ? e.auto_name.replace("Trip · ", "") + " · " : ""}${fmt(its.length)} files`)));
  }));
  dialog("Trips & events", [list], [
    el("button", { class: "mx-btn", onclick: () => api("/api/open", { folder: "_albums" }).catch(() => {}) }, icon("folder"), "Open Albums"),
    el("span", { class: "spacer" }),
    el("button", { class: "mx-btn solid", onclick: async () => {
      if (!await confirmBox("Name them with Claude", ["Claude gets each group's dates, a few photo captions and a rough location (rounded to about 10 km), and suggests names like “Goa beach trip”.",
        "No photos are sent for this. It uses your Claude plan."], "Name them")) return eventsDialog();
      runJob("events_name", {}, "Naming trips & events", () => { toast("Named. The Albums folders were renamed too."); eventsDialog(); });
    } }, "Name them with Claude")]);
}

/* ---------- map ---------- */
function mapDialog() {
  const pts = live().filter(i => i.geo && !i.dupe);
  if (!pts.length) return toast("None of these photos have a location.");
  let useTiles = pref("osm") === "1", z = 2, cx = 0, cy = 0;
  const wrap = el("div", { class: "map" }), tl = el("div", { class: "map-tiles" }), dl = el("div", { class: "map-dots" });
  const attrib = el("div", { class: "map-attr" });
  wrap.append(tl, dl, attrib);
  const P = (lat, lon, zz) => {
    const s = 256 * 2 ** zz, si = Math.min(.9999, Math.max(-.9999, Math.sin(lat * Math.PI / 180)));
    return [(lon + 180) / 360 * s, (0.5 - Math.log((1 + si) / (1 - si)) / (4 * Math.PI)) * s];
  };
  const fit = () => {
    const W = wrap.clientWidth || 800, H = wrap.clientHeight || 500;
    z = 1;
    for (let zz = 16; zz >= 1; zz--) {
      const xs = pts.map(p => P(p.geo[0], p.geo[1], zz));
      const w = Math.max(...xs.map(p => p[0])) - Math.min(...xs.map(p => p[0])), h = Math.max(...xs.map(p => p[1])) - Math.min(...xs.map(p => p[1]));
      if (w < W - 120 && h < H - 120) { z = zz; break; }
    }
    const xs = pts.map(p => P(p.geo[0], p.geo[1], z));
    cx = (Math.max(...xs.map(p => p[0])) + Math.min(...xs.map(p => p[0]))) / 2;
    cy = (Math.max(...xs.map(p => p[1])) + Math.min(...xs.map(p => p[1]))) / 2;
    draw();
  };
  const draw = () => {
    const W = wrap.clientWidth, H = wrap.clientHeight, n = 2 ** z;
    tl.replaceChildren();
    if (useTiles) {
      for (let tx = Math.floor((cx - W / 2) / 256); tx <= Math.floor((cx + W / 2) / 256); tx++)
        for (let ty = Math.max(0, Math.floor((cy - H / 2) / 256)); ty <= Math.min(n - 1, Math.floor((cy + H / 2) / 256)); ty++)
          tl.append(el("img", { src: `https://tile.openstreetmap.org/${z}/${((tx % n) + n) % n}/${ty}.png`, alt: "", draggable: "false",
            style: `left:${tx * 256 - cx + W / 2}px;top:${ty * 256 - cy + H / 2}px` }));
    }
    attrib.replaceChildren(...(useTiles ? [el("a", { href: "https://www.openstreetmap.org/copyright", target: "_blank", rel: "noopener" }, "© OpenStreetMap contributors")] : []));
    const cells = {};
    pts.forEach(p => {
      const [x, y] = P(p.geo[0], p.geo[1], z), sx = x - cx + W / 2, sy = y - cy + H / 2;
      if (sx < -30 || sy < -30 || sx > W + 30 || sy > H + 30) return;
      const k = Math.floor(sx / 46) + "," + Math.floor(sy / 46);
      (cells[k] = cells[k] || { x: 0, y: 0, list: [] }).list.push(p);
      cells[k].x += sx; cells[k].y += sy;
    });
    dl.replaceChildren(...Object.values(cells).map(c => {
      const n_ = c.list.length, x = c.x / n_, y = c.y / n_, d = Math.min(64, 30 + Math.sqrt(n_) * 4);
      return el("button", { class: "dot", style: `left:${x - d / 2}px;top:${y - d / 2}px;width:${d}px;height:${d}px`, "aria-label": `${n_} photos`,
        onclick: () => {
          const spread = new Set(c.list.map(p => p.geo.map(v => v.toFixed(3)).join())).size;
          if (spread > 1 && z < 16) { cx += x - W / 2; cy += y - H / 2; zoom(2); } else browse(`${fmt(n_)} photos here`, c.list);
        } }, el("img", { src: c.list[0].mini, alt: "" }), n_ > 1 ? el("span", {}, fmt(n_)) : null);
    }));
  };
  const zoom = (dz, ax, ay) => {
    const nz = Math.max(1, Math.min(18, z + dz)), W = wrap.clientWidth, H = wrap.clientHeight;
    ax = ax ?? W / 2; ay = ay ?? H / 2;
    const f = 2 ** (nz - z), wx = cx - W / 2 + ax, wy = cy - H / 2 + ay;
    cx = wx * f - ax + W / 2; cy = wy * f - ay + H / 2; z = nz; draw();
  };
  let drag = null;
  wrap.addEventListener("pointerdown", e => { if (e.target.closest(".dot")) return; drag = [e.clientX, e.clientY]; wrap.setPointerCapture(e.pointerId); });
  wrap.addEventListener("pointermove", e => { if (!drag) return; cx -= e.clientX - drag[0]; cy -= e.clientY - drag[1]; drag = [e.clientX, e.clientY]; draw(); });
  wrap.addEventListener("pointerup", () => drag = null);
  wrap.addEventListener("wheel", e => { e.preventDefault(); const r = wrap.getBoundingClientRect(); zoom(e.deltaY < 0 ? 1 : -1, e.clientX - r.left, e.clientY - r.top); }, { passive: false });
  const tilesBox = el("label", { class: "check-row" }, el("input", { type: "checkbox", checked: useTiles, onchange: e => { useTiles = e.target.checked; setPref("osm", useTiles ? "1" : "0"); draw(); } }),
    el("span", {}, "Street map", el("small", {}, " loads map pictures from OpenStreetMap; only the map area you look at is sent, never your photos")));
  dialog(`Map · ${fmt(pts.length)} photos`, [wrap], [tilesBox, el("span", { class: "spacer" }),
    el("button", { class: "mx-icon", "aria-label": "Zoom out", onclick: () => zoom(-1) }, icon("minus")),
    el("button", { class: "mx-icon", "aria-label": "Zoom in", onclick: () => zoom(1) }, icon("plus")),
    el("button", { class: "mx-btn small", onclick: fit }, "Fit")], "wide mapdlg");
  requestAnimationFrame(fit);
}

/* ---------- highlights ---------- */
async function highlightsDialog() {
  const years = [...new Set(live().filter(i => i.taken).map(i => new Date(i.taken * 1000).getFullYear()))].sort((a, b) => b - a);
  if (!years.length) return toast("No dated photos, so no years to make highlights for.");
  const hl = S.steps && S.steps.highlights ? await getJSON("highlights.json") : null;
  let useClaude = true, year = "";
  const made = hl ? Object.entries(hl.years).sort((a, b) => b[0] - a[0]) : [];
  dialog("Highlights", [
    el("p", { class: "para" }, "For each year: the best photos (no duplicates, screenshots or documents), copied into Highlights/ with a slideshow video."
      + (S.ffmpeg ? "" : " Install ffmpeg (brew install ffmpeg) for the video.")),
    made.length ? el("div", { class: "hl" }, made.map(([y, v]) => el("div", { class: "hly" }, el("b", {}, y),
      v.video ? el("video", { src: `/api/highlight/${y}`, controls: true, preload: "metadata" }) : null,
      el("button", { class: "mx-btn small", onclick: () => browse(`Highlights ${y}`, v.ids.map(i => byId[i]).filter(Boolean)) }, `${v.ids.length} photos`)))) : null,
    el("div", { class: "segrow" }, el("span", {}, "Year"), el("select", { class: "mx-select", onchange: e => year = e.target.value },
      el("option", { value: "" }, "All years"), years.map(y => el("option", { value: y }, y)))),
    el("label", { class: "check-row" }, el("input", { type: "checkbox", checked: true, onchange: e => useClaude = e.target.checked }),
      el("span", {}, "Let Claude pick the best", el("small", {}, " (uses your plan; otherwise the sharpest are used)"))),
  ], [el("button", { class: "mx-btn", onclick: () => api("/api/open", { folder: "_highlights" }).catch(() => toast("Make them first.")) }, icon("folder"), "Open folder"),
      el("span", { class: "spacer" }),
      el("button", { class: "mx-btn solid", onclick: () => runJob("highlights", { year, local: !useClaude }, "Making highlights", () => highlightsDialog()) }, icon("film"), made.length ? "Make again" : "Make highlights")]);
}

/* ---------- upload: Google Photos, Apple Photos ---------- */
async function shareDialog() {
  let g = null, a = null;
  try { g = await fetch("/api/google", { cache: "no-store" }).then(r => r.json()); } catch (e) {}
  if (S.platform === "darwin") try { a = await fetch("/api/apple?albums=1", { cache: "no-store" }).then(r => r.json()); } catch (e) {}
  let strip = true, albums = true, aAlbums = true;
  const gBox = el("section", { class: "share" }, el("h3", {}, "Google Photos"));
  if (!g || g.error && !g.configured) gBox.append(el("p", { class: "para" }, (g && g.error) || "Couldn't check Google."));
  if (g && !g.configured) gBox.append(
    el("p", { class: "para" }, "Upload the sorted library into one Google account, an album per folder. Google requires a free key of your own, once:"),
    el("ol", { class: "steps" },
      el("li", {}, "Open ", el("a", { href: "https://console.cloud.google.com/apis/library/photoslibrary.googleapis.com", target: "_blank", rel: "noopener" }, "Google Cloud console"), ", make a project and enable the Photos Library API."),
      el("li", {}, "OAuth consent screen: External, and add your Gmail as a test user."),
      el("li", {}, "Credentials → Create credentials → OAuth client ID → Desktop app → Download JSON."),
      el("li", {}, "Save it as ", el("code", {}, "secrets/google_client.json"), " in the Snapsift folder, then press Check again.")),
    el("button", { class: "mx-btn", onclick: shareDialog }, "Check again"));
  else if (g && !g.signed_in) gBox.append(
    el("p", { class: "para" }, "Snapsift can only add photos and make albums. It can't see, change or delete anything already in your Google Photos."),
    el("button", { class: "mx-btn solid", onclick: () => runJob("google_login", {}, "Finish signing in in the new browser tab", () => { toast("Signed in to Google."); shareDialog(); }) }, "Sign in with Google"));
  else if (g) gBox.append(
    el("p", { class: "para" }, `Signed in as ${g.email || "your Google account"}. ${fmt(g.left)} of ${fmt(g.files)} files to upload (${size(g.bytes || 0)}), ${fmt(g.albums)} albums.`),
    el("label", { class: "check-row" }, el("input", { type: "checkbox", checked: true, onchange: e => strip = e.target.checked }),
      el("span", {}, "Remove location before uploading", el("small", {}, " (recommended; the date stays)"))),
    el("label", { class: "check-row" }, el("input", { type: "checkbox", checked: true, onchange: e => albums = e.target.checked }), "Also albums for trips & events"),
    el("div", { class: "row" },
      el("button", { class: "mx-btn solid", disabled: !g.left, onclick: async () => {
        if (!await confirmBox("Upload to Google Photos", [`${fmt(g.left)} files (${size(g.bytes || 0)}) go to ${g.email || "your Google account"}${strip ? ", without their location" : ", including their location"}.`,
          "Uploads count toward that account's storage. Run it again any time: what's already up is skipped."], "Upload")) return shareDialog();
        runJob("google_upload", { strip, albums }, "Uploading to Google Photos", () => toast("Uploaded to Google Photos."));
      } }, g.left ? `Upload ${fmt(g.left)} files` : "All uploaded"),
      el("button", { class: "linkish", onclick: () => api("/api/google_logout", {}).then(shareDialog).catch(() => {}) }, "Sign out")));
  const aBox = a && !a.unsupported ? el("section", { class: "share" }, el("h3", {}, "Apple Photos"),
    el("p", { class: "para" }, `Import the sorted copies into Photos on this Mac, an album per folder inside a “Snapsift” folder. ${fmt(a.files)} files to import.`),
    el("label", { class: "check-row" }, el("input", { type: "checkbox", checked: true, onchange: e => aAlbums = e.target.checked }), "Also albums for trips & events"),
    el("button", { class: "mx-btn solid", disabled: !a.files, onclick: async () => {
      if (!await confirmBox("Import into Apple Photos", [`This adds ${fmt(a.files)} files to your Photos library, and to iCloud Photos if that's on.`, "The first time, macOS asks to let Snapsift control Photos."], "Import")) return shareDialog();
      runJob("apple_import", { albums: aAlbums }, "Importing into Apple Photos", () => toast("Imported into Apple Photos."));
    } }, a.files ? `Import ${fmt(a.files)} files` : "All imported")) : null;
  dialog("Upload", [gBox, aBox], null, "wide-ish");
}

/* ---------- privacy ---------- */
function privacyDialog() {
  const li = (b, t) => el("li", {}, el("b", {}, b), " ", t);
  dialog("Privacy", [
    el("h4", {}, "Stays on this computer"),
    el("ul", { class: "plist" }, li("Your photos.", "Only read. The sorted folders are copies."), li("Previews, captions, labels, lists.", "In the Snapsift folder (dashboard/data and work), never uploaded or committed."),
      li("Your home location.", "Worked out here to spot trips; never sent anywhere.")),
    el("h4", {}, "Leaves it, only for what you start"),
    el("ul", { class: "plist" },
      li("Claude:", "small previews of your photos, plus each file's date, camera, name and “near/far from home”. No coordinates, no folder paths. Claude can only read the preview sheets it's given."),
      li("Naming trips with Claude:", "dates, captions and a location rounded to about 10 km."),
      li("Street map:", "map pictures come from OpenStreetMap for the area you look at; off unless you turn it on."),
      li("Google Photos upload:", "the files you choose, to your account, location removed by default."),
      li("Jev (if you pick it):", "a 280px preview and the file name of each file, to TypeSafe.")),
    el("h4", {}, "Forget this library"),
    el("p", { class: "para" }, "Deletes Snapsift's previews, captions, labels and lists for this library. Your photos and the sorted folders are not touched. Only the list of what was already uploaded is kept, so nothing is uploaded twice."),
  ], [S.google && S.google.signed_in ? el("button", { class: "mx-btn", onclick: () => api("/api/google_logout", {}).then(() => toast("Signed out of Google.")).catch(() => {}) }, "Sign out of Google") : null,
      el("span", { class: "spacer" }),
      el("button", { class: "mx-btn solid danger", onclick: async () => {
        if (!await confirmBox("Forget this library?", ["Snapsift's previews, captions and lists for this library are deleted. Your photos and sorted folders stay."], "Forget", true)) return privacyDialog();
        try { await api("/api/forget", {}); } catch (e) { return; }
        location.href = "/";
      } }, "Forget this library")]);
}

/* ---------- start ---------- */
function newSort() {
  mode = "setup";
  pick.source = pick.dest = pick.peek = null; pick.typing = null;
  resetStageForSetup(); setHeader(); renderPanel();
  setPill(null, "Choose your photos");
}
async function init() {
  paintIcons();
  if (DEMO) {
    const c = await getJSON("categories.json"); setCats(c);
    await loadLibrary(true);
    S = { source: "~/Pictures/Camera roll (demo)", platform: "demo" };
  } else {
    try { S = await api("/api/state"); } catch (e) { S = {}; }
    setCats(S.categories);
  }
  buildCards();
  if (!DEMO && S.job && S.job.running && S.job.step === "sort") {
    pick.source = S.source;
    runInfo = { files: S.files, bytes: S.bytes };
    beginRunning();
  } else if (DEMO || (S.steps && S.steps.apply)) {
    if (!DEMO) await loadLibrary(true);
    mode = "done"; sphereFromItems(); fillStatic(); showDone(false);
    pick.source = S.source;
    if (!DEMO && S.job && S.job.running) watchJob(NAMES[S.job.phase] || "Working");
  } else {
    mode = "setup"; setPill(null, "Choose your photos");
  }
  setHeader(); renderPanel();
  requestAnimationFrame(tick);
  if (!DEMO && params.get("source") && mode !== "running") {  // ?source=...&dest=... fills both folders in, ready to press Start
    if (mode === "done") newSort();
    await choose("source", params.get("source"));
    if (pick.source) await choose("dest", params.get("dest") || pick.source + " (sorted)");
  }
  if (params.has("auto") && mode === "done") setTimeout(replay, 1200);
}
$("go").onclick = sortWithClaude;
$("btnNew").onclick = newSort;
$("btnFolders").onclick = openFolders;
$("btnOpen").onclick = () => api("/api/open", {}).catch(() => {});
initTools();
addEventListener("keydown", e => {
  if (e.target.matches("input, textarea, select") || $("overlay").children.length) return;
  if (e.code === "Space" && mode === "done") { e.preventDefault(); replay(); }
});
init();
