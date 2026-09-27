/* Courtroom visualiser — vanilla JS, no build step, no network dependencies.
 * Data source: the FastAPI backend when reachable, otherwise the pre-exported
 * bundle (data/bundle.js, loaded by a <script> tag so it also works from file://),
 * so a live demo survives a dead server or no network at all.
 * Owner: Engineer 7.
 */
"use strict";

const $ = (sel) => document.querySelector(sel);
const SVG_NS = "http://www.w3.org/2000/svg";
const API = location.protocol.startsWith("http") ? "/api" : null;
const S = { mode: null, bundle: null, cases: [], strategies: [], trial: null, idx: 0, timer: null, caseFiles: {} };

function el(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}
function svg(tag, attrs = {}, text) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const pct = (p) => `${(100 * p).toFixed(1)}%`;
const title = (s) => s.replaceAll("_", " ");

async function fetchJSON(url, opts = {}, timeoutMs = 20000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...opts, signal: ctrl.signal });
    if (!res.ok) throw new Error(`${res.status} ${(await res.text()).slice(0, 200)}`);
    return await res.json();
  } finally {
    clearTimeout(t);
  }
}

/* ------------------------------------------------------------------ data layer */

async function init() {
  try {
    if (!API) throw new Error("opened from disk");
    await fetchJSON(`${API}/health`, {}, 1500);
    S.mode = "live";
    S.cases = await fetchJSON(`${API}/cases`);
    S.strategies = await fetchJSON(`${API}/strategies`);
  } catch {
    if (!window.COURTROOM_BUNDLE) {
      $("#mode").textContent = "no data source";
      showBanner("Neither the API nor the offline bundle is available. Run `python -m courtroom serve` or `python -m courtroom export`.", "pros");
      return;
    }
    S.bundle = window.COURTROOM_BUNDLE;
    S.mode = "offline";
    S.cases = S.bundle.cases;
    S.strategies = S.bundle.strategies;
    S.bundle.cases.forEach((c) => (S.caseFiles[c.id] = c));
  }
  const mode = $("#mode");
  mode.textContent = S.mode === "live" ? "● live API" : "● offline bundle";
  mode.className = `status ${S.mode}`;

  const caseSel = $("#case");
  S.cases.forEach((c) => caseSel.append(el("option", { value: c.id }, c.title)));
  const names = S.strategies.map((s) => s.name).filter((n) => !n.includes("<"));
  if (S.mode === "live") names.push("mixed:0.4");
  for (const id of ["#pstrat", "#dstrat"]) names.forEach((n) => $(id).append(el("option", { value: n }, title(n))));
  $("#pstrat").value = "aggressive";
  $("#dstrat").value = "conservative";

  $("#run").addEventListener("click", runTrial);
  $("#grun").addEventListener("click", runGame);
  $("#case").addEventListener("change", () => { runTrial(); renderCaseFile(); });
  $("#play").addEventListener("click", togglePlay);
  $("#first").addEventListener("click", () => seek(0));
  $("#last").addEventListener("click", () => seek(Infinity));
  $("#prev").addEventListener("click", () => seek(S.idx - 1));
  $("#next").addEventListener("click", () => seek(S.idx + 1));
  $("#scrub").addEventListener("input", (e) => seek(+e.target.value));
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, select")) return;
    if (e.key === "ArrowRight") seek(S.idx + 1);
    if (e.key === "ArrowLeft") seek(S.idx - 1);
    if (e.key === " ") { e.preventDefault(); togglePlay(); }
  });
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
  await runTrial();
  renderCaseFile();
}

async function getCaseFile(id) {
  if (!S.caseFiles[id]) S.caseFiles[id] = await fetchJSON(`${API}/cases/${encodeURIComponent(id)}`);
  return S.caseFiles[id];
}

