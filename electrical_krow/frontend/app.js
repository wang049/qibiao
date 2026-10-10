/* 第 1 项出表功能页。完整客户端由同事 Electron 工程承载。
   嵌入：/?embed=1 ；跨源时加 api=http://127.0.0.1:端口 或 window.ELECTRICAL_API_BASE。 */
const $ = (id) => document.getElementById(id);
function tx(key, vars) {
  return typeof window.t === "function" ? window.t(key, vars) : key;
}

let loggedIn = false;

function readQuery() {
  try {
    return new URLSearchParams(location.search || "");
  } catch (e) {
    return new URLSearchParams();
  }
}

function embedMode() {
  if (window.ELECTRICAL_EMBED === true) return true;
  const flag = readQuery().get("embed");
  return flag === "1" || flag === "true";
}

function apiUrl(path) {
  if (/^https?:\/\//i.test(path || "")) return path;
  const base = String(
    window.ELECTRICAL_API_BASE || readQuery().get("api") || ""
  ).replace(/\/$/, "");
  const rel = path.startsWith("/") ? path : "/" + path;
  return base + rel;
}

window.electricalApiUrl = apiUrl;

function authHeaders() {
  return loggedIn ? { Authorization: "Bearer local" } : {};
}

async function json(url, opts) {
  const extra = opts || {};
  const { headers, ...rest } = extra;
  const resp = await fetch(apiUrl(url), {
    credentials: "same-origin",
    ...rest,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...headers },
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const msg = data.detail || data.error || resp.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

const fileInput = $("file");
const pick = $("pick");
const drop = $("drop");
const fname = $("fname");
const fsize = $("fsize");
const go = $("go");
const pauseBtn = $("pause");
const stopBtn = $("stop");
const status = $("status");
const health = $("health");
const progress = $("progress");
const barfill = $("barfill");
const result = $("result");
const steps = {
  read: $("st-read"),
  ocr: $("st-ocr"),
  qc: $("st-qc"),
  extract: $("st-extract"),
  write: $("st-write"),
};
let chosen = null;
let llmOk = false;
let currentJob = null;
let submitting = false;
let attaching = false;
let runPaused = false;
let delivery = "client";
let workPanel = embedMode() ? "extract" : "home";
let jobTimer = null;
let jobRows = [];
let viewingJob = null;
let lastShownJob = null;

function isSite() {
  return delivery === "site";
}

function applyShellCopy() {
  const sub = $("brand-sub");
  if (sub) sub.textContent = isSite() ? tx("brand.sub.site") : tx("brand.sub.client");
  const railSub = $("rail-sub");
  if (railSub) railSub.textContent = isSite() ? tx("brand.sub.site") : tx("brand.sub.client");
  const badge = $("local-badge");
  if (badge) badge.textContent = isSite() ? tx("badge.site") : tx("badge.local");
  const hint = $("drop-hint");
  if (hint) hint.textContent = isSite() ? tx("drop.hint.site") : tx("drop.hint.client");
}

function environmentLabel(id, fallback) {
  if (id === "cloud") return tx("env.cloud");
  if (id === "site") return tx("env.site");
  return fallback || tx("unset");
}

function envCaption(h) {
  if (h && (h.environment || h.environment_label)) {
    return environmentLabel(h.environment, h.environment_label);
  }
  const server = String((h && h.server) || "");
  if (server) return server.replace(/^https?:\/\//, "");
  return tx("unset");
}

function applyEnvLabels(h) {
  document.querySelectorAll(".js-env-label").forEach((el) => {
    el.textContent = envCaption(h);
  });
}

function setRunButtons(running, paused, stopping) {
  go.style.display = running ? "none" : "";
  pauseBtn.classList.toggle("show", !!running);
  stopBtn.classList.toggle("show", !!running);
  pauseBtn.textContent = paused ? tx("resume") : tx("pause");
  pauseBtn.disabled = !running || !!stopping;
  stopBtn.disabled = !running || !!stopping;
  pick.disabled = !!running;
  drop.style.pointerEvents = running ? "none" : "";
  const modelSel = $("model");
  if (modelSel) modelSel.disabled = !!running;
}

function fmtSize(n) {
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  return (n / 1048576).toFixed(1) + " MB";
}
function fmtElapsed(sec) {
  sec = Number(sec);
  if (!isFinite(sec) || sec < 0) return "—";
  sec = Math.floor(sec);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m ? tx("fmt.elapsed.ms", { m: m, s: s }) : tx("fmt.elapsed.s", { s: s });
}
function jobMessageText(raw) {
  const text = String(raw || "");
  if (typeof window.localizeJobMessage === "function") {
    const mapped = window.localizeJobMessage(text);
    if (mapped) return mapped;
  }
  return text;
}

function paintJobStatus(raw, elapsedInner) {
  const source = raw == null ? "" : String(raw);
  status.dataset.stage = source;
  const msg = jobMessageText(source) || tx("status.extracting");
  status.textContent = elapsedInner
    ? msg + "  ·  " + tx("status.used", { t: elapsedInner })
    : msg;
}
function setStage(stage) {
  const order = ["read", "ocr", "qc", "extract", "write"];
  let hit = order.indexOf(stage);
  if (hit < 0) hit = 0;
  order.forEach((key, i) => {
    if (!steps[key]) return;
    steps[key].className = "step" + (i < hit ? " done" : i === hit ? " on" : "");
  });
}
async function pollJob(id) {
  let last = null;
  for (let i = 0; i < 6; i++) {
    try {
      const pr = await fetch(apiUrl("/api/jobs/" + encodeURIComponent(id)), {
        credentials: "same-origin",
        headers: authHeaders(),
      });
      const data = await pr.json().catch(() => ({}));
      return { pr, data };
    } catch (e) {
      last = e;
      await new Promise((r) => setTimeout(r, 800));
    }
  }
  throw last || new Error(tx("err.poll"));
}

// 推荐模型（服务端配置默认）；下拉里在名字后加「（推荐）」，value 仍是原名
let recommendedModel = "";
function modelLabel(name) {
  return name && name === recommendedModel ? name + tx("model.recommended") : name;
}

function fillModels(names, current) {
  const sel = $("model");
  if (!sel) return;
  const seen = new Set();
  const list = [];
  (names || []).forEach((name) => {
    if (name && !seen.has(name)) {
      seen.add(name);
      list.push(name);
    }
  });
  if (current && !seen.has(current)) list.unshift(current);
  sel.innerHTML = "";
  if (!list.length) {
    const opt = document.createElement("option");
    opt.value = current || "";
    opt.textContent = current || tx("model.loading");
    sel.appendChild(opt);
  } else {
    list.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = modelLabel(name);
      sel.appendChild(opt);
    });
  }
  sel.value = current || list[0] || "";
}

async function loadModels() {
  if (!loggedIn) return;
  try {
    const data = await json("/api/models");
    recommendedModel = String(data.recommended || "");
    fillModels(data.models || [], data.model || "");
    await applyDefaultModel();
    renderPrefControls();
  } catch {
    fillModels([], $("model") && $("model").value);
  }
}

async function showWork(on, username) {
  loggedIn = on;
  applyDesktopTitle();
  if (!on) {
    workPanel = "home";
    viewingJob = null;
    stopJobTimer();
  }
  $("login-card").hidden = on;
  $("who-wrap").hidden = !on || embedMode();
  const badge = $("local-badge");
  if (badge) badge.hidden = !on || embedMode();
  const name = on ? (username || "") : "";
  $("who").textContent = name;
  const av = $("who-avatar");
  if (av) {
    const ch = name.trim().charAt(0);
    av.textContent = ch ? ch.toUpperCase() : tx("avatar.fallback");
  }
  $("rail").hidden = !on || embedMode();
  if (embedMode()) workPanel = on ? "extract" : "home";
  applyWorkPanel();
  go.disabled = !(chosen && llmOk && loggedIn);
  if (on) {
    await loadModels();
    startJobTimer();
    await loadJobs();
    resumeActiveJob();
  }
}

function setPanel(name) {
  workPanel = name;
  applyWorkPanel();
}

function applyWorkPanel() {
  const on = loggedIn;
  if (embedMode() && on) workPanel = "extract";
  const home = on && workPanel === "home";
  const kb = on && workPanel === "kb";
  const extract = on && workPanel === "extract";
  const io = on && workPanel === "io";
  $("home-card").hidden = !home;
  $("work-card").hidden = !extract;
  $("kb-card").hidden = !kb;
  $("io-card").hidden = !io;
  document.body.classList.toggle("is-logged", on);
  document.body.classList.toggle("is-home", home);
  document.body.classList.toggle("is-kb", kb);
  document.querySelector("main")?.classList.toggle("is-work", on);
  document.querySelector("main")?.classList.toggle("is-kb", kb);
  $("rail-home")?.classList.toggle("is-on", home);
  $("rail-extract")?.classList.toggle("is-on", extract);
  $("rail-io")?.classList.toggle("is-on", io);
  $("rail-kb")?.classList.toggle("is-on", kb);
  if (!on) {
    $("kicker").textContent = isSite() ? tx("login.kicker.site") : tx("login.kicker.client");
    $("title").innerHTML = tx("hero.login.title");
    $("lead").textContent = tx("hero.login.lead");
    return;
  }
  if (home) {
    $("kicker").textContent = tx("hero.home.kicker");
    $("title").innerHTML = tx("hero.home.title");
    $("lead").textContent = tx("hero.home.lead");
    return;
  }
  if (kb) {
    $("kicker").textContent = tx("hero.kb.kicker");
    $("title").innerHTML = tx("hero.kb.title");
    $("lead").textContent = tx("hero.kb.lead");
    if (typeof window.kbEnsure === "function") window.kbEnsure();
    return;
  }
  if (io) {
    $("kicker").textContent = tx("hero.io.kicker");
    $("title").innerHTML = tx("hero.io.title");
    $("lead").textContent = tx("hero.io.lead");
    return;
  }
  $("kicker").textContent = tx("hero.extract.kicker");
  $("title").innerHTML = tx("hero.extract.title");
  $("lead").textContent = isSite() ? tx("hero.extract.lead.site") : tx("hero.extract.lead.client");
}

function escText(s) {
  return String(s || "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function jobStatusLabel(st) {
  if (st === "done") return { text: tx("job.done"), cls: "done" };
  if (st === "error") return { text: tx("job.fail"), cls: "fail" };
  if (st === "paused" || st === "pausing") return { text: tx("job.paused"), cls: "run" };
  if (st === "stopping") return { text: tx("job.stopping"), cls: "run" };
  if (st === "queued") return { text: tx("job.queued"), cls: "run" };
  return { text: tx("job.running"), cls: "run" };
}

function fmtWhen(ts) {
  const n = Number(ts);
  if (!isFinite(n) || n <= 0) return "";
  const d = new Date(n < 1e12 ? n * 1000 : n);
  if (!isFinite(d.getTime())) return "";
  return d.toLocaleString(typeof window.uiLang === "function" && window.uiLang() === "en" ? "en-US" : "zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function startJobTimer() {
  if (jobTimer) return;
  jobTimer = setInterval(() => {
    if (loggedIn) loadJobs();
  }, 4000);
}

function stopJobTimer() {
  if (!jobTimer) return;
  clearInterval(jobTimer);
  jobTimer = null;
}

// 文档类型短标签：侧栏任务行 / 最近核对表用
function kindTag(row) {
  if (!row || row.extract === false) return row && row.kind_label ? tx("kind.skip") : "";
  const label = String(row.kind_label || "");
  if (row.likely_scan) return tx("kind.scan");
  if (/DPR/i.test(label)) return "DPR";
  if (/逆变器/.test(label) || /\bSR\b/.test(label)) return "SR";
  const mapped = (typeof window.kindLabelText === "function") ? window.kindLabelText(label) : label;
  return mapped.slice(0, 18);
}

function fileInfoKindLabel(info) {
  const raw = String((info && info.kind_label) || "");
  if (typeof window.kindLabelText === "function") return window.kindLabelText(raw);
  return raw;
}

function fileInfoScope(info) {
  const raw = String((info && info.estimate_scope) || "");
  if (typeof window.estimateScopeText === "function") return window.estimateScopeText(raw);
  if (raw === "历史" || !raw) return tx("inspect.hist");
  return raw;
}

function fileInfoKindNote(info) {
  const raw = String((info && info.kind_note) || "");
  if (typeof window.kindNoteText === "function") return window.kindNoteText(raw);
  return raw;
}

function fileNameOf(download) {
  const raw = String(download || "").split("/").pop() || "";
  try { return decodeURIComponent(raw); } catch (_) { return raw; }
}

const EMPTY_JOBS_SVG = "<svg viewBox='0 0 64 48' width='64' height='48' fill='none' aria-hidden='true'>"
  + "<rect x='8' y='6' width='34' height='38' rx='3' stroke='currentColor' stroke-width='1.5'/>"
  + "<path d='M15 16h20M15 23h20M15 30h12' stroke='currentColor' stroke-width='1.5' stroke-linecap='round'/>"
  + "<circle cx='48' cy='34' r='9' fill='var(--surface)' stroke='currentColor' stroke-width='1.5'/>"
  + "<path d='M48 30v8M44 34h8' stroke='currentColor' stroke-width='1.5' stroke-linecap='round'/></svg>";

function renderJobs() {
  const host = $("job-list");
  if (!host) return;
  if (!jobRows.length) {
    host.innerHTML = "<div class='job-empty'>" + EMPTY_JOBS_SVG
      + "<p>" + tx("empty.jobs") + "</p><small>" + tx("empty.jobsHint") + "</small></div>";
    renderHome();
    return;
  }
  const active = viewingJob || currentJob || "";
  const busy = !!currentJob;
  host.innerHTML = jobRows.map((row) => {
    const id = String(row.id || "");
    const st = jobStatusLabel(row.status || "");
    const name = String(row.source || tx("spec"));
    const when = fmtWhen(row.created_at);
    const bits = [];
    if (when) bits.push(when);
    if (row.status === "done" && row.found != null) bits.push(tx("meta.found", { n: row.found }));
    if (row.status === "done" && Number(row.pending_note || 0) > 0) bits.push(tx("meta.pending", { n: Number(row.pending_note) }));
    if (row.status === "error" && row.detail) bits.push(String(row.detail).slice(0, 24));
    const tag = kindTag(row);
    const on = id && id === active;
    const block = busy && id !== currentJob;
    return "<button type='button' class='job-row" + (on ? " is-on" : "") + "'"
      + " data-id='" + escText(id) + "'"
      + " title='" + escText(name) + "'"
      + (block ? " disabled" : "") + ">"
      + "<span class='job-status " + st.cls + "'>" + st.text + "</span>"
      + "<span class='job-copy'>"
      + "<span class='job-name'>" + escText(name) + "</span>"
      + "<span class='job-meta'>"
      + (tag ? "<i class='job-tag'>" + escText(tag) + "</i> " : "")
      + escText(bits.join(" · ") || (row.message || ""))
      + "</span></span>"
      + "</button>";
  }).join("");
  host.querySelectorAll(".job-row").forEach((btn) => {
    btn.addEventListener("click", () => openHistory(btn.getAttribute("data-id") || ""));
  });
  renderHome();
}

// ===== 出表页：一行统计 + 最近核对表 =====
// 嵌入模式只有出表页会显示，所以数字与历史都放出表页；工作台只留 SOR 出表一张卡。
let lastHealth = null;

function fmtMinutes(sec) {
  const n = Number(sec);
  if (!isFinite(n) || n <= 0) return "—";
  if (n < 90) return tx("fmt.min.s", { n: Math.round(n) });
  return tx("fmt.min.m", { n: (n / 60).toFixed(n < 600 ? 1 : 0).replace(/\.0$/, "") });
}

// 出表页顶部一行：知识库版本 · 待专家口径 · 本账号已出 N 份 · 平均耗时
function workMetaText() {
  const done = jobRows.filter((r) => r.status === "done" && r.extract !== false);
  const timed = done.filter((r) => Number(r.elapsed_seconds || 0) > 0 && !r.stopped_early);
  const avg = timed.length
    ? timed.reduce((a, r) => a + Number(r.elapsed_seconds), 0) / timed.length
    : 0;
  const kb = (lastHealth && lastHealth.knowledge) || {};
  const pending = Number((lastHealth && lastHealth.pending_rulings) || 0);
  const bits = [];
  bits.push(kb.version ? tx("meta.kbVer", { v: kb.version }) : tx("meta.kbNone"));
  if (pending > 0) bits.push(tx("meta.pendingN", { n: pending }));
  if (done.length) bits.push(tx("meta.doneN", { n: done.length }));
  if (timed.length) bits.push(tx("meta.avg", { t: fmtMinutes(avg) }));
  return bits.join(" · ");
}

function renderHome() {
  const meta = $("work-meta");
  if (meta) {
    meta.textContent = workMetaText();
    meta.hidden = !meta.textContent;
  }

  renderRecent();
}

// 出表页底部的最近核对表：出表进行中收起，别挤着正在跑的任务
function renderRecent() {
  const host = $("work-recent");
  const list = $("work-recent-list");
  if (!host || !list) return;
  const rows = jobRows.filter((r) => r.status === "done" && r.download).slice(0, 5);
  const busy = !!currentJob || submitting || attaching;
  host.hidden = busy || !rows.length;
  if (host.hidden) return;
  list.innerHTML = rows.map((r) => {
    const id = String(r.id || "");
    const total = Number(r.field_count || 0);
    const found = r.found != null ? Number(r.found) : null;
    const tag = kindTag(r);
    const pend = Number(r.pending_note || 0);
    const bits = [];
    if (r.extract === false) bits.push(tx("recent.skipList"));
    else if (found != null) bits.push(tx("meta.found", { n: found + (total ? "/" + total : "") }));
    if (pend > 0) bits.push(tx("meta.pending", { n: pend }));
    if (r.stopped_early) bits.push(tx("recent.early"));
    const open = embedMode() ? "" : "<button type='button' class='recent-btn' data-open='" + escText(r.download) + "'>" + tx("recent.open") + "</button>";
    return "<div class='recent-row' data-id='" + escText(id) + "'>"
      + "<div class='recent-main'>"
      + "<span class='recent-name'>" + escText(r.source || tx("spec"))
      + (tag ? "<i class='job-tag'>" + escText(tag) + "</i>" : "") + "</span>"
      + "<span class='recent-meta'>" + escText([fmtWhen(r.created_at), fmtElapsed(r.elapsed_seconds)].filter(Boolean).join(" · ")) + "</span>"
      + "</div>"
      + "<span class='recent-found'>" + escText(bits.join(" · ") || "—") + "</span>"
      + "<span class='recent-actions'>"
      + "<button type='button' class='recent-btn' data-view='" + escText(id) + "'>" + tx("recent.view") + "</button>"
      + open
      + "<a class='recent-btn' href='" + escText(apiUrl(r.download)) + "' download>" + tx("recent.download") + "</a>"
      + "</span></div>";
  }).join("");
  list.querySelectorAll("[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => openHistory(btn.getAttribute("data-view") || ""));
  });
  list.querySelectorAll("[data-open]").forEach((btn) => {
    btn.addEventListener("click", () => openWorkbookLocally(btn.getAttribute("data-open") || ""));
  });
}

$("work-open-dir")?.addEventListener("click", async () => {
  try {
    await json("/api/output/open", { method: "POST", body: "{}" });
  } catch (_) { /* 打不开目录就不提示 */ }
});

async function loadJobs() {
  if (!loggedIn) return;
  try {
    const data = await json("/api/jobs");
    jobRows = data.jobs || [];
    renderJobs();
  } catch {
    if (!$("job-list").children.length) {
      $("job-list").innerHTML = "<p class='job-empty'>" + tx("jobs.unread") + "</p>";
    }
  }
}

function resultMarkup(data) {
  const elapsed = fmtElapsed(data.elapsed_seconds);
  const filled = (data.filled != null) ? data.filled : "—";
  const extract = data.extract !== false;
  const found = extract ? ((data.found != null) ? data.found : filled) : "—";
  const partial = extract ? ((data.partial != null) ? data.partial : "—") : "—";
  const miss = extract ? ((data.miss != null) ? data.miss : "—") : "—";
  let tip = "";
  if (data.stopped_early) {
    tip = tx("result.stoppedTip");
  } else if (!extract && data.kind_note) {
    tip = (typeof window.kindNoteText === "function") ? window.kindNoteText(data.kind_note) : data.kind_note;
  } else if (extract && Number(data.llm_calls || 0) < 1 && Number(miss) > 0) {
    tip = tx("result.noLlm");
  }
  const incomplete = Number(data.chunk_failures || 0) > 0;
  if (!tip && incomplete) {
    tip = tx("result.chunkFail", { n: Number(data.chunk_failures) });
    if (data.chunk_error) tip += " " + String(data.chunk_error);
  }
  const heading = data.stopped_early
    ? tx("result.stoppedHead")
    : (incomplete ? tx("result.incompleteHead") : tx("result.doneHead"));
  const dl = data.download
    ? "<a class='dl' href='" + escText(apiUrl(data.download)) + "' download>" + tx("result.download") + "</a>"
    : "";
  const pending = extract && data.pending_note != null ? Number(data.pending_note) : null;
  const pendingStat = pending != null
    ? "<div class='stat" + (pending > 0 ? " is-pend" : "") + "'><b>" + pending + "</b><span>" + tx("stat.pending") + "</span></div>"
    : "";
  return "<div class='result-head'><h2>" + heading + "</h2>" + dl + "</div>"
    + "<div class='stats" + (pendingStat ? " has-5" : "") + "'>"
    + "<div class='stat'><b>" + elapsed + "</b><span>" + tx("stat.elapsed") + "</span></div>"
    + "<div class='stat is-found'><b>" + found + "</b><span>" + tx("stat.found") + "</span></div>"
    + "<div class='stat is-partial'><b>" + partial + "</b><span>" + tx("stat.partial") + "</span></div>"
    + "<div class='stat is-miss'><b>" + miss + "</b><span>" + tx("stat.miss") + "</span></div>"
    + pendingStat
    + "</div>"
    + (extract ? groupBarsMarkup(data.groups) : "")
    + (extract ? compareMarkup(data.compare) : "")
    + (tip ? "<p class='result-note'>" + tip + "</p>" : "");
}

// 按 12 个业务分组的检索结论小条形：已检索到 / 局部对应 / 未检索到
function groupBarsMarkup(groups) {
  if (!Array.isArray(groups) || !groups.length) return "";
  const rows = groups.map((g) => {
    const total = Math.max(1, Number(g.total || 0));
    const f = Number(g.found || 0), p = Number(g.partial || 0), m = Number(g.miss || 0);
    const pct = (n) => (100 * n / total).toFixed(1) + "%";
    const weak = f === 0 && total >= 2;
    return "<div class='gbar" + (weak ? " is-weak" : "") + "' title='" + escText(tx("groups.title", { f: f, p: p, m: m })) + "'>"
      + "<span class='gbar-name'>" + escText(g.name) + "</span>"
      + "<span class='gbar-track'>"
      + "<i class='f' style='width:" + pct(f) + "'></i>"
      + "<i class='p' style='width:" + pct(p) + "'></i>"
      + "<i class='m' style='width:" + pct(m) + "'></i>"
      + "</span>"
      + "<span class='gbar-num'>" + f + "<small>/" + Number(g.total || 0) + "</small></span>"
      + "</div>";
  }).join("");
  return "<div class='groups'><div class='groups-head'><span>" + tx("groups.head") + "</span>"
    + "<span class='groups-legend'><i class='f'></i>" + tx("groups.legend.found")
    + "<i class='p'></i>" + tx("groups.legend.partial")
    + "<i class='m'></i>" + tx("groups.legend.miss") + "</span></div>"
    + rows + "</div>";
}

// 同名文件与上一次出表逐条比已检索到
function compareMarkup(cmp) {
  if (!cmp || cmp.prev_found == null) return "";
  const prev = Number(cmp.prev_found), now = Number(cmp.found);
  const delta = now - prev;
  const sign = delta > 0 ? "+" + delta : String(delta);
  const gained = Array.isArray(cmp.gained) ? cmp.gained : [];
  const lost = Array.isArray(cmp.lost) ? cmp.lost : [];
  const joiner = (typeof window.uiLang === "function" && window.uiLang() === "en") ? ", " : "、";
  const more = (list, n) => (n > list.length ? tx("compare.more", { n: n }) : "");
  let body = "";
  if (!gained.length && !lost.length) {
    body = "<p>" + tx("compare.same") + "</p>";
  } else {
    if (gained.length) body += "<p><b class='up'>" + tx("compare.gained", { n: Number(cmp.gained_n || gained.length) }) + "</b>: " + escText(gained.join(joiner)) + more(gained, Number(cmp.gained_n || 0)) + "</p>";
    if (lost.length) body += "<p><b class='down'>" + tx("compare.lost", { n: Number(cmp.lost_n || lost.length) }) + "</b>: " + escText(lost.join(joiner)) + more(lost, Number(cmp.lost_n || 0)) + "</p>";
  }
  return "<div class='compare'><div class='compare-head'>" + tx("compare.head")
    + "<span>" + escText(fmtWhen(cmp.prev_at)) + "</span></div>"
    + "<p class='compare-sum'>" + tx("compare.sum", { prev: prev, now: now })
    + " <b class='" + (delta > 0 ? "up" : (delta < 0 ? "down" : "")) + "'>" + (delta === 0 ? tx("compare.flat") : sign) + "</b></p>"
    + body + "</div>";
}

function showFinishedJob(data) {
  lastShownJob = data;
  progress.classList.add("show");
  liveLine({});
  barfill.style.width = "100%";
  setStage("write");
  steps.write.className = "step done";
  const elapsed = fmtElapsed(data.elapsed_seconds);
  status.className = "status";
  status.dataset.stage = "";
  status.textContent = (data.stopped_early
    ? tx("status.stopped")
    : (Number(data.chunk_failures || 0) > 0 ? tx("status.incomplete") : tx("status.done")))
    + "  ·  " + tx("status.used", { t: elapsed });
  result.className = "result show";
  result.innerHTML = resultMarkup(data);
  revealResult();
}

async function openHistory(id) {
  if (!id) return;
  if (currentJob && id !== currentJob) return;
  viewingJob = id;
  renderJobs();
  setPanel("extract");
  if (currentJob && id === currentJob) return;
  try {
    const data = await json("/api/jobs/" + encodeURIComponent(id));
    if (data.status === "error") {
      progress.classList.add("show");
      result.className = "result fail show";
      result.innerHTML = "<h2>" + tx("result.failHead") + "</h2><p class='result-note'>"
        + escText(data.detail || data.message || tx("result.failDefault")) + "</p>";
      status.className = "status err";
      status.textContent = data.detail || data.message || tx("result.failDefault");
      revealResult();
      return;
    }
    if (data.status === "done") {
      showFinishedJob(data);
    }
  } catch (e) {
    status.className = "status err";
    status.textContent = explainErr(e);
  }
}

async function refresh() {
  try {
    const h = await json("/api/health");
    lastHealth = h;
    delivery = h.delivery === "site" ? "site" : "client";
    applyShellCopy();
    renderHome();
    llmOk = !!h.ok;
    health.className = "health " + (h.ok ? "ok" : "err");
    applyHealthText();
    applyEnvLabels(h);
  } catch (err) {
    llmOk = false;
    health.className = "health err";
    $("health-text").textContent = String(err.message || err);
  }
  try {
    const s = await json("/api/session");
    await showWork(Boolean(s.logged_in), s.username || "");
  } catch {
    await showWork(false, "");
  }
}

$("pass-toggle").onclick = () => {
  const input = $("pass");
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  const btn = $("pass-toggle");
  btn.classList.toggle("on", show);
  btn.setAttribute("aria-label", show ? tx("login.hidePass") : tx("login.showPass"));
  btn.title = show ? tx("login.hidePass") : tx("login.showPass");
};

$("login").onclick = async () => {
  const msg = $("login-msg");
  msg.hidden = true;
  msg.classList.remove("is-info");
  try {
    const body = {
      username: $("user").value,
      password: $("pass").value,
    };
    const data = await json("/api/login", { method: "POST", body: JSON.stringify(body) });
    rememberLoginUser(body.username);
    await showWork(true, data.username);
    await refresh();
  } catch (err) {
    msg.hidden = false;
    msg.textContent = String(err.message || err);
  }
};

$("logout").onclick = async () => {
  await json("/api/logout", { method: "POST", body: "{}" });
  setFile(null);
  fileInput.value = "";
  workPanel = "home";
  viewingJob = null;
  jobRows = [];
  renderJobs();
  await showWork(false, "");
  await refresh();
};

function extractBusy() {
  return !!(currentJob || submitting || attaching);
}

// 点「SOR 参数提取 / 进入出表 / 新建出表」是准备再出一份，不是回看。
// 上次完成或点侧栏打开的核对结果会留在本页，必须清掉；正在跑的任务不能清。
function clearExtractOutcome() {
  viewingJob = null;
  lastShownJob = null;
  result.classList.remove("show", "fail");
  result.innerHTML = "";
  $("work-card")?.classList.remove("has-result");
  progress.classList.remove("show");
  barfill.style.width = "0%";
  Object.keys(steps).forEach((key) => {
    if (steps[key]) steps[key].className = "step";
  });
  status.className = "status";
  status.dataset.stage = "";
  status.textContent = "";
  liveLine({});
}

function goExtract(opts) {
  const clearFile = !!(opts && opts.clearFile);
  if (!extractBusy()) {
    if (clearFile) {
      setFile(null);
      if (fileInput) fileInput.value = "";
    }
    clearExtractOutcome();
    renderJobs();
  }
  setPanel("extract");
}

$("rail-home").onclick = () => setPanel("home");
$("rail-extract").onclick = () => goExtract();
$("rail-io").onclick = () => setPanel("io");
$("rail-kb").onclick = () => setPanel("kb");
$("rail-new").onclick = () => goExtract({ clearFile: true });
$("io-back").onclick = () => setPanel("home");
$("io-blank").onclick = async () => {
  const msg = $("io-msg");
  msg.hidden = true;
  try {
    await json("/api/io-sheet", { method: "POST" });
    msg.hidden = false;
    msg.textContent = tx("io.opened");
  } catch (err) {
    msg.hidden = false;
    msg.textContent = err.message || String(err);
  }
};
// 工作台卡片只切页，不自动弹文件选择；选文件由页内拖放区/按钮触发
document.querySelectorAll(".fn-card[data-go]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const go = btn.getAttribute("data-go") || "home";
    if (go === "extract") goExtract();
    else setPanel(go);
  });
});

function revealResult() {
  $("work-card")?.classList.add("has-result");
  requestAnimationFrame(() => {
    result.scrollIntoView({ behavior: motionReduced() ? "auto" : "smooth", block: "nearest" });
  });
}

function desktopSave() {
  if (embedMode()) return null;
  try {
    const api = window.pywebview && window.pywebview.api;
    return api && typeof api.save_sheet === "function" ? api : null;
  } catch (e) {
    return null;
  }
}

result.addEventListener("click", async (ev) => {
  const link = ev.target.closest("a.dl");
  if (!link) return;
  const api = desktopSave();
  if (!api) return;
  ev.preventDefault();
  const href = link.getAttribute("href") || "";
  const name = href.split("/").pop() || "";
  try {
    const out = await api.save_sheet(name);
    if (out && out.canceled) return;
    if (out && out.ok) {
      status.className = "status";
      const prev = (status.textContent || tx("status.done")).replace(/\s*·\s*(核对表已保存|Workbook saved)$/i, "");
      status.textContent = prev + "  ·  " + tx("status.saved");
      return;
    }
    throw new Error((out && out.error) || tx("err.save"));
  } catch (e) {
    status.className = "status err";
    status.textContent = explainErr(e);
  }
});
function setFile(f) {
  chosen = f || null;
  drop.classList.toggle("has", !!chosen);
  fname.textContent = chosen ? chosen.name : "";
  fsize.textContent = chosen ? fmtSize(chosen.size) : "";
  go.disabled = !(chosen && llmOk && loggedIn);
  pick.textContent = chosen ? tx("pick.change") : tx("pick");
  result.classList.remove("show");
  result.innerHTML = "";
  $("work-card")?.classList.remove("has-result");
  inspectChosen(chosen);
}