async function runTrial() {
  const req = { case_id: $("#case").value, prosecution: $("#pstrat").value, defense: $("#dstrat").value, seed: +$("#seed").value || 0 };
  const btn = $("#run");
  btn.disabled = true;
  try {
    let trial;
    if (S.mode === "live") {
      trial = await fetchJSON(`${API}/trial`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) });
    } else {
      trial = S.bundle.trials[`${req.case_id}|${req.prosecution}|${req.defense}|${req.seed}`];
      if (!trial) {
        showBanner("Offline mode: this pairing/seed was not pre-exported. Try seed 0 with aggressive/conservative/adaptive pairings.", "pros");
        return;
      }
    }
    stop();
    S.trial = trial;
    S.idx = 0;
    setupTrial();
    seek(0);
    togglePlay();
  } catch (err) {
    showBanner(`Trial failed: ${err.message}`, "pros");
  } finally {
    btn.disabled = false;
  }
}

/* ------------------------------------------------------------------ playback */

function togglePlay() {
  if (S.timer) return stop();
  if (!S.trial) return;
  if (S.idx >= S.trial.events.length - 1) seek(0);
  $("#play").textContent = "⏸";
  S.timer = setInterval(() => {
    if (S.idx >= S.trial.events.length - 1) return stop();
    seek(S.idx + 1);
  }, +$("#speed").value);
}
function stop() {
  clearInterval(S.timer);
  S.timer = null;
  $("#play").textContent = "▶";
}
function seek(i) {
  if (!S.trial) return;
  S.idx = Math.max(0, Math.min(S.trial.events.length - 1, i));
  $("#scrub").value = S.idx;
  renderFrame();
}

/* ------------------------------------------------------------------ trial rendering */

function setupTrial() {
  const t = S.trial;
  $("#scrub").max = t.events.length - 1;
  const thr = t.verdict.snapshot.elements[0].threshold_probability;
  $("#threshold-label").textContent = `threshold ${pct(thr)} · ${title(t.verdict.snapshot.elements.length + " elements")}`;
  buildStream();
  buildTimeline();
  buildGraph();
  buildLedger();
  buildFindings();
}

function renderFrame() {
  const t = S.trial;
  const ev = t.events[S.idx];
  const done = S.idx === t.events.length - 1;
  renderGauges(ev);
  renderRules(ev);
  updateStream();
  updateTimelineCursor();
  updateGraph();
  if (done) {
    const v = t.verdict;
    const pros = ["guilty", "liable"].includes(v.outcome);
    showBanner(`${title(v.outcome).toUpperCase()}<small>${escapeHTML(v.reason)}</small>`, pros ? "pros" : "def", true);
  } else {
    $("#banner").className = "banner hidden";
  }
  $("#findings-card").style.opacity = done ? 1 : 0.45;
  $("#ledger-card").style.opacity = done ? 1 : 0.45;
}