// ===== 选中文件后的体检卡：类型 / 页数 / 大小 / 是否 OCR / 预计耗时 =====
let inspectSeq = 0;
function fileInfoMarkup(info) {
  const chips = [];
  const label = fileInfoKindLabel(info);
  if (label) chips.push("<span class='fi-chip" + (info.extract === false ? " warn" : " ok") + "'>" + escText(label) + "</span>");
  else chips.push("<span class='fi-chip'>" + tx("inspect.kindPending") + "</span>");
  if (Number(info.page_count || 0) > 0) {
    const unit = info.page_unit === "页" || !info.page_unit ? tx("inspect.unit.page") : String(info.page_unit);
    chips.push("<span class='fi-chip'>" + Number(info.page_count) + " " + escText(unit) + "</span>");
  }
  chips.push("<span class='fi-chip'>" + escText(fmtSize(Number(info.size || 0))) + "</span>");
  if (String(info.suffix || "") === ".pdf") {
    chips.push(info.likely_scan
      ? "<span class='fi-chip warn'>" + tx("inspect.scanOcr") + "</span>"
      : "<span class='fi-chip'>" + tx("inspect.textNoOcr") + "</span>");
  }
  let est = "";
  if (info.extract === false) {
    est = escText(fileInfoKindNote(info) || tx("inspect.noList"));
  } else if (Number(info.estimate_seconds || 0) > 0) {
    const scope = fileInfoScope(info);
    est = tx("inspect.est", { t: fmtMinutes(info.estimate_seconds), n: Number(info.estimate_n || 0), scope: scope });
    if (info.likely_scan) est += tx("inspect.scanLonger");
  } else {
    est = tx("inspect.noHist");
  }
  return "<div class='fi-chips'>" + chips.join("") + "</div><p class='fi-est'>" + est + "</p>";
}

async function inspectChosen(f) {
  const host = $("file-info");
  if (!host) return;
  const seq = ++inspectSeq;
  if (!f) {
    host.hidden = true;
    host.innerHTML = "";
    return;
  }
  host.hidden = false;
  host.className = "file-info is-loading";
  host.innerHTML = fileInfoMarkup({ size: f.size, suffix: "." + String(f.name.split(".").pop() || "").toLowerCase() })
    .replace(tx("inspect.kindPending"), tx("inspect.kindLoading"));
  if (!loggedIn) return;
  try {
    const body = new FormData();
    body.append("file", f);
    const res = await fetch(apiUrl("/api/inspect"), {
      method: "POST", body, credentials: "same-origin", headers: authHeaders(),
    });
    const info = await res.json().catch(() => ({}));
    if (seq !== inspectSeq || !chosen) return;
    if (!res.ok) throw new Error(detailText(info) || info.detail || tx("err.inspect"));
    host.className = "file-info" + (info.extract === false ? " is-warn" : "");
    host.innerHTML = fileInfoMarkup(info);
  } catch (e) {
    if (seq !== inspectSeq || !chosen) return;
    host.className = "file-info";
    host.innerHTML = "<p class='fi-est'>" + escText(explainErr(e)) + "</p>";
  }
}