function escapeHTML(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
function showBanner(html, cls, trusted = false) {
  const b = $("#banner");
  b.className = `banner ${cls}`;
  if (trusted) b.innerHTML = html; else b.textContent = html;
}

function renderGauges(ev) {
  const thr = S.trial.verdict.snapshot.elements[0].threshold_probability;
  const box = $("#gauges");
  box.replaceChildren();
  const rows = Object.entries(ev.element_probabilities).map(([k, p]) => [title(k), p, false]);
  rows.push(["BURDEN (weakest element)", ev.burden_index, true]);
  for (const [name, p, isBurden] of rows) {
    const g = el("div", { class: `gauge${isBurden ? " burden" : ""}` });
    const label = el("div", { class: "label" });
    label.append(el("span", {}, name), el("span", {}, pct(p)));
    const bar = el("div", { class: "bar" });
    const fill = el("div", { class: `fill${p >= thr ? " met" : ""}` });
    fill.style.width = pct(p);
    const mark = el("div", { class: "thr", title: `threshold ${pct(thr)}` });
    mark.style.left = pct(thr);
    bar.append(fill, mark);
    g.append(label, bar);
    box.append(g);
  }
}

function renderRules(ev) {
  const box = $("#rules");
  box.replaceChildren();
  if (ev.action?.rationale) box.append(el("div", { class: "why" }, `Agent rationale: ${ev.action.rationale}`));
  for (const r of ev.rules) {
    const row = el("div", { class: "rule" });
    row.append(el("span", { class: "rid" }, r.rule_id), document.createTextNode(r.detail));
    box.append(row);
  }
  if (!ev.rules.length && !ev.action?.rationale) box.append(el("div", { class: "hint" }, "No rule fired on this event."));
  box.append(el("div", { class: "hash" }, `event #${ev.seq} · sha256 ${ev.hash}`));
}

function buildStream() {
  const ol = $("#stream");
  ol.replaceChildren();
  S.trial.events.forEach((ev, i) => {
    const li = el("li", { class: [ev.actor || "court", ev.kind].join(" ") });
    li.append(el("span", { class: "seq" }, String(ev.seq).padStart(3, "0")));
    li.append(el("span", { class: "who" }, ev.actor ? (ev.actor === "prosecution" ? "P" : "D") : "§"));
    li.append(document.createTextNode(ev.summary));
    li.addEventListener("click", () => { stop(); seek(i); });
    ol.append(li);
  });
}
function updateStream() {
  const items = $("#stream").children;
  for (let i = 0; i < items.length; i++) {
    items[i].classList.toggle("future", i > S.idx);
    items[i].classList.toggle("current", i === S.idx);
  }
  const cur = items[S.idx], box = $("#stream");
  if (cur && (cur.offsetTop < box.scrollTop || cur.offsetTop + cur.offsetHeight > box.scrollTop + box.clientHeight)) {
    box.scrollTop = cur.offsetTop - box.clientHeight / 2;
  }
}

const ELEMENT_COLOURS = () => [cssVar("--accent"), cssVar("--def"), cssVar("--ok"), cssVar("--pending"), cssVar("--pros")];

function buildTimeline() {
  const t = S.trial;
  const g = $("#timeline");
  g.replaceChildren();
  const W = 800, H = 220, L = 34, R = 8, T = 10, B = 22;
  const n = t.events.length;
  const x = (i) => L + ((W - L - R) * i) / Math.max(1, n - 1);
  const y = (p) => T + (H - T - B) * (1 - p);
  // phase bands
  let start = 0;
  const bands = [];
  t.events.forEach((ev, i) => {
    if (i > 0 && ev.phase !== t.events[i - 1].phase) { bands.push([start, i - 1, t.events[i - 1].phase]); start = i; }
  });
  bands.push([start, n - 1, t.events[n - 1].phase]);
  bands.forEach(([a, b, ph], k) => {
    if (k % 2) g.append(svg("rect", { x: x(a), y: T, width: Math.max(0, x(b) - x(a)), height: H - T - B, style: `fill: ${cssVar("--line")}; opacity: .45` }));
    if (x(b) - x(a) > 60) g.append(svg("text", { x: x(a) + 4, y: H - 6, class: "muted" }, title(ph)));
  });
  for (const p of [0, 0.5, 1]) {
    g.append(svg("line", { x1: L, x2: W - R, y1: y(p), y2: y(p), class: "axis" }));
    g.append(svg("text", { x: 2, y: y(p) + 4, class: "muted" }, `${p * 100}%`));
  }
  const thr = t.verdict.snapshot.elements[0].threshold_probability;
  g.append(svg("line", { x1: L, x2: W - R, y1: y(thr), y2: y(thr), style: `stroke: ${cssVar("--ink")}; stroke-dasharray: 5 4; stroke-width: 1.2` }));
  g.append(svg("text", { x: W - R - 90, y: y(thr) - 4 }, `threshold ${pct(thr)}`));
  const colours = ELEMENT_COLOURS();
  const legend = $("#timeline-legend");
  legend.replaceChildren();
  Object.keys(t.events[0].element_probabilities).forEach((k, idx) => {
    const d = t.events.map((ev, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(ev.element_probabilities[k]).toFixed(1)}`).join("");
    g.append(svg("path", { d, style: `fill: none; stroke: ${colours[idx % colours.length]}; stroke-width: 2.2` }));
    const item = el("span");
    const sw = el("i");
    sw.style.cssText = `width: 14px; height: 3px; background: ${colours[idx % colours.length]}`;
    item.append(sw, document.createTextNode(title(k)));
    legend.append(item);
  });
  g.append(svg("line", { id: "cursor", x1: x(0), x2: x(0), y1: T, y2: H - B, style: `stroke: ${cssVar("--accent")}; stroke-width: 2` }));
  g.dataset.n = n;
}
function updateTimelineCursor() {
  const n = +$("#timeline").dataset.n;
  const xx = 34 + ((800 - 34 - 8) * S.idx) / Math.max(1, n - 1);
  const c = $("#cursor");
  c.setAttribute("x1", xx);
  c.setAttribute("x2", xx);
}

function buildGraph() {
  const g = $("#graph");
  g.replaceChildren();
  const nodes = S.trial.graph.nodes;
  const W = 800, H = 420;
  const cols = { prosecution: nodes.filter((n) => n.owner === "prosecution"), defense: nodes.filter((n) => n.owner === "defense") };
  const pos = {};
  for (const [side, list] of Object.entries(cols)) {
    const cx = side === "prosecution" ? 300 : 500;
    list.forEach((n, i) => (pos[n.id] = { x: cx, y: 30 + ((H - 50) * (i + 0.5)) / Math.max(1, list.length) }));
  }
  g.append(svg("text", { x: 300, y: 14, "text-anchor": "middle", style: `fill: ${cssVar("--pros")}; font-weight: 700` }, "PROSECUTION"));
  g.append(svg("text", { x: 500, y: 14, "text-anchor": "middle", style: `fill: ${cssVar("--def")}; font-weight: 700` }, "DEFENSE"));
  if (!nodes.length) g.append(svg("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "muted" }, "No evidence in this case file."));
  for (const e of S.trial.graph.edges) {
    const a = pos[e.source], b = pos[e.target];
    if (!a || !b) continue;
    let d;
    if (a.x === b.x) { const bend = a.x < 400 ? 60 : -60; d = `M${a.x},${a.y} C${a.x + bend},${a.y} ${b.x + bend},${b.y} ${b.x},${b.y}`; }
    else d = `M${a.x},${a.y} C${(a.x + b.x) / 2},${a.y} ${(a.x + b.x) / 2},${b.y} ${b.x},${b.y}`;
    const contra = e.relation === "contradicts";
    g.append(svg("path", { d, style: `fill: none; stroke: ${contra ? cssVar("--bad") : cssVar("--ok")}; stroke-width: 1.6; ${contra ? "stroke-dasharray: 5 4;" : ""} opacity: .75` }));
  }
  for (const n of nodes) {
    const p = pos[n.id];
    const r = 7 + Math.min(12, n.weight * 3);
    const grp = svg("g", { "data-id": n.id });
    grp.append(svg("title", {}, `${n.id}: ${n.label} (${n.kind})`));
    grp.append(svg("circle", { cx: p.x, cy: p.y, r, class: "node", "data-final": n.status }));
    const left = n.owner === "prosecution";
    grp.append(svg("text", { x: left ? p.x - r - 6 : p.x + r + 6, y: p.y + 4, "text-anchor": left ? "end" : "start" }, `${n.id} · ${n.label.slice(0, 26)}${n.label.length > 26 ? "…" : ""}`));
    g.append(grp);
  }
}
function updateGraph() {
  const status = {};
  for (const ev of S.trial.events.slice(0, S.idx + 1)) if (ev.subject && ev.status && ev.status !== "impeached") status[ev.subject] = ev.status;
  const colour = { admitted: cssVar("--ok"), excluded: cssVar("--bad"), offered: cssVar("--pending") };
  document.querySelectorAll("#graph circle.node").forEach((c) => {
    const id = c.parentNode.dataset.id;
    c.style.fill = colour[status[id]] || cssVar("--grey");
    c.style.stroke = S.trial.events[S.idx].subject === id ? cssVar("--ink") : "none";
    c.style.strokeWidth = 3;
  });
}

function buildLedger() {
  const t = S.trial, lp = t.ledgers.prosecution, ld = t.ledgers.defense;
  const tbl = $("#ledger");
  tbl.replaceChildren();
  const head = el("tr");
  head.append(el("th", {}, ""), el("th", {}, "Prosecution"), el("th", {}, "Defense"));
  tbl.append(head);
  const rows = [["Strategy", t.prosecution_strategy, t.defense_strategy], ...[
    ["Budget left", "budget"], ["Spent", "spent"], ["Admitted / presented", null], ["Excluded", "excluded"],
    ["Objections (sustained)", "obj"], ["Impeachments", "impeachments"], ["Violations", "violations"], ["Sanctions", "sanctions"],
  ].map(([label, k]) => {
    const f = (l) => k === null ? `${l.admitted} / ${l.presented}` : k === "obj" ? `${l.objections} (${l.sustained})` : `${+l[k].toFixed(2)}`;
    return [label, f(lp), f(ld)];
  }), ["Utility", t.utilities.prosecution.toFixed(2), t.utilities.defense.toFixed(2)]];
  for (const [a, b, c] of rows) {
    const tr = el("tr");
    tr.append(el("td", {}, a), el("td", { class: "num" }, b), el("td", { class: "num" }, c));
    tbl.append(tr);
  }
}

function buildFindings() {
  const v = S.trial.verdict;
  const tbl = $("#findings");
  tbl.replaceChildren();
  const head = el("tr");
  ["Element", "Log-odds", "P", "Threshold", "", "Counted evidence (log-odds contribution)"].forEach((h) => head.append(el("th", {}, h)));
  tbl.append(head);
  for (const es of v.snapshot.elements) {
    const tr = el("tr");
    tr.append(el("td", {}, title(es.element_id)), el("td", { class: "num" }, es.log_odds), el("td", { class: "num" }, pct(es.probability)),
      el("td", { class: "num" }, es.threshold), el("td", { class: es.met ? "met" : "unmet" }, es.met ? "MET" : "NOT MET"),
      el("td", {}, es.contributions.filter((c) => c.counted).map((c) => `${c.evidence_id} ${c.log_odds >= 0 ? "+" : ""}${c.log_odds.toFixed(2)}`).join(" · ") || "—"));
    tbl.append(tr);
  }
  $("#digest").textContent = S.trial.digest;
}

/* ------------------------------------------------------------------ game theory */

async function runGame() {
  const caseId = $("#case").value;
  const strategies = $("#gstrats").value.split(",");
  const status = $("#gstatus");
  $("#grun").disabled = true;
  status.textContent = S.mode === "live" ? "Running Monte-Carlo tournament…" : "";
  try {
    let game;
    if (S.mode === "live") {
      game = await fetchJSON(`${API}/game`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: caseId, strategies, seeds: +$("#gseeds").value || 20 }) }, 120000);
    } else {
      game = S.bundle.games[caseId];
      if (strategies.length !== 2) status.textContent = "Offline bundle contains 2×2 games only.";
    }
    renderGame(game);
    if (S.mode === "live") status.textContent = `${game.seeds.length} seeds per cell · exact rational solver`;
  } catch (err) {
    status.textContent = `Failed: ${err.message}`;
  } finally {
    $("#grun").disabled = false;
  }
}

function renderGame(game) {
  const a = game.analysis;
  const pureNE = new Set(a.equilibria.filter((e) => e.pure).map((e) =>
    `${Object.keys(e.row_mix).find((k) => e.row_mix[k] === 1)}|${Object.keys(e.col_mix).find((k) => e.col_mix[k] === 1)}`));
  const grid = Object.fromEntries(game.cells.map((c) => [`${c.row}|${c.col}`, c]));
  const tbl = el("table", { class: "matrix" });
  const head = el("tr");
  head.append(el("th", {}, "P \\ D"));
  game.col_strategies.forEach((c) => head.append(el("th", {}, title(c))));
  tbl.append(head);
  for (const r of game.row_strategies) {
    const tr = el("tr");
    tr.append(el("th", {}, title(r)));
    for (const c of game.col_strategies) {
      const cell = grid[`${r}|${c}`];
      const td = el("td", { class: pureNE.has(`${r}|${c}`) ? "ne" : "" });
      td.append(el("div", { class: "pay" }, `(${cell.mean_row.toFixed(2)}, ${cell.mean_col.toFixed(2)})`));
      td.append(el("div", { class: "rate" }, `P wins ${(100 * cell.prosecution_win_rate).toFixed(0)}% · ±${cell.se_row.toFixed(2)}`));
      tr.append(td);
    }
    tbl.append(tr);
  }
  $("#matrix").replaceChildren(tbl);

  const eqBox = $("#equilibria");
  eqBox.replaceChildren();
  const colours = [cssVar("--pros"), cssVar("--def"), cssVar("--pending")];
  a.equilibria.forEach((e, i) => {
    const box = el("div", { class: "eq" });
    box.append(el("strong", {}, `NE ${i + 1} · ${e.pure ? "pure" : "mixed"} · ${e.verified ? "verified ✔" : "UNVERIFIED"}`));
    for (const [who, mix, exact] of [["Prosecution", e.row_mix, e.row_mix_exact], ["Defense", e.col_mix, e.col_mix_exact]]) {
      box.append(el("div", { class: "hint" }, `${who}: ${Object.entries(mix).map(([k, p]) => `${title(k)} ${(100 * p).toFixed(1)}%`).join(", ")}`));
      const bar = el("div", { class: "mixbar", title: JSON.stringify(exact) });
      Object.values(mix).forEach((p, j) => { const s = el("span"); s.style.cssText = `width:${100 * p}%;background:${colours[j % 3]}`; bar.append(s); });
      box.append(bar);
    }
    box.append(el("div", { class: "hint" }, `Expected utility: P ${e.row_payoff.toFixed(3)} · D ${e.col_payoff.toFixed(3)}`));
    eqBox.append(box);
  });

  const notes = $("#notes");
  notes.replaceChildren();
  const facts = [
    `Dominant strategy — P: ${a.row_dominant ? `${title(a.row_dominant)} (${a.row_dominance})` : "none"}; D: ${a.col_dominant ? `${title(a.col_dominant)} (${a.col_dominance})` : "none"}.`,
    `IESDS survivors: {${a.iesds_rows.map(title).join(", ")}} × {${a.iesds_cols.map(title).join(", ")}}.`,
    ...a.notes,
  ];
  facts.forEach((f) => notes.append(el("li", {}, f)));
  renderDynamics(game);
}

function renderDynamics(game) {
  const g = $("#dynamics");
  g.replaceChildren();
  const P = 40, W = 420, span = W - 2 * P;
  const X = (v) => P + span * v, Y = (v) => W - P - span * v;
  g.append(svg("rect", { x: P, y: P, width: span, height: span, style: `fill: none; stroke: ${cssVar("--line")}` }));
  g.append(svg("text", { x: W / 2, y: W - 8, "text-anchor": "middle", class: "muted" }, `Prosecution share playing ${title(game.row_strategies[0])}`));
  const yl = svg("text", { x: 12, y: W / 2, "text-anchor": "middle", class: "muted", transform: `rotate(-90 12 ${W / 2})` }, `Defense share playing ${title(game.col_strategies[0])}`);
  g.append(yl);
  for (const v of [0, 0.5, 1]) {
    g.append(svg("text", { x: X(v), y: W - P + 14, "text-anchor": "middle", class: "muted" }, v));
    g.append(svg("text", { x: P - 6, y: Y(v) + 4, "text-anchor": "end", class: "muted" }, v));
  }
  if (game.dynamics?.length) {
    const d = game.dynamics.map((pt, i) => `${i ? "L" : "M"}${X(pt.x[0]).toFixed(1)},${Y(pt.y[0]).toFixed(1)}`).join("");
    g.append(svg("path", { d, style: `fill: none; stroke: ${cssVar("--accent")}; stroke-width: 2` }));
    const s = game.dynamics[0], e = game.dynamics[game.dynamics.length - 1];
    g.append(svg("circle", { cx: X(s.x[0]), cy: Y(s.y[0]), r: 4, style: `fill: ${cssVar("--muted")}` }));
    g.append(svg("circle", { cx: X(e.x[0]), cy: Y(e.y[0]), r: 5, style: `fill: ${cssVar("--accent")}` }));
  }
  for (const eq of game.analysis.equilibria) {
    const cx = X(eq.row_mix[game.row_strategies[0]]), cy = Y(eq.col_mix[game.col_strategies[0]]);
    g.append(svg("circle", { cx, cy, r: 7, style: `fill: none; stroke: ${cssVar("--pending")}; stroke-width: 3` }));
    g.append(svg("text", { x: cx + 10, y: cy - 8 }, "NE"));
  }
}

/* ------------------------------------------------------------------ case file */

async function renderCaseFile() {
  const box = $("#casefile");
  try {
    const c = await getCaseFile($("#case").value);
    box.replaceChildren(el("h2", {}, c.title), el("p", {}, c.synopsis));
    const meta = el("p");
    [c.case_type, title(c.standard), `budget ${c.budget}`, `${c.max_primary_turns} turns`, `perception accuracy ${c.perception_accuracy}`, ...c.tags]
      .forEach((t) => meta.append(el("span", { class: "tag" }, t)));
    box.append(meta, el("h2", {}, `Charge: ${c.charge}`));
    const ul = el("ul");
    c.elements.forEach((e) => ul.append(el("li", {}, `${e.name} — ${e.description}`)));
    box.append(ul);
    const tbl = el("table");
    const head = el("tr");
    ["ID", "Side", "Kind", "Exhibit", "Support", "Reliability", "Latent defects (hidden from opponent)"].forEach((h) => head.append(el("th", {}, h)));
    tbl.append(head);
    for (const it of c.evidence) {
      const defects = [it.hearsay && "hearsay", !it.authenticated && "unauthenticated", !it.lawfully_obtained && "unlawfully obtained",
        !it.disclosed && "not disclosed", !it.personal_knowledge && "no personal knowledge"].filter(Boolean);
      const tr = el("tr");
      tr.append(el("td", {}, it.id), el("td", {}, it.owner), el("td", {}, title(it.kind)), el("td", {}, it.title),
        el("td", {}, Object.entries(it.support).map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v}`).join(", ")),
        el("td", { class: "num" }, it.reliability), el("td", { class: "flag" }, defects.join(", ") || "—"));
      tbl.append(tr);
    }
    box.append(tbl);
    if (!c.evidence.length) box.append(el("p", { class: "hint" }, "This case file contains no evidence (edge case)."));
  } catch (err) {
    box.textContent = `Could not load case file: ${err.message}`;
  }
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((b) => { const on = b.dataset.tab === name; b.classList.toggle("active", on); b.setAttribute("aria-selected", on); });
  document.querySelectorAll(".tabpanel").forEach((p) => p.classList.toggle("hidden", p.id !== `tab-${name}`));
  $(".controls .playback").style.display = name === "trial" ? "" : "none";
  if (name === "game" && !$("#matrix").children.length) runGame();
}

init();