function liveLine(data) {
  const el = $("live");
  if (!el) return;
  const bits = [];
  const done = Number(data.chunk_done || 0), total = Number(data.chunk_total || 0);
  if (total > 0) bits.push(tx("live.chunk", { a: Math.min(done, total), b: total }));
  if (data.filled != null) bits.push(tx("live.filled", { n: Number(data.filled) }));
  el.hidden = !bits.length;
  el.textContent = bits.join(" · ");
}
function openPicker() { fileInput.click(); }
pick.addEventListener("click", openPicker);
drop.addEventListener("click", openPicker);
drop.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openPicker(); }
});
fileInput.addEventListener("change", () => setFile(fileInput.files[0] || null));
["dragenter", "dragover"].forEach((ev) => {
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); });
});
["dragleave", "drop"].forEach((ev) => {
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); });
});
drop.addEventListener("drop", (e) => {
  const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) setFile(f);
});

$("model").addEventListener("change", async () => {
  const name = $("model").value;
  setPref("model", name);
  if (!name) return;
  try {
    await json("/api/model", { method: "POST", body: JSON.stringify({ model: name }) });
    await refresh();
  } catch (err) {
    status.className = "status err";
    status.textContent = String(err.message || err);
  }
});

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function detailText(data) {
  const d = data && data.detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && d.message) return String(d.message);
  return "";
}

function isBusyConflict(httpStatus, data) {
  if (httpStatus !== 409) return false;
  const msg = detailText(data) || String((data && data.message) || "");
  return msg.indexOf("全站同时一份") >= 0
    || msg.indexOf("正在结束出表") >= 0
    || msg.indexOf("结束后即可") >= 0;
}

async function waitUntilIdle(onWait) {
  for (let i = 0; i < 400; i++) {
    try {
      const h = await json("/api/health");
      if (!h.busy) return true;
      if (typeof onWait === "function") onWait(h);
    } catch {
      /* 收尾时服务仍可能瞬时不可读，继续等锁 */
    }
    await sleep(800);
  }
  return false;
}

async function openWorkbookLocally(download) {
  const m = /\/files\/([^/?#]+)/.exec(String(download || ""));
  if (!m) return;
  try {
    await json("/api/files/" + m[1] + "/open", { method: "POST", body: "{}" });
  } catch (_) {
    /* 打不开就留着下载按钮 */
  }
}

async function followJob(jobId, t0, opts) {
  const startedHere = !!(opts && opts.startedHere);
  currentJob = jobId;
  viewingJob = jobId;
  loadJobs();
  while (loggedIn) {
    await sleep(800);
    const { pr, data } = await pollJob(jobId);
    if (!pr.ok) throw new Error(detailText(data) || data.detail || tx("err.poll"));
    const pct = Math.max(0, Math.min(100, data.percent || 0));
    barfill.style.width = pct + "%";
    setStage(data.stage || "extract");
    paintJobStatus(data.message || tx("status.extracting"), fmtElapsed((Date.now() - t0) / 1000));
    liveLine(data);
    const st = data.status || "";
    runPaused = st === "paused" || st === "pausing";
    setRunButtons(true, runPaused, st === "stopping" || st === "queued");
    if (st === "done") {
      liveLine({});
      showFinishedJob(data);
      // 只对本页发起的出表自动打开 / 提醒；刷新后接回的旧任务不打开
      if (startedHere) {
        const sheet = decodeURIComponent(String(data.download || "").split("/").pop() || "");
        finishAlert(tx("alert.done"), sheet || tx("alert.sheet"));
        if (prefs.autoOpen === "on" && !embedMode()) openWorkbookLocally(data.download);
      }
      await waitUntilIdle();
      break;
    }
    if (st === "error") {
      liveLine({});
      const why = detailText(data) || data.detail || tx("result.failDefault");
      if (startedHere) finishAlert(tx("alert.fail"), why);
      throw new Error(why);
    }
  }
}

async function resumeActiveJob() {
  if (!loggedIn || currentJob || submitting || attaching) return;
  attaching = true;
  try {
    let id = "";
    let busy = false;
    try {
      const h = await json("/api/health");
      busy = !!h.busy;
      if (h.active_job && h.active_job.id) id = String(h.active_job.id);
    } catch {
      return;
    }
    if (!id) {
      const row = (jobRows || []).find((r) => {
        const st = String(r.status || "");
        return st && st !== "done" && st !== "error";
      });
      if (row) id = String(row.id || "");
    }
    if (!id) {
      if (!busy) return;
      setPanel("extract");
      setRunButtons(true, false, true);
      progress.classList.add("show");
      status.className = "status";
      paintJobStatus(tx("status.waitLock"));
      await waitUntilIdle();
      return;
    }
    setPanel("extract");
    setRunButtons(true, false, false);
    result.classList.remove("show");
    result.innerHTML = "";
    $("work-card")?.classList.remove("has-result");
    progress.classList.add("show");
    status.className = "status";
    try {
      await followJob(id, Date.now());
    } catch (e) {
      if (!loggedIn) return;
      status.className = "status err";
      status.dataset.stage = "";
      status.textContent = explainErr(e);
      result.className = "result fail show";
      result.innerHTML = "<h2>" + tx("result.failHead") + "</h2><p class='result-note'>" + explainErr(e) + "</p>";
      revealResult();
    }
  } finally {
    attaching = false;
    currentJob = null;
    runPaused = false;
    if (loggedIn) {
      setRunButtons(false, false, false);
      go.disabled = !(chosen && llmOk && loggedIn);
      loadJobs();
    }
  }
}

go.addEventListener("click", async () => {
  if (!chosen || submitting || currentJob || attaching) return;
  submitting = true;
  viewingJob = null;
  lastShownJob = null;
  runPaused = false;
  renderRecent();
  setPanel("extract");
  setRunButtons(true, false, true);
  result.classList.remove("show");
  result.innerHTML = "";
  $("work-card")?.classList.remove("has-result");
  progress.classList.add("show");
  barfill.style.width = "2%";
  setStage("read");
  const t0 = Date.now();
  status.className = "status";
  paintJobStatus(tx("status.received"), tx("fmt.elapsed.s", { s: 0 }));
  let tick = setInterval(() => {
    if (!status.dataset.stage) return;
    paintJobStatus(status.dataset.stage, fmtElapsed((Date.now() - t0) / 1000));
  }, 1000);
  try {
    const waitNote = tx("status.waitPrev");
    const deadline = Date.now() + 20 * 60 * 1000;
    let job = null;
    while (!job) {
      if (Date.now() > deadline) {
        throw new Error(tx("err.busyWait"));
      }
      let busy = false;
      try {
        const h = await json("/api/health");
        busy = !!h.busy;
      } catch {
        busy = false;
      }
      if (busy) {
        paintJobStatus(waitNote, fmtElapsed((Date.now() - t0) / 1000));
        setRunButtons(true, false, true);
        await sleep(800);
        continue;
      }
      const body = new FormData();
      body.append("file", chosen);
      const started = await fetch(apiUrl("/api/jobs"), {
        method: "POST",
        body,
        credentials: "same-origin",
        headers: authHeaders(),
      });
      const payload = await started.json().catch(() => ({}));
      if (started.ok) {
        job = payload;
        break;
      }
      if (isBusyConflict(started.status, payload)) {
        paintJobStatus(waitNote, fmtElapsed((Date.now() - t0) / 1000));
        setRunButtons(true, false, true);
        await sleep(800);
        continue;
      }
      throw new Error(detailText(payload) || payload.detail || tx("err.start"));
    }
    setRunButtons(true, false, false);
    paintJobStatus(tx("status.received"));
    await followJob(job.id, t0, { startedHere: true });
  } catch (e) {
    status.className = "status err";
    status.dataset.stage = "";
    status.textContent = explainErr(e);
    result.className = "result fail show";
    result.innerHTML = "<h2>" + tx("result.failHead") + "</h2><p class='result-note'>" + explainErr(e) + "</p>";
    revealResult();
  } finally {
    clearInterval(tick);
    submitting = false;
    currentJob = null;
    runPaused = false;
    setRunButtons(false, false, false);
    go.disabled = !(chosen && llmOk && loggedIn);
    loadJobs();
  }
});

async function sendControl(action) {
  if (!currentJob) return;
  const res = await fetch(apiUrl("/api/jobs/" + currentJob + "/" + action), {
    method: "POST",
    credentials: "same-origin",
    headers: authHeaders(),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || tx("err.op"));
  return data;
}
pauseBtn.addEventListener("click", async () => {
  if (!currentJob) return;
  pauseBtn.disabled = true;
  try {
    if (runPaused) {
      await sendControl("resume");
      runPaused = false;
      pauseBtn.textContent = tx("pause");
    } else {
      await sendControl("pause");
      runPaused = true;
      pauseBtn.textContent = tx("resume");
    }
  } catch (e) {
    status.className = "status err";
    status.textContent = explainErr(e);
  } finally {
    pauseBtn.disabled = !currentJob;
  }
});
stopBtn.addEventListener("click", async () => {
  if (!currentJob) return;
  pauseBtn.disabled = true;
  stopBtn.disabled = true;
  try {
    await sendControl("stop");
    paintJobStatus(tx("status.ending"));
  } catch (e) {
    status.className = "status err";
    status.textContent = explainErr(e);
    pauseBtn.disabled = !currentJob;
    stopBtn.disabled = !currentJob;
  }
});

document.body.classList.toggle("is-embed", embedMode());

// ===== 常规设置（外观 / 布局）：只存本机 localStorage，不进后端 =====
// 首屏套用在 index.html 的内联脚本里；这里负责对话框交互、持久化与「跟随系统」监听。
const PREFS_KEY = "electrical.prefs";
const PREF_DEFAULTS = {
  theme: "system",
  accent: "blue",
  zoom: "100",
  font: "system",
  contrast: "normal",
  motion: "system",
  density: "cozy",
  rail: "left",
  lang: "zh",
  // 出表：默认模型（空 = 用服务端默认）、完成后自动打开。模型推理不进设置，跟上游默认（开）
  model: "",
  autoOpen: "off",
  // 通用：记住邮箱、完成通知 / 提示音、出表中关窗确认
  rememberUser: "on",
  notify: "off",
  sound: "off",
  confirmClose: "on",
};
const PREF_ALLOWED = {
  theme: ["system", "light", "dark"],
  accent: ["blue", "teal", "green", "purple", "orange", "rose", "slate"],
  zoom: ["80", "90", "100", "110", "125", "150"],
  font: ["system", "yahei", "songti", "mono"],
  contrast: ["normal", "high"],
  motion: ["system", "on", "off"],
  density: ["cozy", "compact"],
  rail: ["left", "right"],
  lang: ["zh", "en"],
  autoOpen: ["off", "on"],
  rememberUser: ["off", "on"],
  notify: ["off", "on"],
  sound: ["off", "on"],
  confirmClose: ["off", "on"],
};
// 挂到 <html> 的只有外观 / 布局；出表偏好走请求参数
const PREF_ATTRS = ["theme", "accent", "zoom", "font", "contrast", "motion", "density", "rail"];

function validModelName(v) {
  return typeof v === "string" && v.length > 0 && v.length <= 80 && !/\s/.test(v);
}
const darkQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
const motionQuery = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;

function motionAttr(v) {
  if (v === "system") return motionQuery && motionQuery.matches ? "reduce" : "full";
  return v === "on" ? "reduce" : "full";
}

function motionReduced() {
  return motionAttr(prefs.motion) === "reduce";
}

function themeFromQuery() {
  const t = readQuery().get("theme");
  return PREF_ALLOWED.theme.includes(t) ? t : "";
}

function loadPrefs() {
  let raw = {};
  try {
    raw = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") || {};
  } catch (_) {
    raw = {};
  }
  const out = {};
  Object.keys(PREF_DEFAULTS).forEach((k) => {
    if (k === "model") out[k] = validModelName(raw[k]) ? raw[k] : "";
    else out[k] = PREF_ALLOWED[k].includes(raw[k]) ? raw[k] : PREF_DEFAULTS[k];
  });
  // 父壳可用 ?theme= / ?lang= 指定（不落盘）
  const forced = themeFromQuery();
  if (forced) out.theme = forced;
  const forcedLang = typeof window.langFromQuery === "function" ? window.langFromQuery() : "";
  if (forcedLang) out.lang = forcedLang;
  return out;
}

function savePrefs(prefs) {
  const toStore = Object.assign({}, prefs);
  if (themeFromQuery()) delete toStore.theme;
  if (typeof window.langFromQuery === "function" && window.langFromQuery()) delete toStore.lang;
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(toStore));
  } catch (_) {
    /* 隐私模式等写不进去就只在本次会话生效 */
  }
}

function applyPrefs(prefs) {
  const h = document.documentElement;
  PREF_ATTRS.forEach((k) => {
    let v = prefs[k];
    if (k === "theme" && v === "system") v = darkQuery && darkQuery.matches ? "dark" : "light";
    if (k === "motion") v = motionAttr(v);
    h.setAttribute("data-" + k, v);
  });
  const lang = (typeof window.langFromQuery === "function" && window.langFromQuery()) || prefs.lang || "zh";
  h.setAttribute("data-lang", lang);
  h.lang = lang === "en" ? "en" : "zh-CN";
}

function applyHealthText() {
  const el = $("health-text");
  if (!el || !lastHealth) return;
  const h = lastHealth;
  let ready = tx("health.needLogin");
  if (h.logged_in) ready = tx("health.ready");
  if (h.busy) ready = tx("health.busy");
  el.textContent = h.ok ? ready : (h.detail || tx("health.down"));
  applyEnvLock();
}

function jobIsRunning() {
  return !!(currentJob || (lastHealth && lastHealth.busy));
}

function applyEnvLock() {
  const locked = jobIsRunning();
  const box = $("env-choices");
  const warn = $("env-busy");
  const packLocked = !!(box && box.classList.contains("is-pack-locked"));
  if (box) {
    box.classList.toggle("is-locked", locked || packLocked);
    box.querySelectorAll("button.env-choice").forEach((btn) => {
      btn.disabled = locked || packLocked;
    });
  }
  if (warn) {
    warn.hidden = !locked;
    warn.textContent = tx("env.busy");
  }
}

function applyDesktopTitle() {
  const title = tx("brand.agent");
  document.title = title;
  try {
    const api = window.pywebview && window.pywebview.api;
    if (api && typeof api.set_title === "function") {
      Promise.resolve(api.set_title(title)).catch(() => {});
    }
  } catch (_) { /* 非桌面窗口无需同步原生标题 */ }
}

function applyUiLang() {
  if (typeof window.applyStaticI18n === "function") window.applyStaticI18n();
  applyDesktopTitle();
  applyShellCopy();
  applyWorkPanel();
  applyHealthText();
  if (lastHealth) applyEnvLabels(lastHealth);
  const sel = $("model");
  if (sel) {
    const names = Array.from(sel.options).map((o) => o.value).filter(Boolean);
    fillModels(names, sel.value);
  }
  renderPrefControls();
  renderJobs();
  pick.textContent = chosen ? tx("pick.change") : tx("pick");
  if (currentJob) pauseBtn.textContent = runPaused ? tx("resume") : tx("pause");
  else pauseBtn.textContent = tx("pause");
  const pass = $("pass");
  const pbtn = $("pass-toggle");
  if (pass && pbtn) {
    const show = pass.type !== "password";
    pbtn.setAttribute("aria-label", show ? tx("login.hidePass") : tx("login.showPass"));
    pbtn.title = show ? tx("login.hidePass") : tx("login.showPass");
  }
  if (chosen && !extractBusy()) inspectChosen(chosen);
  if (lastShownJob && result.classList.contains("show") && !result.classList.contains("fail")) {
    showFinishedJob(lastShownJob);
  }
  if (typeof window.kbRerender === "function") window.kbRerender();
  applyEnvLock();
  if (status.dataset.stage) {
    const parts = String(status.textContent || "").split("  ·  ");
    const elapsed = parts.length > 1 ? parts.slice(1).join("  ·  ") : "";
    const msg = jobMessageText(status.dataset.stage) || tx("status.extracting");
    status.textContent = elapsed ? msg + "  ·  " + elapsed : msg;
  }
}

window.addEventListener("pywebviewready", applyDesktopTitle);

let prefs = loadPrefs();
applyPrefs(prefs);
prefillLoginUser();
if (darkQuery) {
  const onScheme = () => {
    if (prefs.theme === "system") applyPrefs(prefs);
  };
  if (typeof darkQuery.addEventListener === "function") darkQuery.addEventListener("change", onScheme);
  else if (typeof darkQuery.addListener === "function") darkQuery.addListener(onScheme);
}
if (motionQuery) {
  const onMotion = () => {
    if (prefs.motion === "system") applyPrefs(prefs);
  };
  if (typeof motionQuery.addEventListener === "function") motionQuery.addEventListener("change", onMotion);
  else if (typeof motionQuery.addListener === "function") motionQuery.addListener(onMotion);
}

function setPref(key, value) {
  if (key === "model") {
    if (value !== "" && !validModelName(value)) return;
  } else if (!PREF_ALLOWED[key] || !PREF_ALLOWED[key].includes(value)) {
    return;
  }
  prefs = Object.assign({}, prefs, { [key]: value });
  savePrefs(prefs);
  applyPrefs(prefs);
  renderPrefControls();
  if (key === "lang") applyUiLang();
  if (key === "notify" && value === "on") askNotifyPermission();
  if (key === "rememberUser" && value === "off") rememberLoginUser("");
}

// ===== 通用：记住邮箱 / 完成提醒 / 关窗确认 =====
const LAST_USER_KEY = "electrical.lastUser";

function rememberLoginUser(email) {
  try {
    if (prefs.rememberUser === "on" && email) localStorage.setItem(LAST_USER_KEY, String(email).trim());
    else localStorage.removeItem(LAST_USER_KEY);
  } catch (_) { /* 写不进去就不记 */ }
}

function prefillLoginUser() {
  const input = $("user");
  if (!input || input.value || prefs.rememberUser !== "on") return;
  try {
    input.value = localStorage.getItem(LAST_USER_KEY) || "";
  } catch (_) { /* ignore */ }
}

function askNotifyPermission() {
  const msg = $("settings-msg");
  const say = (text, info) => {
    if (!msg) return;
    msg.hidden = false;
    msg.classList.toggle("is-info", !!info);
    msg.textContent = text;
  };
  if (!("Notification" in window)) {
    say(tx("notify.unsupported"));
    return;
  }
  if (Notification.permission === "granted") return;
  if (Notification.permission === "denied") {
    say(tx("notify.denied"));
    return;
  }
  Notification.requestPermission().then((p) => {
    if (p !== "granted") say(tx("notify.notGranted"));
    else say(tx("notify.ok"), true);
  }).catch(() => {});
}

function playDoneSound() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const now = ctx.currentTime;
    [[880, 0], [1174.66, 0.16]].forEach(([freq, at]) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, now + at);
      gain.gain.exponentialRampToValueAtTime(0.18, now + at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + at + 0.22);
      osc.connect(gain).connect(ctx.destination);
      osc.start(now + at);
      osc.stop(now + at + 0.25);
    });
    setTimeout(() => ctx.close().catch(() => {}), 800);
  } catch (_) { /* 无音频设备等 */ }
}

// 出表完成 / 失败提醒：只对本页发起的任务；系统通知只在窗口不在前台时弹
function finishAlert(title, body) {
  if (prefs.sound === "on") playDoneSound();
  if (prefs.notify !== "on" || !("Notification" in window)) return;
  if (Notification.permission !== "granted") return;
  if (document.hasFocus() && document.visibilityState === "visible") return;
  try {
    const n = new Notification(title, { body: String(body || ""), tag: "electrical-krow-job" });
    n.onclick = () => { window.focus(); n.close(); };
  } catch (_) { /* ignore */ }
}

window.addEventListener("beforeunload", (ev) => {
  if (prefs.confirmClose !== "on" || !currentJob || embedMode()) return;
  ev.preventDefault();
  ev.returnValue = "";
});

function renderPrefControls() {
  const modelSel = $("pref-model");
  if (modelSel) {
    // 只列服务端返回的模型；未登录时只显示提示
    const names = Array.from($("model")?.options || []).map((o) => o.value).filter(Boolean);
    modelSel.innerHTML = "";
    const head = document.createElement("option");
    head.value = "";
    head.textContent = names.length ? tx("pref.model.serverDefault") : tx("pref.model.afterLogin");
    modelSel.appendChild(head);
    names.forEach((n) => {
      const opt = document.createElement("option");
      opt.value = n;
      opt.textContent = modelLabel(n);
      modelSel.appendChild(opt);
    });
    if (prefs.model && !names.includes(prefs.model)) {
      const opt = document.createElement("option");
      opt.value = prefs.model;
      opt.textContent = prefs.model + tx("pref.model.missing");
      modelSel.appendChild(opt);
    }
    modelSel.value = prefs.model || "";
    modelSel.disabled = !names.length && !prefs.model;
  }
  document.querySelectorAll("[data-pref]").forEach((group) => {
    const key = group.getAttribute("data-pref");
    group.querySelectorAll("button[data-value]").forEach((btn) => {
      const on = btn.getAttribute("data-value") === prefs[key];
      btn.classList.toggle("is-on", on);
      btn.setAttribute("aria-checked", on ? "true" : "false");
      btn.setAttribute("role", "radio");
    });
  });
}

document.querySelectorAll("[data-pref]").forEach((group) => {
  const key = group.getAttribute("data-pref");
  group.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-value]");
    if (btn) setPref(key, btn.getAttribute("data-value"));
  });
});

$("pref-model")?.addEventListener("change", async () => {
  const name = $("pref-model").value;
  setPref("model", name);
  if (name && loggedIn) await applyDefaultModel();
});

// 登录后把默认模型套到会话上；表单里选了别的也记成新的默认
async function applyDefaultModel() {
  const sel = $("model");
  if (!sel || !prefs.model) return;
  const names = Array.from(sel.options).map((o) => o.value);
  if (!names.includes(prefs.model) || sel.value === prefs.model) return;
  try {
    await json("/api/model", { method: "POST", body: JSON.stringify({ model: prefs.model }) });
    sel.value = prefs.model;
  } catch (_) {
    /* 服务端拒了就保持当前会话模型 */
  }
}

$("settings-reset")?.addEventListener("click", () => {
  // 只恢复外观 / 布局；出表偏好保留
  const keep = {};
  ["model", "autoOpen", "rememberUser", "notify", "sound", "confirmClose"].forEach((k) => { keep[k] = prefs[k]; });
  prefs = Object.assign({}, PREF_DEFAULTS, keep);
  const forced = themeFromQuery();
  if (forced) prefs.theme = forced;
  const forcedLang = typeof window.langFromQuery === "function" ? window.langFromQuery() : "";
  if (forcedLang) prefs.lang = forcedLang;
  savePrefs(prefs);
  applyPrefs(prefs);
  renderPrefControls();
  applyUiLang();
});

function showSettingsTab(name) {
  document.querySelectorAll(".settings-tab").forEach((t) => {
    t.classList.toggle("is-on", t.getAttribute("data-tab") === name);
  });
  document.querySelectorAll(".settings-panel").forEach((p) => {
    p.hidden = p.getAttribute("data-panel") !== name;
  });
  const msg = $("settings-msg");
  if (msg) msg.hidden = true;
  if (name === "env") loadEnvironments();
  if (name === "about") loadAbout();
}

async function loadAbout() {
  const list = $("about-list");
  if (!list) return;
  const put = (key, val) => {
    const el = list.querySelector('[data-about="' + key + '"]');
    if (el) el.textContent = val || "—";
  };
  try {
    const h = await json("/api/health");
    const v = h.versions || {};
    put("client", v.client);
    put("sdk", v.sdk);
    put("runtime", v.runtime);
    put("knowledge", v.knowledge);
    put("server", (envCaption(h) ? envCaption(h) + "  " : "") + (h.server || ""));
    put("model", prefs.model || h.model);
    put("output_dir", h.output_dir);
    put("platform", [v.platform, v.python ? "Python " + v.python : ""].filter(Boolean).join("  ·  "));
  } catch (err) {
    put("server", String(err.message || err));
  }
}

$("about-open-output")?.addEventListener("click", async () => {
  const msg = $("settings-msg");
  try {
    await json("/api/output/open", { method: "POST" });
  } catch (err) {
    if (msg) { msg.hidden = false; msg.classList.remove("is-info"); msg.textContent = String(err.message || err); }
  }
});

$("about-copy")?.addEventListener("click", async () => {
  const rows = Array.from($("about-list")?.querySelectorAll("dt") || []);
  const sep = (typeof window.uiLang === "function" && window.uiLang() === "en") ? ": " : "：";
  const text = rows.map((dt) => dt.textContent + sep + (dt.nextElementSibling?.textContent || "")).join("\n");
  const msg = $("settings-msg");
  try {
    await navigator.clipboard.writeText(text);
    if (msg) { msg.hidden = false; msg.classList.add("is-info"); msg.textContent = tx("about.copied"); }
  } catch (_) {
    if (msg) { msg.hidden = false; msg.textContent = text; }
  }
});

document.querySelectorAll(".settings-tab").forEach((tab) => {
  tab.addEventListener("click", () => showSettingsTab(tab.getAttribute("data-tab")));
});

async function openSettings(tab) {
  const dlg = $("settings-dialog");
  if (!dlg) return;
  const msg = $("settings-msg");
  if (msg) {
    msg.hidden = true;
    msg.textContent = "";
  }
  renderPrefControls();
  showSettingsTab(tab || "appearance");
  if (typeof dlg.showModal === "function") dlg.showModal();
  else dlg.setAttribute("open", "");
}

async function loadEnvironments() {
  const box = $("env-choices");
  const msg = $("settings-msg");
  if (!box) return;
  box.innerHTML = "<p>" + tx("env.loading") + "</p>";
  try {
    const data = await json("/api/settings");
    try {
      lastHealth = await json("/api/health");
    } catch (_) { /* 锁态仍按已有 lastHealth / currentJob */ }
    box.innerHTML = "";
    const locked = !!data.environment_locked || (data.environments || []).length <= 1;
    box.classList.toggle("is-pack-locked", locked);
    (data.environments || []).forEach((env) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "env-choice" + (env.id === data.id ? " is-on" : "");
      btn.innerHTML = "<strong>" + escText(environmentLabel(env.id, env.label)) + "</strong><span>"
        + escText(env.server) + "</span>";
      if (locked) btn.disabled = true;
      else btn.addEventListener("click", () => pickEnvironment(env.id));
      box.appendChild(btn);
    });
    const note = $("env-note");
    if (note) note.setAttribute("data-i18n", locked ? "env.locked" : "env.note");
    if (note) note.textContent = tx(locked ? "env.locked" : "env.note");
    applyEnvLock();
  } catch (err) {
    box.innerHTML = "";
    msg.hidden = false;
    msg.textContent = String(err.message || err);
    applyEnvLock();
  }
}

async function pickEnvironment(id) {
  const msg = $("settings-msg");
  msg.hidden = true;
  if (jobIsRunning()) {
    applyEnvLock();
    return;
  }
  try {
    const data = await json("/api/settings", {
      method: "POST",
      body: JSON.stringify({ id }),
    });
    const dlg = $("settings-dialog");
    if (dlg) dlg.close();
    if (data.changed) {
      setFile(null);
      if (fileInput) fileInput.value = "";
      workPanel = "home";
      viewingJob = null;
      jobRows = [];
      renderJobs();
      await showWork(false, "");
    }
    await refresh();
  } catch (err) {
    msg.hidden = false;
    msg.textContent = String(err.message || err);
  }
}

document.querySelectorAll(".js-open-settings").forEach((btn) => {
  // 挨着「识别环境」的设置按钮直接落到环境页，其余进外观页
  const tab = btn.getAttribute("data-tab") || (btn.closest(".env-row") ? "env" : "");
  btn.addEventListener("click", () => openSettings(tab || undefined));
});
const settingsDialog = $("settings-dialog");
if (settingsDialog) {
  settingsDialog.addEventListener("click", (ev) => {
    if (ev.target === settingsDialog) settingsDialog.close();
  });
}

applyUiLang();
refresh();
