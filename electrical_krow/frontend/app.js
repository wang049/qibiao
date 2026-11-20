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
  const icd = on && workPanel === "icd";
  const bom = on && workPanel === "bom";
  const etest = on && workPanel === "etest";
  const arch = on && workPanel === "arch";
  $("home-card").hidden = !home;
  $("work-card").hidden = !extract;
  $("kb-card").hidden = !kb;
  $("io-card").hidden = !io;
  $("icd-card").hidden = !icd;
  $("bom-card").hidden = !bom;
  $("etest-card").hidden = !etest;
  $("arch-card").hidden = !arch;
  document.body.classList.toggle("is-logged", on);
  document.body.classList.toggle("is-home", home);
  document.body.classList.toggle("is-kb", kb);
  document.querySelector("main")?.classList.toggle("is-work", on);
  document.querySelector("main")?.classList.toggle("is-kb", kb);
  $("rail-home")?.classList.toggle("is-on", home);
  $("rail-extract")?.classList.toggle("is-on", extract);
  $("rail-io")?.classList.toggle("is-on", io);
  $("rail-icd")?.classList.toggle("is-on", icd);
  $("rail-bom")?.classList.toggle("is-on", bom);
  $("rail-etest")?.classList.toggle("is-on", etest);
  $("rail-arch")?.classList.toggle("is-on", arch);
  $("rail-kb")?.classList.toggle("is-on", kb);
  if (io) setRailRecordTab("hsi");
  else if (icd) setRailRecordTab("icd");
  else if (bom) setRailRecordTab("bom");
  else if (etest) setRailRecordTab("etest");
  else if (arch) setRailRecordTab("arch");
  else if (extract) setRailRecordTab("jobs");
  // 知识库页的口径只在页内蓝条说一次，标题下不再放副标题
  $("lead").hidden = Boolean(on && kb);
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
  if (icd) {
    $("kicker").textContent = tx("hero.icd.kicker");
    $("title").innerHTML = tx("hero.icd.title");
    $("lead").textContent = tx("hero.icd.lead");
    return;
  }
  if (bom) {
    $("kicker").textContent = tx("hero.bom.kicker");
    $("title").innerHTML = tx("hero.bom.title");
    $("lead").textContent = tx("hero.bom.lead");
    return;
  }
  if (etest) {
    $("kicker").textContent = tx("hero.etest.kicker");
    $("title").innerHTML = tx("hero.etest.title");
    $("lead").textContent = tx("hero.etest.lead");
    return;
  }
  if (arch) {
    $("kicker").textContent = tx("hero.arch.kicker");
    $("title").innerHTML = tx("hero.arch.title");
    $("lead").textContent = tx("hero.arch.lead");
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
  const lang = typeof window.uiLang === "function" && window.uiLang() === "en" ? "en-US" : "zh-CN";
  const clock = d.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
  const today = new Date();
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const todayDay = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  if (day === todayDay) return tx("record.today", { t: clock });
  if (day === todayDay - 86400000) return tx("record.yesterday", { t: clock });
  const date = d.toLocaleDateString(lang, { month: "numeric", day: "numeric" });
  return date + " " + clock;
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

function recordTitle(name) {
  const base = String(name || "").replace(/\.(pdf|xlsx|xlsm|xls|edf|docx)$/i, "");
  const hsi = base.match(/^HSI-(.*?)(?:-\d{8}(?:-\d{6})?)?$/i);
  if (hsi) {
    const title = hsi[1].replace(/^-+/, "").replace(/-+$/, "");
    return title || "HSI";
  }
  const icd = base.match(/^ICD引脚清单-(.+)$/);
  if (icd) return icd[1].replace(/-/g, " ");
  const bom = base.match(/^CEBOM-(.+)$/);
  if (bom) return bom[1].replace(/-/g, " ");
  return base || String(name || "");
}

function recordInner(kindLabel, title, metaHtml) {
  return "<span class='job-copy'>"
    + "<span class='job-kind'>" + escText(kindLabel) + "</span>"
    + "<span class='job-name'>" + escText(title) + "</span>"
    + (metaHtml || "")
    + "</span>";
}

const EMPTY_JOBS_SVG = "<svg viewBox='0 0 64 48' width='64' height='48' fill='none' aria-hidden='true'>"
  + "<rect x='8' y='6' width='34' height='38' rx='3' stroke='currentColor' stroke-width='1.5'/>"
  + "<path d='M15 16h20M15 23h20M15 30h12' stroke='currentColor' stroke-width='1.5' stroke-linecap='round'/>"
  + "<circle cx='48' cy='34' r='9' fill='var(--surface)' stroke='currentColor' stroke-width='1.5'/>"
  + "<path d='M48 30v8M44 34h8' stroke='currentColor' stroke-width='1.5' stroke-linecap='round'/></svg>";

let hsiRows = [];
let jobSources = [];
let hsiSources = [];
let archSources = [];
let recordFolders = { jobs: [], hsi: [], arch: [], icd: [], bom: [], etest: [] };
let icdRows = [];
let bomRows = [];
let etestRows = [];
let icdSources = [];
let bomSources = [];
let etestSources = [];
let recordNote = null;
let recordOpen = {};
let recordDraft = null;
let recordQuery = { jobs: "", hsi: "", arch: "", icd: "", bom: "" };

function renderByKind(kind) {
  if (kind === "hsi") renderHsi();
  else if (kind === "arch") renderArch();
  else if (kind === "icd") renderSheetRecords("icd");
  else if (kind === "bom") renderSheetRecords("bom");
  else if (kind === "etest") renderSheetRecords("etest");
  else renderJobs();
}

function recordListId(kind) {
  return { hsi: "hsi-list", arch: "arch-list", icd: "icd-list", bom: "bom-list", etest: "etest-list" }[kind] || "job-list";
}

function recordFolderTitle(row, kind) {
  const grouped = String((row && row.group_title) || "").trim();
  if (grouped) return grouped;
  if (kind === "hsi") {
    const chip = [row.mcu, row.package].filter(Boolean).join(" ");
    if (chip) return chip;
    const name = fileNameOf(row.download) || String(row.source || "");
    return recordTitle(name);
  }
  if (kind === "arch") return recordTitle(fileNameOf(row.download) || row.source || "");
  return String(row.source || tx("spec"));
}

function recordAutoKey(row, kind) {
  return "auto:" + recordFolderTitle(row, kind).trim().toLowerCase();
}

function recordFileKey(row) {
  const raw = String((row && row.source) || "").trim() || fileNameOf(row && row.download);
  const base = raw.split(/[/\\]/).pop() || raw;
  return base.trim().toLowerCase();
}

function betterRecord(row, prev, active) {
  const id = String(row.id || "");
  const prevId = String(prev.id || "");
  if (active && id === active && prevId !== active) return true;
  if (active && prevId === active && id !== active) return false;
  const newer = Number(row.created_at || 0) - Number(prev.created_at || 0);
  if (newer) return newer > 0;
  const rowOut = row.role !== "source";
  const prevOut = prev.role !== "source";
  if (rowOut !== prevOut) return rowOut;
  return row.status === "done" && prev.status !== "done";
}

function collapseSameFiles(rows) {
  const active = String(viewingJob || currentJob || "");
  const best = new Map();
  rows.forEach((row) => {
    const key = recordFileKey(row);
    if (!key) return;
    const prev = best.get(key);
    if (!prev || betterRecord(row, prev, active)) best.set(key, row);
  });
  return rows.filter((row) => {
    const key = recordFileKey(row);
    return !key || best.get(key) === row;
  });
}

function layoutRecords(rows, kind) {
  const folders = recordFolders[kind] || [];
  const known = new Set(folders.map((folder) => folder.id));
  const placed = new Map();
  rows.forEach((row) => {
    const fid = String(row.folder_id || "");
    if (!fid || !known.has(fid)) return;
    if (!placed.has(fid)) placed.set(fid, []);
    placed.get(fid).push(row);
  });
  const autoCount = new Map();
  rows.forEach((row) => {
    const fid = String(row.folder_id || "");
    if (fid && known.has(fid)) return;
    const key = recordAutoKey(row, kind);
    autoCount.set(key, (autoCount.get(key) || 0) + 1);
  });
  const blocks = [];
  const seenUser = new Set();
  const seenAuto = new Set();
  folders.forEach((folder) => {
    if ((placed.get(folder.id) || []).length) return;
    seenUser.add(folder.id);
    blocks.push({ type: "user", id: folder.id, title: folder.name, rows: [] });
  });
  rows.forEach((row) => {
    const fid = String(row.folder_id || "");
    if (fid && known.has(fid)) {
      if (seenUser.has(fid)) return;
      seenUser.add(fid);
      const folder = folders.find((item) => item.id === fid);
      blocks.push({ type: "user", id: fid, title: folder ? folder.name : fid, rows: placed.get(fid) || [] });
      return;
    }
    const key = recordAutoKey(row, kind);
    if ((autoCount.get(key) || 0) >= 2) {
      if (seenAuto.has(key)) return;
      seenAuto.add(key);
      const group = rows.filter((item) => {
        const id = String(item.folder_id || "");
        return !(id && known.has(id)) && recordAutoKey(item, kind) === key;
      });
      blocks.push({ type: "auto", id: key, title: recordFolderTitle(group[0], kind), rows: group });
      return;
    }
    blocks.push({ type: "single", row });
  });
  return blocks;
}

function recordQueryOf(kind) {
  return String(recordQuery[kind] || "");
}

function recordHaystack(row, kind) {
  const status = String((row && row.status) || "");
  const statusWord = status === "error" ? "失败 fail" : status === "done" ? "完成 done" : status === "running" ? "进行中 running" : status;
  return [
    row && row.source,
    row && row.download,
    row && row.mcu,
    row && row.package,
    row && row.group_title,
    row && row.detail,
    row && row.message,
    statusWord,
    recordFolderTitle(row || {}, kind),
    fileNameOf(row && row.download),
  ].filter(Boolean).join(" ").toLowerCase();
}

function folderIsOpen(kind, id, rows) {
  if (recordQueryOf(kind).trim()) return true;
  const key = kind + ":" + id;
  if (Object.prototype.hasOwnProperty.call(recordOpen, key)) return !!recordOpen[key];
  const active = viewingJob || currentJob || "";
  return kind === "jobs" && rows.some((row) => String(row.id || "") === active);
}

function sourceAccept(kind) {
  if (kind === "hsi") return ".pdf,.edf,application/pdf";
  if (kind === "arch") return ".pdf,application/pdf";
  if (kind === "bom") return ".pdf,.xlsx,.xlsm,.docx,.edf";
  if (kind === "icd") return ".xlsx,.xlsm,.pdf";
  return ".pdf,.docx,.xlsx,.xlsm,application/pdf";
}

function recordCard(kind, row, openAttr, openValue, title, inner) {
  const id = String(row.id || "");
  const on = kind === "jobs" && id && id === (viewingJob || currentJob || "");
  const block = kind === "jobs" && !!currentJob && id !== currentJob;
  const move = id && !block
    ? "<button type='button' class='job-move' data-kind='" + escText(kind) + "' data-move='" + escText(id) + "'>" + tx("record.move") + "</button>"
    : "";
  return "<div class='job-row" + (on ? " is-on" : "") + "'>"
    + "<button type='button' class='job-open' " + openAttr + "='" + escText(openValue) + "' title='" + escText(title) + "'"
    + (block ? " disabled" : "") + ">" + inner + "</button>"
    + move + "</div>";
}

function mergedRecords(outputs, sources) {
  return outputs.concat(sources).sort((a, b) => Number(b.created_at || 0) - Number(a.created_at || 0));
}

function sourceKindLabel(kind) {
  if (kind === "hsi") return tx("record.kind.net");
  if (kind === "arch") return tx("record.kind.req");
  if (kind === "icd") return tx("record.kind.icdIn");
  if (kind === "bom") return tx("record.kind.manual");
  return tx("record.kind.spec");
}

function sourceCard(kind, row) {
  const name = String(row.source || "");
  const when = fmtWhen(row.created_at);
  const meta = "<span class='job-meta'><span class='job-meta-text'>" + escText(when) + "</span></span>";
  return recordCard(kind, row, "data-source", row.id || "", name, recordInner(sourceKindLabel(kind), name, meta));
}

function recordToolbar(kind) {
  const note = recordNote && recordNote.kind === kind
    ? "<p class='job-folder-error'>" + escText(recordNote.text) + "</p>" : "";
  if (recordDraft && recordDraft.kind === kind) {
    return "<form class='job-folder-form' data-kind='" + escText(kind) + "'>"
      + "<input name='folder' maxlength='40' placeholder='" + escText(tx("record.folderName")) + "' value='" + escText(recordDraft.name || "") + "' />"
      + "<button type='submit'>" + tx("record.create") + "</button>"
      + "<button type='button' data-cancel='1'>" + tx("record.cancel") + "</button>"
      + (recordDraft.error ? "<p class='job-folder-error'>" + escText(recordDraft.error) + "</p>" : "")
      + "</form>";
  }
  const query = recordQueryOf(kind);
  return "<div class='job-folder-bar'>"
    + "<input class='job-search' type='search' value='" + escText(query) + "' placeholder='" + escText(tx("record.search")) + "' aria-label='" + escText(tx("record.search")) + "' />"
    + "<button type='button' class='job-new-folder' data-kind='" + escText(kind) + "'>" + tx("record.newFolder") + "</button>"
    + "<button type='button' class='job-add-source' data-kind='" + escText(kind) + "'>" + tx("record.addSource") + "</button>"
    + "<input class='job-source-input' type='file' hidden accept='" + sourceAccept(kind) + "' />"
    + "</div>" + note;
}

function fillRecordHost(host, kind, rows, cardHtml, onEmpty) {
  const query = recordQueryOf(kind).trim().toLowerCase();
  const unique = collapseSameFiles(rows);
  const shown = query ? unique.filter((row) => recordHaystack(row, kind).includes(query)) : unique;
  const folders = recordFolders[kind] || [];
  const scroll = host.scrollTop;
  const typing = document.activeElement && host.contains(document.activeElement)
    && document.activeElement.classList.contains("job-search");
  const caret = typing ? document.activeElement.selectionStart : null;
  let html = recordToolbar(kind);
  if (!rows.length && !folders.length) {
    host.innerHTML = html + onEmpty();
    bindRecordChrome(host, kind);
    return;
  }
  let blocks = layoutRecords(shown, kind);
  if (query) {
    blocks = blocks.filter((block) => {
      if (block.type === "single") return true;
      if ((block.rows || []).length) return true;
      return String(block.title || "").toLowerCase().includes(query);
    });
  }
  if (!blocks.length) {
    html += "<p class='job-empty'>" + tx("record.noMatch") + "</p>";
  } else if (query) {
    html += "<p class='job-search-count'>" + tx("record.foundN", { n: shown.length, total: unique.length }) + "</p>";
  }
  html += blocks.map((block) => {
    if (block.type === "single") return cardHtml(block.row);
    const open = folderIsOpen(kind, block.id, block.rows);
    const latest = (block.rows || []).reduce((max, row) => Math.max(max, Number(row.created_at || 0)), 0);
    const when = fmtWhen(latest);
    const body = block.rows.length
      ? block.rows.map(cardHtml).join("")
      : "<p class='job-folder-empty'>" + tx("record.folderEmpty") + "</p>";
    return "<section class='job-folder" + (open ? " is-open" : "") + "'>"
      + "<button type='button' class='job-folder-head' data-folder='" + escText(kind + ":" + block.id) + "'>"
      + "<span class='job-folder-chev' aria-hidden='true'></span>"
      + "<span class='job-folder-name'>" + escText(block.title) + "</span>"
      + (when ? "<span class='job-folder-when'>" + escText(when) + "</span>" : "")
      + "<span class='job-folder-count'>" + block.rows.length + "</span>"
      + "</button><div class='job-folder-body'>" + body + "</div></section>";
  }).join("");
  host.innerHTML = html;
  bindRecordChrome(host, kind);
  if (typing) {
    const input = host.querySelector(".job-search");
    if (input) {
      input.focus();
      if (caret != null) input.setSelectionRange(caret, caret);
    }
  }
  host.scrollTop = scroll;
}

function bindRecordChrome(host, kind) {
  host.querySelectorAll(".job-search").forEach((input) => {
    input.addEventListener("input", () => {
      recordQuery[kind] = input.value;
      renderByKind(kind);
    });
  });
  host.querySelectorAll(".job-new-folder").forEach((btn) => {
    btn.addEventListener("click", () => {
      recordDraft = { kind, recordId: "", name: "", error: "" };
      renderByKind(kind);
      const input = host.querySelector(".job-folder-form input");
      if (input) input.focus();
    });
  });
  host.querySelectorAll(".job-folder-form").forEach((form) => {
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const input = form.querySelector("input");
      const name = input ? input.value : "";
      const draft = recordDraft || { kind, recordId: "" };
      recordDraft = { kind: draft.kind, recordId: draft.recordId, name, error: "" };
      try {
        const made = await json("/api/records/folders", {
          method: "POST",
          body: JSON.stringify({ kind, name }),
        });
        const folder = made.folder || {};
        if (draft.recordId && folder.id) {
          await json("/api/records/place", {
            method: "POST",
            body: JSON.stringify({ kind, record_id: draft.recordId, folder_id: folder.id }),
          });
        }
        recordOpen[kind + ":" + folder.id] = true;
        recordDraft = null;
        await loadJobs();
      } catch (err) {
        recordDraft = { kind, recordId: draft.recordId, name, error: err.message || String(err) };
        renderByKind(kind);
      }
    });
    const cancel = form.querySelector("[data-cancel]");
    if (cancel) {
      cancel.addEventListener("click", () => {
        recordDraft = null;
        renderByKind(kind);
      });
    }
  });
  host.querySelectorAll(".job-folder-head").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-folder") || "";
      recordOpen[key] = !folderHeadOpen(btn);
      renderByKind(kind);
    });
  });
  host.querySelectorAll(".job-move").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openRecordMenu(btn, kind, btn.getAttribute("data-move") || "");
    });
  });
  host.querySelectorAll(".job-add-source").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = host.querySelector(".job-source-input");
      if (!input) return;
      input._anchor = btn;
      input.click();
    });
  });
  host.querySelectorAll(".job-source-input").forEach((input) => {
    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      input.value = "";
      if (!file) return;
      const folders = recordFolders[kind] || [];
      if (!folders.length) {
        uploadSource(kind, file, "");
        return;
      }
      openFolderPick(input._anchor || input, kind, (folderId) => uploadSource(kind, file, folderId));
    });
  });
  host.querySelectorAll("[data-source]").forEach((btn) => {
    btn.addEventListener("click", () => openSource(btn.getAttribute("data-source") || ""));
  });
}

async function uploadSource(kind, file, folderId) {
  const body = new FormData();
  body.append("kind", kind);
  body.append("folder_id", folderId || "");
  body.append("file", file);
  recordNote = null;
  try {
    const resp = await fetch(apiUrl("/api/records/sources"), {
      method: "POST",
      credentials: "same-origin",
      headers: authHeaders(),
      body,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const msg = data.detail || data.error || resp.statusText;
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    if (folderId) recordOpen[kind + ":" + folderId] = true;
    await loadJobs();
  } catch (err) {
    recordNote = { kind, text: err.message || String(err) };
    renderByKind(kind);
  }
}

async function openSource(id) {
  if (!id) return;
  try {
    await json("/api/records/sources/" + encodeURIComponent(id) + "/open", { method: "POST", body: "{}" });
  } catch (err) {
    window.location.href = apiUrl("/api/records/sources/" + encodeURIComponent(id) + "/file");
  }
}

function openFolderPick(anchor, kind, onPick) {
  const menu = recordMenuEl();
  const folders = recordFolders[kind] || [];
  let html = "<p class='record-menu-title'>" + tx("record.addSource") + "</p>";
  folders.forEach((folder) => {
    html += "<button type='button' data-pick='" + escText(folder.id) + "'>" + escText(folder.name) + "</button>";
  });
  html += "<button type='button' data-pick=''>" + tx("record.byFile") + "</button>";
  menu.innerHTML = html;
  menu.hidden = false;
  const box = anchor.getBoundingClientRect ? anchor.getBoundingClientRect() : { right: 200, bottom: 80, top: 40 };
  menu.style.left = Math.max(8, Math.min(box.right - 180, window.innerWidth - 188)) + "px";
  menu.style.top = (box.bottom + 4) + "px";
  menu.querySelectorAll("[data-pick]").forEach((btn) => {
    btn.addEventListener("click", () => {
      menu.hidden = true;
      onPick(btn.getAttribute("data-pick") || "");
    });
  });
}

function folderHeadOpen(btn) {
  const section = btn.closest(".job-folder");
  return !!(section && section.classList.contains("is-open"));
}

function recordRows(kind) {
  if (kind === "hsi") return hsiRows;
  if (kind === "arch") return archRows;
  if (kind === "icd") return icdRows;
  if (kind === "bom") return bomRows;
  return jobRows;
}

function recordById(kind, id) {
  return recordRows(kind).find((row) => String(row.id || "") === id) || null;
}

function recordMenuEl() {
  let menu = document.getElementById("record-menu");
  if (menu) return menu;
  menu = document.createElement("div");
  menu.id = "record-menu";
  menu.className = "record-menu";
  menu.hidden = true;
  document.body.appendChild(menu);
  document.addEventListener("click", (ev) => {
    if (menu.hidden) return;
    if (menu.contains(ev.target) || (ev.target.closest && ev.target.closest(".job-move, .io-file-box, #pick, #drop"))) return;
    menu.hidden = true;
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") menu.hidden = true;
  });
  return menu;
}

function openRecordMenu(anchor, kind, recordId) {
  const menu = recordMenuEl();
  const row = recordById(kind, recordId);
  const folders = recordFolders[kind] || [];
  let html = "<p class='record-menu-title'>" + tx("record.moveTo") + "</p>";
  if (!folders.length) html += "<p class='record-menu-empty'>" + tx("record.noFolders") + "</p>";
  folders.forEach((folder) => {
    const on = !!(row && row.folder_id === folder.id);
    html += "<button type='button' data-pick='" + escText(folder.id) + "'" + (on ? " disabled" : "") + ">"
      + escText(folder.name) + "</button>";
  });
  if (row && row.folder_id) {
    html += "<button type='button' data-pick=''>" + tx("record.byFile") + "</button>";
  }
  html += "<button type='button' data-new='1'>" + tx("record.newFolder") + "</button>";
  menu.innerHTML = html;
  menu.hidden = false;
  const box = anchor.getBoundingClientRect();
  const width = 180;
  let left = Math.min(box.right - width, window.innerWidth - width - 8);
  if (left < 8) left = 8;
  let top = box.bottom + 4;
  menu.style.left = left + "px";
  menu.style.top = top + "px";
  const height = menu.offsetHeight;
  if (top + height > window.innerHeight - 8) {
    menu.style.top = Math.max(8, box.top - height - 4) + "px";
  }
  menu.querySelectorAll("[data-pick]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      menu.hidden = true;
      try {
        await json("/api/records/place", {
          method: "POST",
          body: JSON.stringify({ kind, record_id: recordId, folder_id: btn.getAttribute("data-pick") || "" }),
        });
        const picked = btn.getAttribute("data-pick") || "";
        if (picked) recordOpen[kind + ":" + picked] = true;
        await loadJobs();
      } catch (err) {
        recordDraft = { kind, recordId: "", name: "", error: err.message || String(err) };
        renderByKind(kind);
      }
    });
  });
  const newer = menu.querySelector("[data-new]");
  if (newer) {
    newer.addEventListener("click", () => {
      menu.hidden = true;
      recordDraft = { kind, recordId, name: "", error: "" };
      renderByKind(kind);
      const input = document.querySelector("#" + recordListId(kind) + " .job-folder-form input");
      if (input) input.focus();
    });
  }
}

function renderHsi() {
  const host = $("hsi-list");
  if (!host) return;
  fillRecordHost(host, "hsi", mergedRecords(hsiRows, hsiSources), (row) => {
    if (row.role === "source") return sourceCard("hsi", row);
    const name = fileNameOf(row.download) || String(row.source || "");
    const titled = String(row.group_title || "").trim() || [row.mcu, row.package].filter(Boolean).join(" ");
    const bits = [];
    const when = fmtWhen(row.created_at);
    if (when) bits.push(when);
    const src = String(row.source || "");
    if (src && src !== titled && fileNameOf(src) !== fileNameOf(name)) bits.push(fileNameOf(src) || src);
    if (row.pins) bits.push(tx("io.pins", { n: row.pins }));
    const meta = "<span class='job-meta'><span class='job-meta-text'>" + escText(bits.join(" · ")) + "</span></span>";
    const inner = recordInner(tx("record.kind.hsi"), titled || recordTitle(name), meta);
    return recordCard("hsi", row, "data-hsi", row.download || "", name, inner);
  }, () => "<p class='job-empty'>" + tx("empty.hsi") + "</p>");
  host.querySelectorAll("[data-hsi]").forEach((btn) => {
    btn.addEventListener("click", () => openHsiRecord(btn.getAttribute("data-hsi") || ""));
  });
}

let archRows = [];

function renderArch() {
  const host = $("arch-list");
  if (!host) return;
  fillRecordHost(host, "arch", mergedRecords(archRows, archSources), (row) => {
    if (row.role === "source") return sourceCard("arch", row);
    const name = fileNameOf(row.download) || String(row.source || "");
    const bits = [];
    const when = fmtWhen(row.created_at);
    if (when) bits.push(when);
    if (row.rows) bits.push(tx("arch.rows", { n: row.rows }));
    const meta = "<span class='job-meta'><span class='job-meta-text'>" + escText(bits.join(" · ")) + "</span></span>";
    const inner = recordInner(tx("record.kind.arch"), recordTitle(name), meta);
    return recordCard("arch", row, "data-arch", row.download || "", name, inner);
  }, () => "<p class='job-empty'>" + tx("empty.arch") + "</p>");
  host.querySelectorAll("[data-arch]").forEach((btn) => {
    btn.addEventListener("click", () => openArchRecord(btn.getAttribute("data-arch") || ""));
  });
}

const sheetRecord = {
  icd: { rows: () => icdRows, sources: () => icdSources, empty: "empty.icd", attr: "data-icd", panel: "icd", msg: setIcdMsg, show: showIcdDownload },
  bom: { rows: () => bomRows, sources: () => bomSources, empty: "empty.bom", attr: "data-bom", panel: "bom", msg: setBomMsg, show: showBomDownload },
  etest: { rows: () => etestRows, sources: () => etestSources, empty: "empty.etest", attr: "data-etest", panel: "etest", msg: setEtestMsg, show: showEtestDownload },
};

function renderSheetRecords(kind) {
  const spec = sheetRecord[kind];
  const host = $(recordListId(kind));
  if (!spec || !host) return;
  fillRecordHost(host, kind, mergedRecords(spec.rows(), spec.sources()), (row) => {
    if (row.role === "source") return sourceCard(kind, row);
    const name = fileNameOf(row.download) || String(row.source || "");
    const bits = [];
    const when = fmtWhen(row.created_at);
    if (when) bits.push(when);
    if (kind === "icd" && row.pins) bits.push(tx("io.pins", { n: row.pins }));
    if ((kind === "bom" || kind === "etest") && row.rows) bits.push(tx("arch.rows", { n: row.rows }));
    const meta = "<span class='job-meta'><span class='job-meta-text'>" + escText(bits.join(" · ")) + "</span></span>";
    const kindLabel = kind === "bom" ? tx("record.kind.bom") : kind === "etest" ? tx("record.kind.etest") : tx("record.kind.icd");
    const inner = recordInner(kindLabel, recordTitle(name), meta);
    return recordCard(kind, row, spec.attr, row.download || "", name, inner);
  }, () => "<p class='job-empty'>" + tx(spec.empty) + "</p>");
  host.querySelectorAll("[" + spec.attr + "]").forEach((btn) => {
    btn.addEventListener("click", () => openSheetRecord(kind, btn.getAttribute(spec.attr) || ""));
  });
}

function openSheetRecord(kind, download) {
  const spec = sheetRecord[kind];
  if (!spec) return;
  const row = spec.rows().find((item) => item.download === download) || {};
  const name = fileNameOf(download) || String(row.source || "");
  setPanel(spec.panel);
  spec.msg(name, "ok");
  spec.show({ name, download });
}

function openArchRecord(download) {
  const row = archRows.find((item) => item.download === download) || {};
  const name = fileNameOf(download) || String(row.source || "");
  setPanel("arch");
  if (row.rows) {
    setArchMsg(tx("arch.done", { name, files: row.files || 0, rows: row.rows, tables: row.tables || 0 }), "ok");
  } else {
    setArchMsg(name, "ok");
  }
  showArchDownload({ name, download });
}

// 带了上一版才谈差异；0 条差异和没有上一版是两回事。
function hsiDoneKey(row) {
  if (Number(row.changes || 0) > 0) return "io.done";
  return row.previous ? "io.doneSame" : "io.doneFirst";
}

function openHsiRecord(download) {
  const row = hsiRows.find((item) => item.download === download) || {};
  const name = fileNameOf(download) || String(row.source || "");
  setPanel("io");
  if (row.pins) {
    setIoMsg(tx(hsiDoneKey(row), { name, pins: row.pins, changes: row.changes || 0 }), "ok");
  } else {
    setIoMsg(name, "ok");
  }
  showIoDownload({ name, download });
}

function renderJobs() {
  const host = $("job-list");
  if (!host) return;
  fillRecordHost(host, "jobs", mergedRecords(jobRows, jobSources), (row) => {
    if (row.role === "source") return sourceCard("jobs", row);
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
    const meta = "<span class='job-meta'>"
      + "<span class='job-status " + st.cls + "'>" + st.text + "</span>"
      + (tag ? "<i class='job-tag'>" + escText(tag) + "</i>" : "")
      + "<span class='job-meta-text'>" + escText(bits.join(" · ") || (row.message || "")) + "</span>"
      + "</span>";
    const inner = recordInner(tx("record.kind.sheet"), name, meta);
    return recordCard("jobs", row, "data-id", id, name, inner);
  }, () => "<div class='job-empty'>" + EMPTY_JOBS_SVG
    + "<p>" + tx("empty.jobs") + "</p><small>" + tx("empty.jobsHint") + "</small></div>");
  host.querySelectorAll(".job-open[data-id]").forEach((btn) => {
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
    const [data, hsi, arch, icd, bom, etest] = await Promise.all([
      json("/api/jobs"),
      json("/api/hsi/history").catch(() => ({ records: [] })),
      json("/api/arch/history").catch(() => ({ records: [] })),
      json("/api/icd/history").catch(() => ({ records: [] })),
      json("/api/ce-bom/history").catch(() => ({ records: [] })),
      json("/api/enterprise-test/history").catch(() => ({ records: [] })),
    ]);
    const split = (rows) => {
      const outputs = [];
      const sources = [];
      (rows || []).forEach((row) => {
        if (row && row.role === "source") sources.push(row);
        else outputs.push(row);
      });
      return [outputs, sources];
    };
    [jobRows, jobSources] = split(data.jobs);
    [hsiRows, hsiSources] = split(hsi.records);
    [archRows, archSources] = split(arch.records);
    [icdRows, icdSources] = split(icd.records);
    [bomRows, bomSources] = split(bom.records);
    [etestRows, etestSources] = split(etest.records);
    recordFolders = {
      jobs: data.folders || [],
      hsi: hsi.folders || [],
      arch: arch.folders || [],
      icd: icd.folders || [],
      bom: bom.folders || [],
      etest: etest.folders || [],
    };
    renderJobs();
    renderHsi();
    renderArch();
    renderSheetRecords("icd");
    renderSheetRecords("bom");
    renderSheetRecords("etest");
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
    + (extract ? "<div id='sor-items' class='sor-items'></div>" : "")
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

let sorView = { id: "", items: [], filter: "all", q: "", group: "", openKey: "", extraOpen: false };

function itemBucket(status) {
  const s = String(status || "");
  if (s === "已检索到" || s === "通过") return "found";
  if (s.indexOf("局部对应") === 0 || s === "需修改") return "partial";
  return "miss";
}

function statusLabel(it) {
  const s = String((it && it.status) || "").trim();
  if (!s) return String((it && it.value) || "").trim() ? "—" : tx("items.filterMiss");
  if (s.indexOf("局部对应") === 0) return tx("items.filterPartial");
  return s;
}

function loadSorItems(data) {
  const box = document.getElementById("sor-items");
  if (!box) return;
  const id = String((data && data.id) || "");
  if (!id) {
    box.innerHTML = "";
    return;
  }
  if (!box.dataset.bound) {
    box.dataset.bound = "1";
    box.addEventListener("click", onSorClick);
    box.addEventListener("input", onSorInput);
    box.addEventListener("change", onSorInput);
    box.addEventListener("compositionstart", onSorComposeStart);
    box.addEventListener("compositionend", onSorComposeEnd);
  }
  box.innerHTML = "<p class='sor-wait'>" + tx("items.loading") + "</p>";
  json("/api/jobs/" + encodeURIComponent(id) + "/items").then((payload) => {
    const live = document.getElementById("sor-items");
    if (!live || !lastShownJob || String(lastShownJob.id || "") !== id) return;
    sorView = {
      id: id,
      items: Array.isArray(payload.items) ? payload.items : [],
      filter: "all",
      q: "",
      group: "",
      openKey: "",
      extraOpen: false,
    };
    renderSorItems();
  }).catch((err) => {
    const live = document.getElementById("sor-items");
    if (live) {
      const msg = (err && err.message) ? err.message : String(err);
      live.innerHTML = "<p class='sor-wait'>" + escText(msg) + "</p>";
    }
  });
}

function onSorClick(ev) {
  const btn = ev.target.closest("[data-filter]");
  if (btn) {
    sorView.filter = btn.getAttribute("data-filter") || "all";
    sorView.openKey = "";
    renderSorItems();
    return;
  }
  const extra = ev.target.closest("[data-extra]");
  if (extra) {
    sorView.extraOpen = !sorView.extraOpen;
    renderSorItems();
    return;
  }
  const row = ev.target.closest("tr[data-key]");
  if (!row || !ev.currentTarget.contains(row)) return;
  const key = row.getAttribute("data-key") || "";
  const box = ev.currentTarget;
  const wasOpen = sorView.openKey === key;
  box.querySelectorAll("tr.sor-detail").forEach((el) => el.remove());
  box.querySelectorAll("tr.is-open").forEach((el) => el.classList.remove("is-open"));
  if (wasOpen) {
    sorView.openKey = "";
    return;
  }
  const it = (sorView.items || []).find((item) => sorKey(item) === key);
  if (!it) return;
  sorView.openKey = key;
  row.classList.add("is-open");
  row.insertAdjacentHTML("afterend", sorDetailRow(it));
  const detail = row.nextElementSibling;
  const scroller = row.closest(".sor-scroll");
  if (detail && scroller) {
    const view = scroller.getBoundingClientRect();
    const boxBottom = detail.getBoundingClientRect().bottom;
    if (boxBottom > view.bottom) scroller.scrollTop += boxBottom - view.bottom + 8;
  }
}

function onSorComposeStart(ev) {
  const t = ev.target;
  if (t.matches && t.matches("[data-q]")) t.dataset.composing = "1";
}

function onSorComposeEnd(ev) {
  const t = ev.target;
  if (!t.matches || !t.matches("[data-q]")) return;
  delete t.dataset.composing;
  sorView.q = t.value;
  paintSorRows();
}

function onSorInput(ev) {
  const t = ev.target;
  if (t.matches("[data-q]")) {
    if (ev.isComposing || t.dataset.composing) return;
    sorView.q = t.value;
    paintSorRows();
    return;
  }
  if (!t.matches("[data-group]")) return;
  sorView.group = t.value;
  renderSorItems();
}

function sorKey(it) {
  return (it.extra ? "x:" : "m:") + String(it.seq || "") + ":" + String(it.name || "");
}

function sorMatchQuery(it) {
  const q = String(sorView.q || "").trim().toLowerCase();
  if (!q) return true;
  const name = String(it.name || "").toLowerCase();
  const seq = String(it.seq || "");
  const value = String(it.value || "").toLowerCase();
  return name.indexOf(q) >= 0 || value.indexOf(q) >= 0 || (seq && seq.indexOf(q) >= 0);
}

function sorVisible(main, extra) {
  const shown = main.filter((it) => {
    if (sorView.group && String(it.group || "") !== sorView.group) return false;
    if (!sorMatchQuery(it)) return false;
    return sorView.filter === "all" || itemBucket(it.status) === sorView.filter;
  }).map((it, index) => ({ it: it, index: index }));
  shown.sort((a, b) => sorRank(a.it) - sorRank(b.it) || a.index - b.index);
  const extraShown = extra.filter((it) => !sorView.group && sorMatchQuery(it));
  return { shown: shown, extraShown: extraShown };
}

function sorBodyHtml(shown) {
  return shown.length
    ? shown.map((row) => sorRowMarkup(row.it)).join("")
    : "<tr><td class='sor-none' colspan='5'>" + tx("items.none") + "</td></tr>";
}

function sorExtraHtml(extraShown) {
  if (!extraShown.length) return "";
  return "<div class='sor-extra" + (sorView.extraOpen ? " is-open" : "") + "'>"
    + "<button type='button' class='sor-extra-btn' data-extra='1'>"
    + "<i class='sor-caret'></i>"
    + tx("items.extra") + "<b>" + extraShown.length + "</b>"
    + "</button>"
    + (sorView.extraOpen
      ? "<div class='sor-scroll'><table class='sor-table'>" + sorHead() + "<tbody>"
        + extraShown.map(sorRowMarkup).join("")
        + "</tbody></table></div>"
      : "")
    + "</div>";
}

function paintSorRows() {
  const box = document.getElementById("sor-items");
  const tbody = box && box.querySelector(".sor-scroll tbody");
  if (!tbody) {
    renderSorItems();
    return;
  }
  const all = Array.isArray(sorView.items) ? sorView.items : [];
  const visible = sorVisible(all.filter((it) => !it.extra), all.filter((it) => it.extra));
  tbody.innerHTML = sorBodyHtml(visible.shown);
  const old = box.querySelector(".sor-extra");
  if (old) old.remove();
  const extra = sorExtraHtml(visible.extraShown);
  if (extra) box.insertAdjacentHTML("beforeend", extra);
}

function renderSorItems() {
  const box = document.getElementById("sor-items");
  if (!box) return;
  const pageX = window.scrollX;
  const pageY = window.scrollY;
  const all = Array.isArray(sorView.items) ? sorView.items : [];
  const main = all.filter((it) => !it.extra);
  const extra = all.filter((it) => it.extra);
  const groups = [];
  main.forEach((it) => {
    const name = String(it.group || "");
    if (name && groups.indexOf(name) < 0) groups.push(name);
  });
  const counts = { all: main.length, found: 0, partial: 0, miss: 0 };
  main.forEach((it) => {
    counts[itemBucket(it.status)] += 1;
  });
  const filters = [
    ["found", "items.filterFound"],
    ["partial", "items.filterPartial"],
    ["miss", "items.filterMiss"],
    ["all", "items.filterAll"],
  ];
  const chips = filters.map(([id, key]) => {
    const on = sorView.filter === id ? " is-on" : "";
    return "<button type='button' class='sor-chip" + on + "' data-filter='" + id + "'>"
      + "<i class='sor-dot is-" + id + "'></i>"
      + tx(key) + "<b>" + counts[id] + "</b></button>";
  }).join("");
  const groupOpts = "<option value=''>" + tx("items.groupAll") + "</option>"
    + groups.map((name) => {
      const sel = sorView.group === name ? " selected" : "";
      return "<option value='" + escText(name) + "'" + sel + ">" + escText(name) + "</option>";
    }).join("");
  const visible = sorVisible(main, extra);
  const body = sorBodyHtml(visible.shown);
  const extraBlock = sorExtraHtml(visible.extraShown);
  box.innerHTML = "<div class='sor-head'><div class='sor-title'>" + tx("items.head") + "</div>"
    + "<p class='sor-lead'>" + tx("items.lead") + "</p></div>"
    + "<div class='sor-bar'><div class='sor-filters'>" + chips + "</div>"
    + "<div class='sor-find'><select data-group>" + groupOpts + "</select>"
    + "<input data-q type='search' value='" + escText(sorView.q) + "' placeholder='" + escText(tx("items.search")) + "'>"
    + "</div></div>"
    + "<div class='sor-scroll'><table class='sor-table'>" + sorHead()
    + "<tbody>" + body + "</tbody></table></div>"
    + extraBlock;
  window.scrollTo(pageX, pageY);
}

function sorHead() {
  return "<colgroup><col class='c-seq'><col class='c-name'><col class='c-value'><col class='c-loc'><col class='c-status'></colgroup>"
    + "<thead><tr><th>" + tx("items.colSeq") + "</th><th>" + tx("items.colName")
    + "</th><th>" + tx("items.colValue") + "</th><th>" + tx("items.colLoc")
    + "</th><th>" + tx("items.colStatus") + "</th></tr></thead>";
}

function sorRank(it) {
  const bucket = itemBucket(it.status);
  if (bucket === "found") return 0;
  if (bucket === "partial") return 1;
  return 2;
}

function sorLocMarkup(page, clause) {
  if (page && clause) {
    return "<span class='sor-page'>" + escText(page) + "</span><span class='sor-clause'>" + escText(clause) + "</span>";
  }
  if (page) return "<span class='sor-page'>" + escText(page) + "</span>";
  if (clause) return "<span class='sor-clause is-only'>" + escText(clause) + "</span>";
  return "<span class='sor-page is-empty'>—</span>";
}

function sorDetailRow(it) {
  const page = String(it.page || "").trim();
  const clause = String(it.clause || "").trim();
  const excerpt = String(it.excerpt || "").trim();
  const note = String(it.note || "").trim();
  const seq = Number(it.seq || 0) ? String(it.seq) : "";
  const meta = [
    "<span>" + tx("items.colItem") + " <b>" + escText(seq || "—") + "</b></span>",
    "<span>" + tx("items.colPage") + " <b>" + escText(page || "—") + "</b></span>",
    "<span>" + tx("items.colClause") + " <b>" + escText(clause || "—") + "</b></span>",
  ].join("");
  return "<tr class='sor-detail'><td colspan='5'><div class='sor-cite'>"
    + "<div class='sor-cite-meta'>" + meta + "</div>"
    + "<div class='sor-cite-label'>" + tx("items.excerpt") + "</div>"
    + "<p class='sor-cite-body'>" + escText(excerpt || "—") + "</p>"
    + (note ? "<p class='sor-cite-note'><b>" + tx("items.note") + "</b>" + escText(note) + "</p>" : "")
    + "</div></td></tr>";
}

function sorRowMarkup(it) {
  const key = sorKey(it);
  const open = sorView.openKey === key;
  const value = String(it.value || "").trim();
  const bucket = it.extra && value && !String(it.status || "").trim() ? "found" : itemBucket(it.status);
  const seq = Number(it.seq || 0) ? String(it.seq) : "";
  const page = String(it.page || "").trim();
  const clause = String(it.clause || "").trim();
  const group = String(it.group || "").trim();
  const detail = open ? sorDetailRow(it) : "";
  return "<tr class='sor-row is-" + bucket + (open ? " is-open" : "") + "' data-key='" + escText(key) + "'>"
    + "<td class='num sor-seq'><i class='sor-caret'></i><span>" + escText(seq) + "</span></td>"
    + "<td><span class='sor-name'>" + escText(it.name || "") + "</span>"
    + (group ? "<span class='sor-group'>" + escText(group) + "</span>" : "") + "</td>"
    + "<td><span class='sor-value" + (value ? "" : " is-empty") + "' title='" + escText(value || tx("items.emptyValue")) + "'>"
    + escText(value || tx("items.emptyValue")) + "</span></td>"
    + "<td class='sor-loc'>" + sorLocMarkup(page, clause) + "</td>"
    + "<td><span class='sor-status is-" + bucket + "'>" + escText(statusLabel(it)) + "</span></td>"
    + "</tr>" + detail;
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
  loadSorItems(data);
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

const FLOWS = {
  extract: {
    zh: {
      title: "出表核对",
      input: ["一份规格书：PDF、Word 或 Excel，不超过 80MB"],
      output: ["电控设计需求核对", "01_封面、02_需求核对、03_提取质量审查、04_清单外、05_条目说明"],
      bound: ["只根据这份规格书写", "读不出文字就不出表", "05_条目说明不是本份抽出值"],
      steps: [
        { k: "p", t: "选择规格书", d: "PDF、Word 或 Excel" },
        { k: "q", q: "能读出文字？", join: false, no: [{ k: "e", t: "停止，不出表", stop: true }] },
        { k: "p", t: "核对这份材料", d: "看中文、英文和前后是否一致" },
        { k: "q", q: "对得上原文？", yes: [{ k: "p", t: "写入该格", d: "内容来自这份规格书" }], no: [{ k: "p", t: "留空或待确认", d: "对不上就不填" }] },
        { k: "p", t: "写出核对表", d: "大标题是电控设计需求核对。源文件用上传时的文件名。对照清单仍是原来的 116 条清单" },
        { k: "p", t: "按页签看", d: "02 是主表。绿色已检索到，琥珀局部对应，浅红未检索到。03 是提取质量审查。点一行才展开原文" },
      ],
    },
    en: {
      title: "Extract and review",
      input: ["One spec: PDF, Word, or Excel, up to 80MB"],
      output: ["An e-control design review workbook", "Cover, requirement check, document review, off-list, and item notes"],
      bound: ["Use only this spec", "Stop if the text cannot be read", "The item-note sheet is not this document's extracted values"],
      steps: [
        { k: "p", t: "Choose the spec", d: "PDF, Word, or Excel" },
        { k: "q", q: "Text readable?", join: false, no: [{ k: "e", t: "Stop. No workbook", stop: true }] },
        { k: "p", t: "Check this document", d: "Compare the Chinese, English, and internal consistency" },
        { k: "q", q: "Matches the source?", yes: [{ k: "p", t: "Write the cell", d: "The value comes from this spec" }], no: [{ k: "p", t: "Leave blank or pending", d: "Do not fill a cell that does not match" }] },
        { k: "p", t: "Write the workbook", d: "The title is the review name. The source file keeps the uploaded name" },
        { k: "p", t: "Read the tabs", d: "The second sheet is the working list. Open a row to read the source text" },
      ],
    },
  },
  io: {
    zh: {
      title: "HSI 生成",
      input: ["选定的 HSI 模板", "有原理图就用 PDF 或 EDIF，没有就用芯片手册和封装"],
      output: ["同一套模板表", "改过的格子标绿，并写待人工复核", "变更记录追加本次时间"],
      bound: ["只改这次读到、并且和模板不同的格子", "脚号别名不是网络名，不写成交叉", "模板里没有的脚不新增，原理图没有的脚不删除"],
      steps: [
        { k: "q", q: "有原理图？", yes: [
          { k: "p", t: "读原理图", d: "PDF 按符号脚，EDIF 按网络名和外部电阻" },
          { k: "q", q: "符号对得上模板？", yes: [
            { k: "p", t: "更新这一行", d: "球号变了才改。有导线网络名就写入 Pin Definition；没有网络名、格子又空着，才写入符号上的功能。复用只在空格时填写" },
            { k: "q", q: "和模板原名相同？", yes: [
              { k: "p", t: "不写交叉", d: "核对状态不因另一个脚号改动" },
            ], no: [
              { k: "p", t: "写交叉说明", d: "格子改成原理图上的名字，标记留下模板原名" },
            ]},
          ], no: [
            { k: "p", t: "不新增这一行", d: "对不上的脚和网络都不补" },
          ]},
          { k: "p", t: "去掉星驱原理图网络列", d: "这一列不进入输出。后面的列和公式左移" },
          { k: "p", t: "后面各页留下", d: "原理图没写到的页不删。盖住文字的图挪到这段文字右侧，按原来的大小" },
          { k: "p", t: "补回跳转", d: "一对一直接跳，一对多先打开跳转索引" },
          { k: "p", t: "死区时间可以改", d: "7_Dead Time 的 μs 改一格，要求文字和时序图跟着变" },
          { k: "p", t: "3041 用下拉选位", d: "一位两位下拉选 0、1、2。位数多的直接填数。寄存器值和纳秒结果跟着变" },
          { k: "p", t: "变更记录加上本次时间", d: "封面和没改的页保持模板" },
        ], no: [
          { k: "p", t: "读芯片手册", d: "认不出型号，或没有该封装的脚表，就停止" },
          { k: "p", t: "按封装列出全部引脚", d: "数总脚数" },
          { k: "p", t: "按符号和复用分类", d: "电源、地、ADC、SPI、CAN、GPIO、IO。多种接法都写上" },
          { k: "p", t: "删掉信号名列", d: "没有原理图不留信号名。时间常数的单位列留下" },
        ] },
        { k: "p", t: "写出 HSI", d: "本次新写的格子标绿。新增页的列宽按字数收" },
      ],
    },
    en: {
      title: "HSI",
      input: ["The selected HSI template", "A schematic PDF or EDIF, or a datasheet and package if there is none"],
      output: ["The same template workbook", "Changed cells are green and marked for review", "This run's time is appended to the history"],
      bound: ["Change a cell only when this reading differs from the template", "A pin alias is not a net name", "Do not add pins absent from the template, or delete pins absent from the schematic"],
      steps: [
        { k: "q", q: "Schematic?", yes: [
          { k: "p", t: "Read the schematic", d: "PDF by symbol pin. EDIF by net name and external resistor" },
          { k: "q", q: "Symbol matches the template?", yes: [
            { k: "p", t: "Update this row", d: "Change the ball only when it differs. A wire net goes into Pin Definition. If there is no net and that cell is empty, write the function printed on the symbol. Fill an option cell only when it is empty" },
            { k: "q", q: "Port name matches the net?", yes: [
              { k: "p", t: "No cross note", d: "Another pin number does not change the review status" },
            ], no: [
              { k: "p", t: "Write a cross note", d: "Keep the port name. Green the net and mark it for review" },
            ]},
          ], no: [
            { k: "p", t: "Do not add this row", d: "Leave unmatched pins and nets out" },
          ]},
          { k: "p", t: "Drop the project net column", d: "The Xingqu schematic-net column is removed. Later columns and formulas shift left" },
          { k: "p", t: "Later sheets stay", d: "Do not delete a sheet the schematic did not fill. Move a picture off the text, keeping its size" },
          { k: "p", t: "Restore jumps", d: "One hit jumps directly. Several hits open the index" },
          { k: "p", t: "Dead time stays editable", d: "Change the μs cell on 7_Dead Time. The requirement text and the timing figure follow it" },
          { k: "p", t: "3041 uses a bit dropdown", d: "One or two bits choose 0, 1, or 2. Wider fields are typed. The register word and the nanosecond result follow" },
          { k: "p", t: "Stamp this run", d: "Cover and untouched sheets stay as in the template" },
        ], no: [
          { k: "p", t: "Read the datasheet", d: "Stop if the part or the package pin table cannot be read" },
          { k: "p", t: "List every pin", d: "Count the package pins" },
          { k: "p", t: "Classify by symbol and options", d: "Power, ground, ADC, SPI, CAN, GPIO, IO. Write every option" },
          { k: "p", t: "Remove signal-name columns", d: "Without a schematic there is no signal name. Keep the time-constant unit" },
        ] },
        { k: "p", t: "Write the HSI", d: "Green the cells written this run. Size new sheets by their text" },
      ],
    },
  },
  icd: {
    zh: {
      title: "ICD 规划",
      input: ["当版 ICD", "上一版可以不选"],
      output: ["当版原表，改过的格子涂色", "本表小结在表头右侧", "有上一版时，原表后面加差异总结"],
      bound: ["只反映当版实际有的内容", "原表列宽不缩小，图按原文件里的尺寸留下", "删除的行写在右侧本表小结，不插回原表"],
      steps: [
        { k: "q", q: "是引脚表？", join: false, no: [{ k: "e", t: "不出表", stop: true }] },
        { k: "p", t: "按原表抽出引脚", d: "表和列保持当版原来的样子" },
        { k: "q", q: "有上一版？", yes: [
          { k: "p", t: "逐行对照", d: "看出新增、修改和删除" },
          { k: "p", t: "原表涂色", d: "新增绿，修改黄，删除红。只涂改过的那一格" },
          { k: "p", t: "小结写在右侧", d: "颜色说明单独占最上面一行，原表下移一行。本表小结仍在表头右侧，空一列。不插入列" },
          { k: "p", t: "图保持原尺寸", d: "沿用客户原来的两个格子。有图的表用普通视图从 A1 打开，不再铺成分页预览" },
          { k: "p", t: "原表后面写差异总结", d: "关键变化先写接插件的厂家、供应商、型号和料号。引脚增减不展开" },
        ], no: [
          { k: "p", t: "保持当版原表", d: "不编上一版没有的差异" },
        ]},
        { k: "p", t: "写出引脚清单", d: "变更记录不进入输出" },
      ],
    },
    en: {
      title: "ICD",
      input: ["The current ICD", "A previous ICD is optional"],
      output: ["The current sheets, with changed cells colored", "A sheet note to the right of the header", "A difference summary after the original sheets when a previous file exists"],
      bound: ["Show only what the current file actually has", "Do not shrink original columns. Keep each picture at its recorded size", "Removed rows go in the note on the right"],
      steps: [
        { k: "q", q: "Pin workbook?", join: false, no: [{ k: "e", t: "No workbook", stop: true }] },
        { k: "p", t: "Read the current sheets", d: "Keep their tables and columns" },
        { k: "q", q: "Previous file?", yes: [
          { k: "p", t: "Compare row by row", d: "See what was added, changed, or removed" },
          { k: "p", t: "Color the current sheets", d: "Green for added, yellow for changed, red for removed. Color only that cell" },
          { k: "p", t: "Note the sheet on the right", d: "The color note takes the top row and the original sheet moves down one row. The summary stays to the right of the header. Do not insert a column" },
          { k: "p", t: "Keep picture size", d: "Do not stretch a picture with its cells. Picture sheets stay in page-break preview and open at A1" },
          { k: "p", t: "Write the summary after the sheets", d: "Lead with the connector maker, supplier, model, and part number. Do not expand pin adds and deletes" },
        ], no: [
          { k: "p", t: "Keep the current sheets", d: "Do not invent a difference" },
        ]},
        { k: "p", t: "Write the pin list", d: "Drop the change-log sheet from the output" },
      ],
    },
  },
  bom: {
    zh: {
      title: "CE BOM",
      input: ["电子件用 AD 导出的 Excel", "结构件用二维图", "上一版可以不选"],
      output: ["供应商表，电子件级别为 4", "字段匹配页一个零件一行", "结构件另起一张同样的列"],
      bound: ["规则表没有的 TYPE，中文名称留空", "3 级件不提取尺寸", "明细栏旁边的技术要求不写入零件名", "上一版多出来的零件不补"],
      steps: [
        { k: "q", q: "是电子件？", yes: [
          { k: "p", t: "读 AD 导出的 Excel", d: "取 TYPE、数量、规格型号" },
          { k: "p", t: "TYPE 对中文名称", d: "规则表没有的名称留空" },
          { k: "p", t: "级别写成 4", d: "特殊层级留给人工改" },
          { k: "p", t: "另起字段匹配页", d: "一个零件一行。缺的字段标未对上，页首写合计" },
        ], no: [
          { k: "q", q: "是这张二维图上的零件？", yes: [
            { k: "p", t: "定为 2 级", d: "读标题栏的图样名称、图号、材料、质量，以及视图上的外形尺寸。没有文字层也读标题栏这一块" },
          ], no: [
            { k: "p", t: "定为 3 级", d: "明细里的子件不提取尺寸，尺寸手填" },
          ]},
        ]},
        { k: "q", q: "有上一版？", yes: [
          { k: "p", t: "按名称校核用量和规格", d: "不一致写出来。上一版多出的零件不补行" },
        ], no: [
          { k: "p", t: "只写这次读到的行", d: "不用别的表填空" },
        ]},
        { k: "p", t: "写出供应商表", d: "字段匹配的列宽按字数收" },
      ],
    },
    en: {
      title: "CE BOM",
      input: ["An AD Excel BOM for electronic parts", "A 2D drawing for structure", "A previous BOM is optional"],
      output: ["A supplier sheet, with electronic parts at level 4", "A field-match sheet with one row per part", "Structure on a second sheet with the same columns"],
      bound: ["Leave the Chinese name blank when TYPE is not in the rules", "Do not extract sizes for level-3 parts", "A note beside the name is not part of the part name", "Do not add parts that exist only in the previous file"],
      steps: [
        { k: "q", q: "Electronic parts?", yes: [
          { k: "p", t: "Read the AD Excel", d: "Take TYPE, quantity, and spec" },
          { k: "p", t: "Map TYPE to the Chinese name", d: "Leave the name blank when the rules have no TYPE" },
          { k: "p", t: "Write level 4", d: "Leave unusual levels for a person to edit" },
          { k: "p", t: "Add a field-match sheet", d: "One row per part. Mark a missing field, and put the total at the top" },
        ], no: [
          { k: "q", q: "Part on this drawing?", yes: [
            { k: "p", t: "Level 2", d: "Read the title block name, number, material, and mass, plus the outline on the view. A drawing without a text layer still uses the title block" },
          ], no: [
            { k: "p", t: "Level 3", d: "Do not extract sizes for detail-list children" },
          ]},
        ]},
        { k: "q", q: "Previous BOM?", yes: [
          { k: "p", t: "Check quantity and spec by name", d: "Record a mismatch. Do not add parts only in the previous file" },
        ], no: [
          { k: "p", t: "Write this input only", d: "Do not fill blanks from another sheet" },
        ]},
        { k: "p", t: "Write the supplier sheet", d: "Size the field-match columns by their text" },
      ],
    },
  },
  arch: {
    zh: {
      title: "需求拆解",
      input: ["一份或多份需求 PDF"],
      output: ["确认说明和需求清单", "整表和图表放在附件"],
      bound: ["数值只来自原文", "意见是初步意见，理由写在备注", "状态留给人确认"],
      steps: [
        { k: "p", t: "选择 PDF", d: "可以一次选多份" },
        { k: "q", q: "能读出文字？", join: false, no: [{ k: "e", t: "停止，并说明原因", stop: true }] },
        { k: "p", t: "拆成条款", d: "保留出处和带单位的数值" },
        { k: "p", t: "保留整表和图表", d: "看不清文字的页不拆进条款" },
        { k: "p", t: "标出不一致", d: "前后对不上的标出来，不改原数值" },
        { k: "p", t: "写出对照稿", d: "每条有初步意见和理由。状态仍待人确认" },
      ],
    },
    en: {
      title: "Requirement breakdown",
      input: ["One or more requirement PDFs"],
      output: ["A confirmation note and a requirement list", "Whole tables and figures go to the attachment"],
      bound: ["Numbers come only from the document", "The comment is a preliminary opinion. The reason is in the note", "Status is left for a person"],
      steps: [
        { k: "p", t: "Choose PDFs", d: "Several files can be selected" },
        { k: "q", q: "Text readable?", join: false, no: [{ k: "e", t: "Stop and say why", stop: true }] },
        { k: "p", t: "Split into clauses", d: "Keep the source and values with units" },
        { k: "p", t: "Keep tables and figures", d: "Pages without readable text are not split" },
        { k: "p", t: "Mark conflicts", d: "Flag disagreements. Do not change the number" },
        { k: "p", t: "Write the workbook", d: "Each item has a preliminary opinion and a reason. Status stays pending" },
      ],
    },
  },
};

function flowLang() {
  return document.documentElement.getAttribute("data-lang") === "en" ? "en" : "zh";
}

function fcEsc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function fcArrow(label, kind) {
  const text = label ? `<span>${fcEsc(label)}</span>` : "";
  const cls = kind === "no" ? " is-no" : "";
  return `<div class="fc-arrow${cls}" aria-hidden="true"><svg viewBox="0 0 16 28" width="16" height="28"><path d="M8 0 V27 M3.2 20.5 L8 27 L12.8 20.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="miter" stroke-linecap="butt"/></svg>${text}</div>`;
}

function fcDiamond(question) {
  return `<div class="fc-diamond"><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><polygon points="50,1.5 98.5,50 50,98.5 1.5,50"></polygon></svg><span>${fcEsc(question)}</span></div>`;
}

function fcNodes(nodes) {
  return (nodes || []).map((node, index) => {
    const prev = nodes[index - 1];
    const lead = index ? fcArrow(prev && prev.k === "q" && prev.join === false ? tx("flow.yes") : "") : "";
    return lead + fcNode(node);
  }).join("");
}

function fcNode(node) {
  if (node.k === "p") {
    return `<div class="fc-proc"><b>${fcEsc(node.t)}</b>${node.d ? `<span>${fcEsc(node.d)}</span>` : ""}</div>`;
  }
  if (node.k === "e") return `<div class="fc-term${node.stop ? " is-stop" : ""}">${fcEsc(node.t)}</div>`;
  if (node.k !== "q") return "";
  if (node.join === false) {
    return `<div class="fc-ask">${fcDiamond(node.q)}<div class="fc-out"><b>${fcEsc(tx("flow.no"))}</b>${fcNodes(node.no)}</div></div>`;
  }
  const yes = tx("flow.yes");
  const no = tx("flow.no");
  return `<div class="fc-fork">${fcDiamond(node.q)}<div class="fc-split" aria-hidden="true"></div><div class="fc-arms"><div class="fc-arm">${fcArrow(yes)}${fcNodes(node.yes)}</div><div class="fc-arm">${fcArrow(no, "no")}${fcNodes(node.no)}</div></div><div class="fc-join" aria-hidden="true"></div></div>`;
}

function openFlow(panel) {
  const pack = FLOWS[panel];
  const dialog = $("flow-dialog");
  if (!pack || !dialog) return;
  const data = pack[flowLang()] || pack.zh;
  $("flow-title").textContent = data.title;
  const meta = [
    ["flow.input", data.input],
    ["flow.output", data.output],
    ["flow.bound", data.bound],
  ].map(([key, items]) => (
    `<section class="flow-meta"><h3>${tx(key)}</h3><p>${items.join("。")}</p></section>`
  )).join("");
  const chart = [
    `<div class="fc-term">${fcEsc(tx("flow.start"))}</div>`,
    fcArrow(""),
    fcNodes(data.steps),
    fcArrow(""),
    `<div class="fc-term">${fcEsc(tx("flow.end"))}</div>`,
  ].join("");
  $("flow-body").innerHTML = `<div class="flow-meta-row">${meta}</div><div class="fc">${chart}</div>`;
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

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

document.querySelectorAll("[data-flow]").forEach((btn) => {
  btn.onclick = () => openFlow(btn.dataset.flow || "");
});
$("flow-close").onclick = () => {
  const dialog = $("flow-dialog");
  if (dialog && typeof dialog.close === "function") dialog.close();
};

function extractBusy() {
  return !!(currentJob || submitting || attaching);
}

// 点「SOR 参数提取 / 进入出表」是准备再出一份，不是回看。
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

function setRailRecordTab(tab) {
  const pick = ["hsi", "arch", "icd", "bom", "etest"].includes(tab) ? tab : "jobs";
  const panels = { jobs: $("job-list"), hsi: $("hsi-list"), icd: $("icd-list"), bom: $("bom-list"), etest: $("etest-list"), arch: $("arch-list") };
  const tabs = { jobs: $("rail-tab-jobs"), hsi: $("rail-tab-hsi"), icd: $("rail-tab-icd"), bom: $("rail-tab-bom"), etest: $("rail-tab-etest"), arch: $("rail-tab-arch") };
  Object.keys(panels).forEach((key) => {
    const on = key === pick;
    if (panels[key]) panels[key].hidden = !on;
    tabs[key]?.classList.toggle("is-on", on);
    tabs[key]?.setAttribute("aria-selected", on ? "true" : "false");
  });
}

$("rail-home").onclick = () => setPanel("home");
$("rail-extract").onclick = () => goExtract({ clearFile: true });
$("rail-io").onclick = () => setPanel("io");
$("rail-icd").onclick = () => setPanel("icd");
$("rail-bom").onclick = () => setPanel("bom");
$("rail-etest").onclick = () => setPanel("etest");
$("rail-arch").onclick = () => setPanel("arch");
$("rail-kb").onclick = () => setPanel("kb");
$("rail-tab-jobs").onclick = () => setRailRecordTab("jobs");
$("rail-tab-hsi").onclick = () => setRailRecordTab("hsi");
$("rail-tab-icd").onclick = () => setRailRecordTab("icd");
$("rail-tab-bom").onclick = () => setRailRecordTab("bom");
$("rail-tab-etest").onclick = () => setRailRecordTab("etest");
$("rail-tab-arch").onclick = () => setRailRecordTab("arch");
function syncIoResult() {
  const row = $("io-result");
  const msg = $("io-msg");
  const link = $("io-dl");
  if (!row) return;
  const msgOn = !!(msg && !msg.hidden && String(msg.textContent || "").trim());
  const dlOn = !!(link && !link.hidden);
  row.hidden = !(msgOn || dlOn);
}

function setIoMsg(text, kind) {
  const msg = $("io-msg");
  if (!msg) return;
  msg.classList.remove("is-info", "is-ok");
  if (kind) msg.classList.add("is-" + kind);
  msg.textContent = text || "";
  msg.hidden = !String(text || "").trim();
  syncIoResult();
}

function clearIoDownload() {
  const link = $("io-dl");
  if (!link) return;
  link.hidden = true;
  link.removeAttribute("href");
  syncIoResult();
}

let ioPackageSeq = 0;
let ioPackagesLoading = false;

function selectedIoPackage() {
  const picked = document.querySelector("#io-package-choices input:checked");
  return picked ? String(picked.value || "") : "";
}

function ioMode() {
  const picked = document.querySelector("input[name=io-mode]:checked");
  return picked ? picked.value : "schematic";
}

let ioMcuReady = false;

function applyIoMode() {
  const mode = ioMode();
  document.querySelectorAll("[data-io-mode]").forEach((el) => {
    const want = el.getAttribute("data-io-mode");
    if (el.id === "io-mcu-field") {
      el.hidden = mode !== "mcu" || !ioMcuReady;
      return;
    }
    if (el.id === "io-package-field") {
      el.hidden = mode !== "mcu" || !el.querySelector("input");
      return;
    }
    el.hidden = want !== "both" && want !== mode;
  });
  if (mode === "schematic") loadIoTemplates();
  refreshIoGenerate();
}

function selectedIoTemplateId() {
  const picked = document.querySelector("#io-template-choices input:checked");
  return picked ? String(picked.value || "") : "";
}

function selectedIoTemplateFile() {
  const input = $("io-template");
  return input && input.files && input.files[0] ? input.files[0] : null;
}

function hasIoTemplate() {
  return !!(selectedIoTemplateFile() || selectedIoTemplateId());
}

function refreshIoGenerate() {
  const btn = $("io-hsi");
  if (!btn) return;
  if (ioMode() === "schematic") {
    const file = $("io-schematic") && $("io-schematic").files && $("io-schematic").files[0];
    const name = file ? file.name.toLowerCase() : "";
    const schematicOk = name.endsWith(".edf") || name.endsWith(".pdf");
    btn.disabled = !(schematicOk && hasIoTemplate());
    btn.textContent = tx("io.revise");
    return;
  }
  const mcu = $("io-mcu") ? $("io-mcu").value.trim() : "";
  btn.disabled = ioPackagesLoading || !selectedIoPackage() || !mcu;
  btn.textContent = tx("io.generate");
}

function setPackageStatus(text, kind) {
  const status = $("io-package-status");
  if (!status) return;
  status.className = "io-package-status" + (kind ? " is-" + kind : "");
  if (!text) {
    status.hidden = true;
    status.textContent = "";
    return;
  }
  status.hidden = false;
  status.textContent = text;
}

function clearIoPackages() {
  ioPackagesLoading = false;
  ioMcuReady = false;
  const field = $("io-package-field");
  const mcuField = $("io-mcu-field");
  const mcuInput = $("io-mcu");
  const choices = $("io-package-choices");
  if (field) field.hidden = true;
  if (mcuField) mcuField.hidden = true;
  if (mcuInput) mcuInput.value = "";
  setPackageStatus("");
  if (choices) choices.innerHTML = "";
  refreshIoGenerate();
}

function renderIoPackages(packages) {
  const choices = $("io-package-choices");
  if (!choices) return;
  choices.innerHTML = "";
  packages.forEach((name) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "io-package";
    input.value = name;
    if (packages.length === 1) input.checked = true;
    label.appendChild(input);
    label.appendChild(document.createTextNode(name));
    choices.appendChild(label);
  });
  setPackageStatus(packages.length > 1 ? tx("io.packagePick") : "", packages.length > 1 ? "pick" : "");
  refreshIoGenerate();
}

let ioTemplatesLoaded = false;

function renderIoTemplates(rows, defaultId) {
  const host = $("io-template-choices");
  if (!host) return;
  const keepLocal = selectedIoTemplateFile();
  host.innerHTML = "";
  if (!rows.length) {
    host.innerHTML = "<p class='io-package-status is-pick'>" + escText(tx("io.templateEmpty")) + "</p>";
    refreshIoGenerate();
    return;
  }
  rows.forEach((row, index) => {
    const id = String(row.id || "");
    const name = String(row.name || row.file || id);
    if (!id) return;
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "io-template";
    input.value = id;
    if (!keepLocal && (id === defaultId || (!defaultId && index === 0))) input.checked = true;
    label.appendChild(input);
    label.appendChild(document.createTextNode(name));
    host.appendChild(label);
  });
  refreshIoGenerate();
}

async function loadIoTemplates() {
  const host = $("io-template-choices");
  if (!host || ioTemplatesLoaded) return;
  host.innerHTML = "<p class='io-package-status is-reading'>" + escText(tx("io.templateLoading")) + "</p>";
  try {
    const data = await json("/api/hsi/templates");
    const rows = Array.isArray(data.templates) ? data.templates : [];
    renderIoTemplates(rows, data.default ? String(data.default) : "");
    ioTemplatesLoaded = true;
  } catch (err) {
    host.innerHTML = "<p class='io-package-status is-pick'>" + escText(err.message || String(err)) + "</p>";
    refreshIoGenerate();
  }
}

async function loadIoPackages(file) {
  const seq = ++ioPackageSeq;
  const field = $("io-package-field");
  const choices = $("io-package-choices");
  clearIoDownload();
  setIoMsg("");
  if (!file) {
    clearIoPackages();
    return;
  }
  ioPackagesLoading = true;
  ioMcuReady = false;
  const mcuField = $("io-mcu-field");
  if (mcuField) mcuField.hidden = true;
  if (field) field.hidden = false;
  if (choices) choices.innerHTML = "";
  setPackageStatus(tx("io.packageReading"), "reading");
  refreshIoGenerate();
  const body = new FormData();
  body.append("datasheet", file);
  try {
    const resp = await fetch(apiUrl("/api/hsi/packages"), {
      method: "POST",
      credentials: "same-origin",
      headers: authHeaders(),
      body,
    });
    const data = await resp.json().catch(() => ({}));
    if (seq !== ioPackageSeq) return;
    if (!resp.ok) {
      const detail = data.detail || data.error || resp.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    const packages = Array.isArray(data.packages) ? data.packages.map(String) : [];
    if (!packages.length) throw new Error(tx("io.needPackage"));
    const detected = data.mcu ? String(data.mcu).trim() : "";
    const mcuInput = $("io-mcu");
    if (mcuInput) {
      mcuInput.value = detected;
      setMcuMenu(false);
    }
    ioMcuReady = true;
    ioPackagesLoading = false;
    renderIoPackages(packages);
    applyIoMode();
    if (detected) {
      const hint = tx("io.mcuFromManual", { mcu: detected });
      if (packages.length > 1) {
        setPackageStatus(tx("io.packagePick") + " " + hint, "pick");
      } else {
        setPackageStatus(hint, "");
      }
    }
  } catch (err) {
    if (seq !== ioPackageSeq) return;
    // 读不出封装就收起封装行，原因写在结果区
    clearIoPackages();
    setIoMsg(err.message || String(err));
  }
}

function showIoDownload(data, labelKey) {
  const link = $("io-dl");
  const name = data && data.name ? String(data.name) : "";
  if (!link || !name) {
    clearIoDownload();
    return;
  }
  const path = data.download || ("/files/" + encodeURIComponent(name));
  link.href = apiUrl(path);
  link.textContent = tx(labelKey || "io.download");
  link.hidden = false;
  syncIoResult();
}

function syncIoFileName(input, nameEl) {
  if (!input || !nameEl) return;
  const file = input.files && input.files[0];
  if (file) {
    nameEl.removeAttribute("data-i18n");
    nameEl.textContent = file.name;
    nameEl.classList.add("is-set");
    return;
  }
  nameEl.setAttribute("data-i18n", "io.fileNone");
  nameEl.textContent = tx("io.fileNone");
  nameEl.classList.remove("is-set");
}

function storedSources(accept, kind) {
  const rows = kind === "hsi" ? hsiSources : kind === "arch" ? archSources : kind === "icd" ? icdSources : kind === "bom" ? bomSources : kind === "etest" ? etestSources : jobSources;
  const seen = new Set();
  return rows.filter((row) => {
    const id = String(row.id || "");
    const name = String(row.source || "").toLowerCase();
    if (!id || seen.has(id)) return false;
    const ok = accept === "pdf" ? name.endsWith(".pdf")
      : accept === "sheet" ? (name.endsWith(".xlsx") || name.endsWith(".xlsm"))
      : accept === "manual" ? (name.endsWith(".pdf") || name.endsWith(".docx") || name.endsWith(".xlsx") || name.endsWith(".xlsm") || name.endsWith(".edf"))
      : accept === "schematic" ? (name.endsWith(".pdf") || name.endsWith(".edf") || name.endsWith(".xlsx") || name.endsWith(".xlsm"))
      : (name.endsWith(".pdf") || name.endsWith(".docx") || name.endsWith(".xlsx") || name.endsWith(".xlsm"));
    if (!ok) return false;
    seen.add(id);
    return true;
  });
}

async function fileFromSource(row) {
  const resp = await fetch(apiUrl(row.download), { credentials: "same-origin", headers: authHeaders() });
  const data = await resp.blob().catch(() => null);
  if (!resp.ok || !data) throw new Error(tx("io.noSource"));
  const name = String(row.source || "file");
  return new File([data], name, { type: data.type || "application/octet-stream" });
}

function assignPickedFile(target, file) {
  if (target === "spec") {
    setFile(file);
    return;
  }
  if (target === "arch-files") {
    addArchFiles([file]);
    clearArchDownload();
    setArchMsg("");
    renderArchFiles();
    return;
  }
  const input = $(target);
  if (!input || typeof DataTransfer === "undefined") return;
  const bag = new DataTransfer();
  bag.items.add(file);
  input.files = bag.files;
  input.dispatchEvent(new Event("change"));
}

async function useStoredSource(target, row) {
  const file = await fileFromSource(row);
  assignPickedFile(target, file);
}

function sourceFolderName(row) {
  const id = String(row.folder_id || "");
  const folders = (recordFolders.jobs || []).concat(recordFolders.hsi || [], recordFolders.arch || [], recordFolders.icd || [], recordFolders.bom || []);
  const folder = id ? folders.find((item) => item.id === id) : null;
  return folder ? folder.name : "";
}

function placeChoiceMenu(menu, anchor) {
  const box = anchor.getBoundingClientRect();
  menu.hidden = false;
  menu.style.left = Math.max(8, Math.min(box.left, window.innerWidth - 336)) + "px";
  menu.style.top = (box.bottom + 4) + "px";
  const height = menu.offsetHeight;
  if (box.bottom + 8 + height > window.innerHeight) {
    menu.style.top = Math.max(8, box.top - height - 4) + "px";
  }
}

function reportPickError(target, err) {
  const msg = err.message || String(err);
  if (target === "io-manual" || target === "io-previous" || target === "io-schematic" || target === "io-template") setIoMsg(msg);
  else if (target === "icd-file" || target === "icd-previous") setIcdMsg(msg);
  else if (target === "bom-manuals" || target === "bom-template" || target === "bom-previous") setBomMsg(msg);
  else if (target === "etest-standard" || target === "etest-existing" || target === "etest-rules" || target === "etest-report" || target === "etest-plan") setEtestMsg(msg);
  else if (target === "arch-files") setArchMsg(msg);
  else {
    const host = $("file-info");
    if (host) {
      host.hidden = false;
      host.className = "file-info";
      host.innerHTML = "<p class='fi-est'>" + escText(msg) + "</p>";
    }
  }
}

function openFileChoice(anchor, target, accept, kind) {
  const menu = recordMenuEl();
  const inputId = target === "spec" ? "file" : target;
  const paint = (mode) => {
    if (mode === "root" && target === "etest-table") {
      menu.innerHTML = "<button type='button' data-etest-local='1'>" + tx("io.pickLocal") + "</button>"
        + "<button type='button' data-app='1'>" + tx("io.pickApp") + "</button>";
    } else if (mode === "root") {
      menu.innerHTML = "<label class='record-menu-choice' for='" + escText(inputId) + "'>" + tx("io.pickLocal") + "</label>"
        + "<button type='button' data-app='1'>" + tx("io.pickApp") + "</button>";
    } else {
      const rows = storedSources(accept, kind);
      const groups = new Map();
      rows.forEach((row) => {
        const title = sourceFolderName(row);
        const key = title || "";
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(row);
      });
      let html = "<button type='button' data-back='1'>" + tx("io.pickBack") + "</button>";
      if (!rows.length) html += "<p class='record-menu-empty'>" + tx("io.noSource") + "</p>";
      groups.forEach((items, title) => {
        if (title && groups.size > 1) html += "<p class='record-menu-title'>" + escText(title) + "</p>";
        items.forEach((row) => {
          const name = String(row.source || "");
          html += "<button type='button' data-source-id='" + escText(row.id) + "' title='" + escText(name) + "'>" + escText(name) + "</button>";
        });
      });
      menu.innerHTML = html;
      menu._sourceRows = rows;
    }
    placeChoiceMenu(menu, anchor);
  };
  menu.onclick = (ev) => {
    if (ev.target.closest(".record-menu-choice")) {
      ev.stopPropagation();
      menu.hidden = true;
      return;
    }
    const btn = ev.target.closest("button");
    if (!btn || !menu.contains(btn)) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (btn.hasAttribute("data-etest-local")) {
      menu.hidden = true;
      pickEtestLocal();
      return;
    }
    if (btn.hasAttribute("data-app")) {
      paint("app");
      return;
    }
    if (btn.hasAttribute("data-back")) {
      paint("root");
      return;
    }
    const sourceId = btn.getAttribute("data-source-id");
    if (!sourceId) return;
    menu.hidden = true;
    const row = (menu._sourceRows || []).find((entry) => String(entry.id) === sourceId);
    if (!row) return;
    useStoredSource(target, row).catch((err) => reportPickError(target, err));
  };
  paint("root");
}

document.querySelectorAll(".io-file-box[data-target]").forEach((box) => {
  if (box.getAttribute("data-target") === "etest-table") {
    box.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      pickEtestLocal();
    }, true);
    return;
  }
  box.addEventListener("click", (ev) => {
    if (ev.target.closest("button, input")) return;
    ev.preventDefault();
    ev.stopPropagation();
    openFileChoice(box, box.getAttribute("data-target") || "", box.getAttribute("data-accept") || "pdf", box.getAttribute("data-kind") || "jobs");
  });
});

$("io-manual").addEventListener("change", () => {
  syncIoFileName($("io-manual"), $("io-manual-name"));
  const manual = $("io-manual").files && $("io-manual").files[0];
  loadIoPackages(manual || null);
});
$("io-schematic").addEventListener("change", () => {
  const file = $("io-schematic").files && $("io-schematic").files[0];
  const name = file ? file.name.toLowerCase() : "";
  const ok = !file || name.endsWith(".edf") || name.endsWith(".pdf") || name.endsWith(".xlsx") || name.endsWith(".xlsm");
  if (!ok) {
    $("io-schematic").value = "";
    syncIoFileName($("io-schematic"), $("io-schematic-name"));
    setIoMsg(tx("io.schematicType"));
    return;
  }
  syncIoFileName($("io-schematic"), $("io-schematic-name"));
  clearIoDownload();
  setIoMsg("");
  refreshIoGenerate();
});
if ($("io-template")) {
  $("io-template").addEventListener("change", () => {
    const file = selectedIoTemplateFile();
    const name = file ? file.name.toLowerCase() : "";
    if (file && !(name.endsWith(".xlsx") || name.endsWith(".xlsm"))) {
      $("io-template").value = "";
      syncIoFileName($("io-template"), $("io-template-name"));
      setIoMsg(tx("io.needTemplate"));
      refreshIoGenerate();
      return;
    }
    if (file) {
      document.querySelectorAll("#io-template-choices input").forEach((input) => {
        input.checked = false;
      });
    }
    syncIoFileName($("io-template"), $("io-template-name"));
    clearIoDownload();
    setIoMsg("");
    refreshIoGenerate();
  });
}
$("io-previous").addEventListener("change", () => {
  syncIoFileName($("io-previous"), $("io-previous-name"));
  // 换了上一版，上次的结果就不再对应当前输入
  clearIoDownload();
  setIoMsg("");
});
$("io-package-choices").addEventListener("change", () => {
  const status = $("io-package-status");
  if (status && selectedIoPackage()) status.hidden = true;
  clearIoDownload();
  const msg = $("io-msg");
  if (msg && msg.classList.contains("is-ok")) setIoMsg("");
  refreshIoGenerate();
});
if ($("io-template-choices")) {
  $("io-template-choices").addEventListener("change", () => {
    if (selectedIoTemplateId() && $("io-template")) {
      $("io-template").value = "";
      syncIoFileName($("io-template"), $("io-template-name"));
    }
    clearIoDownload();
    setIoMsg("");
    refreshIoGenerate();
  });
}
document.querySelectorAll("input[name=io-mode]").forEach((input) => {
  input.addEventListener("change", () => {
    clearIoDownload();
    setIoMsg("");
    applyIoMode();
  });
});
function setMcuMenu(open) {
  const menu = $("io-mcu-menu");
  const input = $("io-mcu");
  if (!menu || !input) return;
  menu.hidden = !open;
  input.setAttribute("aria-expanded", open ? "true" : "false");
  const current = input.value.trim().toUpperCase();
  menu.querySelectorAll("[data-mcu]").forEach((choice) => {
    const picked = (choice.getAttribute("data-mcu") || "").toUpperCase() === current;
    choice.setAttribute("aria-selected", picked ? "true" : "false");
  });
}

if ($("io-mcu")) {
  $("io-mcu").addEventListener("input", () => {
    clearIoDownload();
    refreshIoGenerate();
  });
  $("io-mcu").addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setMcuMenu(true);
    } else if (event.key === "Escape") {
      setMcuMenu(false);
    }
  });
}
if ($("io-mcu-pick")) {
  $("io-mcu-pick").addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const menu = $("io-mcu-menu");
    setMcuMenu(menu ? menu.hidden : false);
  });
}
if ($("io-mcu-menu")) {
  $("io-mcu-menu").addEventListener("click", (event) => {
    const choice = event.target.closest("[data-mcu]");
    if (!choice || !$("io-mcu")) return;
    $("io-mcu").value = choice.getAttribute("data-mcu") || "";
    $("io-mcu").dispatchEvent(new Event("input", { bubbles: true }));
    setMcuMenu(false);
    $("io-mcu").focus();
  });
}
document.addEventListener("click", (event) => {
  const menu = $("io-mcu-menu");
  if (!menu || menu.hidden) return;
  if (event.target.closest(".io-mcu-combo")) return;
  setMcuMenu(false);
});
applyIoMode();
$("io-back").onclick = () => setPanel("home");
$("io-blank").onclick = async () => {
  clearIoDownload();
  setIoMsg("");
  try {
    const data = await json("/api/io-sheet", { method: "POST" });
    setIoMsg(tx("io.opened"), "ok");
    if (data && data.name) showIoDownload(data, "io.downloadBlank");
  } catch (err) {
    setIoMsg(err.message || String(err));
  }
};
$("io-hsi").onclick = async () => {
  const mode = ioMode();
  const manual = $("io-manual").files && $("io-manual").files[0];
  const schematic = $("io-schematic").files && $("io-schematic").files[0];
  clearIoDownload();
  const body = new FormData();
  body.append("mode", mode);
  const previous = $("io-previous").files && $("io-previous").files[0];
  if (previous) body.append("previous", previous);
  if (mode === "schematic") {
    const schematicName = schematic ? schematic.name.toLowerCase() : "";
    if (!schematic || !(schematicName.endsWith(".edf") || schematicName.endsWith(".pdf"))) {
      setIoMsg(tx("io.needSchematic"));
      return;
    }
    const templateFile = selectedIoTemplateFile();
    const templateId = selectedIoTemplateId();
    if (!templateFile && !templateId) {
      setIoMsg(tx("io.needTemplate"));
      return;
    }
    if (templateFile) body.append("template", templateFile);
    if (templateId) body.append("template_id", templateId);
    body.append("schematic", schematic);
  } else {
    const mcu = $("io-mcu") ? $("io-mcu").value.trim() : "";
    if (!mcu) {
      setIoMsg(tx("io.needMcu"));
      return;
    }
    if (!manual) {
      setIoMsg(tx("io.needManual"));
      return;
    }
    const packageName = selectedIoPackage();
    if (!packageName) {
      setIoMsg(tx("io.needPackage"));
      return;
    }
    body.append("mcu", mcu);
    body.append("datasheet", manual);
    body.append("package", packageName);
  }
  const progressId = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now());
  setIoMsg("");
  showIoProgress(1, ioProgressLabel({ stage: "read", detail: "" }));
  $("io-hsi").disabled = true;
  const blank = $("io-blank");
  if (blank) blank.disabled = true;
  let poll = 0;
  let closed = false;
  const tick = async () => {
    if (closed) return;
    try {
      const resp = await fetch(apiUrl("/api/hsi/progress/" + encodeURIComponent(progressId)), {
        credentials: "same-origin",
        headers: authHeaders(),
      });
      if (!resp.ok || closed) return;
      const payload = await resp.json();
      if (closed || payload.done) {
        closed = true;
        window.clearInterval(poll);
        hideIoProgress();
        return;
      }
      // 文件还在上传时，服务端还没有这条进度，先留着本地的读取提示
      if (!(Number(payload.percent) > 0)) return;
      showIoProgress(payload.percent, ioProgressLabel(payload));
    } catch (e) { /* 进度读不到不影响出表 */ }
  };
  poll = window.setInterval(tick, 400);
  try {
    const resp = await fetch(apiUrl("/api/hsi"), {
      method: "POST",
      credentials: "same-origin",
      headers: Object.assign({ "X-Hsi-Progress": progressId }, authHeaders()),
      body,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const detail = data.detail || data.error || resp.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    let done = data.mode === "schematic"
      ? tx("io.schematicDone", { name: data.name, n: data.schematic_updates })
      : tx(hsiDoneKey(data), {
        name: data.name,
        pins: data.pins,
        changes: data.changes,
      });
    setIoMsg(done, "ok");
    showIoDownload(data);
    loadJobs();
  } catch (err) {
    clearIoDownload();
    setIoMsg(err.message || String(err));
  } finally {
    closed = true;
    window.clearInterval(poll);
    hideIoProgress();
    if (blank) blank.disabled = false;
    refreshIoGenerate();
  }
};

function showIoProgress(percent, label) {
  const box = $("io-progress");
  const bar = $("io-progress-bar");
  const text = $("io-progress-label");
  if (!box || !bar || !text) return;
  box.hidden = false;
  const track = box.querySelector("[role=progressbar]");
  const value = Math.max(0, Math.min(100, Number(percent) || 0));
  bar.style.width = value + "%";
  if (track) track.setAttribute("aria-valuenow", String(value));
  text.textContent = label || "";
}

function hideIoProgress() {
  const box = $("io-progress");
  if (box) box.hidden = true;
}

function ioProgressLabel(payload) {
  const stage = payload && payload.stage ? payload.stage : "read";
  const key = stage === "read" && ioMode() === "schematic" ? "io.progress.readNet" : "io.progress." + stage;
  return tx(key, { detail: (payload && payload.detail) || "" }).replace(/\s+$/, "");
}
$("io-dl").addEventListener("click", async (ev) => {
  const link = ev.currentTarget;
  const api = desktopSave();
  if (!api) return;
  ev.preventDefault();
  const href = link.getAttribute("href") || "";
  const name = decodeURIComponent(href.split("/").pop() || "");
  try {
    const out = await api.save_sheet(name, "Excel (*.xlsx)");
    if (out && out.canceled) return;
    if (out && out.ok) return;
    throw new Error((out && out.error) || tx("err.save"));
  } catch (e) {
    setIoMsg(e.message || String(e));
  }
});
// 架构填报：多选需求 PDF，出材料对照稿。只摘原文，不写满足结论。
function syncArchResult() {
  const row = $("arch-result");
  const msg = $("arch-msg");
  const link = $("arch-dl");
  if (!row) return;
  const msgOn = !!(msg && !msg.hidden && String(msg.textContent || "").trim());
  const dlOn = !!(link && !link.hidden);
  row.hidden = !(msgOn || dlOn);
}

function setArchMsg(text, kind) {
  const msg = $("arch-msg");
  if (!msg) return;
  msg.classList.remove("is-info", "is-ok");
  if (kind) msg.classList.add("is-" + kind);
  msg.textContent = text || "";
  msg.hidden = !String(text || "").trim();
  syncArchResult();
}

function clearArchDownload() {
  const link = $("arch-dl");
  if (!link) return;
  link.hidden = true;
  link.removeAttribute("href");
  syncArchResult();
}

function showArchDownload(data) {
  const link = $("arch-dl");
  const name = data && data.name ? String(data.name) : "";
  if (!link || !name) {
    clearArchDownload();
    return;
  }
  const path = data.download || ("/files/" + encodeURIComponent(name));
  link.href = apiUrl(path);
  link.textContent = tx("arch.download");
  link.hidden = false;
  syncArchResult();
}

// 原生文件框每次选择都会替换上一次，这里自己累积：一次选一个也能攒成一批。
let archPicked = [];

function archFiles() {
  return archPicked.slice();
}

function addArchFiles(incoming) {
  const seen = new Set(archPicked.map((f) => f.name + "\u0000" + f.size));
  let added = 0;
  Array.from(incoming || []).forEach((f) => {
    const key = f.name + "\u0000" + f.size;
    if (seen.has(key)) return;
    seen.add(key);
    archPicked.push(f);
    added += 1;
  });
  return added;
}

function removeArchFile(index) {
  archPicked.splice(index, 1);
  clearArchDownload();
  setArchMsg("");
  renderArchFiles();
}

function renderArchFiles() {
  const files = archFiles();
  const nameEl = $("arch-files-name");
  const list = $("arch-file-list");
  if (nameEl) {
    if (files.length) {
      nameEl.removeAttribute("data-i18n");
      nameEl.textContent = tx("arch.picked", { n: files.length });
      nameEl.classList.add("is-set");
    } else {
      nameEl.setAttribute("data-i18n", "io.fileNone");
      nameEl.textContent = tx("io.fileNone");
      nameEl.classList.remove("is-set");
    }
  }
  if (list) {
    list.hidden = !files.length;
    list.innerHTML = files.map((f, i) => "<li title='" + escText(f.name) + "'><span>" + escText(f.name) + "</span>"
      + "<button type='button' class='arch-file-remove' data-index='" + i + "' aria-label='" + escText(tx("arch.remove")) + "' title='" + escText(tx("arch.remove")) + "'>&times;</button></li>").join("");
    list.querySelectorAll(".arch-file-remove").forEach((btn) => {
      btn.addEventListener("click", () => removeArchFile(Number(btn.getAttribute("data-index"))));
    });
  }
  const btn = $("arch-build");
  if (btn) btn.disabled = !files.length;
  // 两份以上才给「清空」；单份直接点 × 就行
  const clear = $("arch-clear");
  if (clear) clear.hidden = files.length < 2;
}

function clearArchFiles() {
  archPicked = [];
  clearArchDownload();
  setArchMsg("");
  renderArchFiles();
}

$("arch-clear").addEventListener("click", (ev) => {
  // 按钮在文件框的 label 里：拦住默认行为，别顺手弹出选择文件
  ev.preventDefault();
  ev.stopPropagation();
  clearArchFiles();
});

$("arch-files").addEventListener("change", () => {
  const input = $("arch-files");
  addArchFiles(input.files);
  // 清掉原生选择，同一个文件移除后还能再选
  input.value = "";
  clearArchDownload();
  setArchMsg("");
  renderArchFiles();
});
$("arch-back").onclick = () => setPanel("home");
function showArchProgress(percent, label) {
  const box = $("arch-progress");
  const bar = $("arch-progress-bar");
  const text = $("arch-progress-label");
  if (!box || !bar || !text) return;
  box.hidden = false;
  const track = box.querySelector("[role=progressbar]");
  const value = Math.max(0, Math.min(100, Number(percent) || 0));
  bar.style.width = value + "%";
  if (track) track.setAttribute("aria-valuenow", String(value));
  text.textContent = label || "";
}

function hideArchProgress() {
  const box = $("arch-progress");
  if (box) box.hidden = true;
}

function archProgressLabel(payload) {
  const stage = payload && payload.stage ? payload.stage : "text";
  return tx("arch.progress." + stage, { detail: (payload && payload.detail) || "" }).replace(/\s+$/, "");
}

$("arch-build").onclick = async () => {
  const files = archFiles();
  clearArchDownload();
  if (!files.length) {
    setArchMsg(tx("arch.needFiles"));
    return;
  }
  const body = new FormData();
  files.forEach((f) => body.append("files", f));
  const progressId = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now());
  setArchMsg("");
  showArchProgress(1, tx("arch.progress.text", { detail: "" }));
  $("arch-build").disabled = true;
  let poll = 0;
  let closed = false;
  const tick = async () => {
    if (closed) return;
    try {
      const resp = await fetch(apiUrl("/api/arch/progress/" + encodeURIComponent(progressId)), {
        credentials: "same-origin",
        headers: authHeaders(),
      });
      if (!resp.ok || closed) return;
      const payload = await resp.json();
      if (closed || payload.done) {
        closed = true;
        window.clearInterval(poll);
        hideArchProgress();
        return;
      }
      showArchProgress(payload.percent, archProgressLabel(payload));
    } catch (e) { /* 进度读不到不影响出表 */ }
  };
  poll = window.setInterval(tick, 400);
  try {
    const resp = await fetch(apiUrl("/api/arch"), {
      method: "POST",
      credentials: "same-origin",
      headers: Object.assign({ "X-Arch-Progress": progressId }, authHeaders()),
      body,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const detail = data.detail || data.error || resp.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    let text = tx("arch.done", { name: data.name, files: data.files, rows: data.rows, tables: data.tables || 0 });
    if (typeof data.reqs === "number") text += " " + tx("arch.reqs", { n: data.reqs, shots: data.shots || 0 });
    if (data.image_tables) text += " " + tx("arch.ocr", { n: data.image_tables });
    if (data.figures) text += " " + tx("arch.figures", { n: data.figures });
    if (typeof data.params === "number") {
      text += " " + tx(data.conflicts ? "arch.paramsDiff" : "arch.params", { params: data.params, conflicts: data.conflicts || 0 });
    }
    if (data.tbd_count) {
      text += " " + tx("arch.tbd", { n: data.tbd_count });
    }
    if (data.quality_summary && (data.bilingual_conflicts || data.logic_conflicts)) {
      text += " " + data.quality_summary;
    }
    const skipped = Array.isArray(data.unreadable) ? data.unreadable : [];
    if (skipped.length) {
      text += " " + tx("arch.unreadable", { n: skipped.length, names: skipped.map((u) => u.name).join("、") });
    }
    setArchMsg(text, "ok");
    showArchDownload(data);
    loadJobs();
  } catch (err) {
    clearArchDownload();
    const raw = String((err && err.message) || err || "");
    const down = /load failed|failed to fetch|networkerror/i.test(raw);
    setArchMsg(down ? "本机服务中断了，没有生成结果。请重新打开客户端后再点生成。" : raw);
  } finally {
    closed = true;
    window.clearInterval(poll);
    hideArchProgress();
    renderArchFiles();
  }
};
function setBomMsg(text, kind) {
  const msg = $("bom-msg");
  const box = $("bom-result");
  if (!msg || !box) return;
  box.hidden = !text;
  msg.hidden = !text;
  msg.textContent = text || "";
  msg.className = "msg" + (kind === "ok" ? " is-ok" : "");
}

function clearBomDownload() {
  const link = $("bom-dl");
  if (!link) return;
  link.hidden = true;
  link.removeAttribute("href");
  link.textContent = "";
}

function showBomDownload(data) {
  const link = $("bom-dl");
  if (!link || !data || !data.download) return;
  link.hidden = false;
  link.href = apiUrl(data.download);
  link.textContent = tx("bom.download");
}

function refreshBomGenerate() {
  $("bom-build").disabled = false;
}

$("bom-manuals").addEventListener("change", () => {
  const input = $("bom-manuals");
  const nameEl = $("bom-manuals-name");
  const files = input.files ? Array.from(input.files) : [];
  const bad = files.some((file) => {
    const name = file.name.toLowerCase();
    return !(name.endsWith(".pdf") || name.endsWith(".docx") || name.endsWith(".xlsx") || name.endsWith(".xlsm") || name.endsWith(".edf"));
  });
  if (bad) {
    input.value = "";
    syncIoFileName(input, nameEl);
    setBomMsg(tx("bom.manualType"));
    refreshBomGenerate();
    return;
  }
  const count = files.length;
  if (count > 1) {
    nameEl.removeAttribute("data-i18n");
    nameEl.textContent = tx("bom.picked", { n: count });
    nameEl.classList.add("is-set");
  } else {
    syncIoFileName(input, nameEl);
  }
  clearBomDownload();
  setBomMsg("");
  refreshBomGenerate();
});
if ($("bom-previous")) {
  $("bom-previous").addEventListener("change", () => {
    syncIoFileName($("bom-previous"), $("bom-previous-name"));
    clearBomDownload();
    setBomMsg("");
  });
}
$("bom-back").onclick = () => setPanel("home");
$("bom-build").onclick = async () => {
  const manuals = $("bom-manuals").files;
  const body = new FormData();
  if (manuals && manuals.length) Array.from(manuals).forEach((file) => body.append("manuals", file));
  const previous = $("bom-previous") && $("bom-previous").files && $("bom-previous").files[0];
  if (previous) body.append("previous", previous);
  $("bom-build").disabled = true;
  clearBomDownload();
  setBomMsg(tx("bom.working"), "ok");
  try {
    const resp = await fetch(apiUrl("/api/ce-bom"), {
      method: "POST",
      credentials: "same-origin",
      headers: authHeaders(),
      body,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const detail = data.detail || data.error || resp.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    setBomMsg(tx(data.standard ? "bom.doneStandard" : "bom.done", data), "ok");
    showBomDownload(data);
  } catch (err) {
    clearBomDownload();
    setBomMsg(err.message || String(err));
  } finally {
    refreshBomGenerate();
  }
};
function setEtestMsg(text, kind) {
  const msg = $("etest-msg");
  const box = $("etest-result");
  if (!msg || !box) return;
  box.hidden = !text;
  msg.hidden = !text;
  msg.textContent = text || "";
  msg.className = "msg" + (kind === "ok" ? " is-ok" : "");
}

function bindEtestLink(id, href, label) {
  const link = $(id);
  if (!link) return;
  if (!href) {
    link.hidden = true;
    link.removeAttribute("href");
    link.textContent = "";
    return;
  }
  link.hidden = false;
  link.href = apiUrl(href);
  link.textContent = label;
}

function clearEtestDownload() {
  bindEtestLink("etest-dl", "", "");
  bindEtestLink("etest-report-dl", "", "");
  bindEtestLink("etest-plan-dl", "", "");
}

function showEtestDownload(data) {
  if (!data) return;
  bindEtestLink("etest-dl", data.download, tx("etest.download"));
  bindEtestLink("etest-report-dl", data.report_download, tx("etest.reportDownload"));
  bindEtestLink("etest-plan-dl", data.plan_download, tx("etest.planDownload"));
}

function renderEtestSheet(reply, tables) {
  const log = $("etest-log");
  if (!log) return;
  log.replaceChildren();
  if (reply) {
    const text = document.createElement("p");
    text.className = "etest-turn is-assistant";
    text.textContent = reply;
    log.append(text);
  }
  for (const sheet of tables || []) {
    const block = document.createElement("div");
    block.className = "etest-sheet";
    const caption = document.createElement("strong");
    caption.textContent = sheet.title || "";
    const wrap = document.createElement("div");
    wrap.className = "etest-table-wrap";
    const table = document.createElement("table");
    table.className = "etest-table";
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const name of sheet.headers || []) {
      const cell = document.createElement("th");
      cell.textContent = name;
      headRow.append(cell);
    }
    head.append(headRow);
    const body = document.createElement("tbody");
    for (const values of sheet.rows || []) {
      const line = document.createElement("tr");
      for (const value of values) {
        const cell = document.createElement("td");
        cell.textContent = value == null ? "" : String(value);
        line.append(cell);
      }
      body.append(line);
    }
    table.append(head, body);
    wrap.append(table);
    block.append(caption, wrap);
    log.append(block);
  }
}

let etestFile = null;
let etestBytes = null;
let etestRead = null;
let etestReadError = "";
let etestHold = "";

function refreshEtestCompare() {
  $("etest-send").disabled = !etestHold && !etestBytes;
}

$("etest-table").addEventListener("change", () => {
  const input = $("etest-table");
  const file = input.files && input.files[0];
  const name = (file && file.name || "").toLowerCase();
  const ok = !file || [".xlsx", ".xlsm", ".docx", ".txt", ".md"].some((suffix) => name.endsWith(suffix));
  etestHold = "";
  etestFile = null;
  etestBytes = null;
  etestReadError = "";
  etestRead = null;
  if (file && !ok) {
    input.value = "";
    setEtestMsg(tx("etest.tableType"));
  } else if (file) {
    etestFile = file;
    setEtestMsg("已选中 " + file.name + "。", "ok");
    etestRead = copyEtestFile(file);
  } else {
    setEtestMsg("");
  }
  syncIoFileName(input, $("etest-table-name"));
  refreshEtestCompare();
});

const ETEST_TRACE = [
  ["read", "接收测试表"],
  ["extract", "抽出标准号和文件名"],
  ["open", "打开网址"],
  ["find", "查找检索"],
  ["search", "按标准号和文件名检索"],
  ["file", "读取标准文件"],
  ["write", "写出对比表"],
];

function etestStepLabel(id) {
  const found = ETEST_TRACE.find((item) => item[0] === id);
  return found ? found[1] : id;
}

function renderEtestTrace(current, states, detail) {
  const list = $("etest-trace");
  if (!list) return;
  list.hidden = false;
  list.replaceChildren();
  const known = states || {};
  for (const [id, label] of ETEST_TRACE) {
    const li = document.createElement("li");
    const state = known[id] || "wait";
    li.className = "is-" + state;
    li.textContent = id === current && detail ? label + "：" + detail : label;
    list.append(li);
  }
}

renderEtestTrace("", {}, "");

function showEtestResult(data) {
  renderEtestSheet(data.reply || "", data.tables || []);
  showEtestDownload({ download: data.download || "" });
  setEtestMsg(data.page_note || data.reply || "", "ok");
}

const etestDetectLines = [];

function renderEtestDetect() {
  const box = $("etest-detect-text");
  if (!box) return;
  box.textContent = etestDetectLines.length ? etestDetectLines.join("\n") : "还没有记录。";
  box.scrollTop = box.scrollHeight;
}

function etestDetect(line) {
  const text = String(line || "").trim();
  if (!text || etestDetectLines.indexOf(text) >= 0) return;
  etestDetectLines.push(text);
  renderEtestDetect();
  const panel = $("etest-detect");
  if (panel && /(?:^|\s)ok=0(?:\s|$)/.test(text)) panel.open = true;
}

function etestStamp() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate())
    + " " + pad(now.getHours()) + ":" + pad(now.getMinutes()) + ":" + pad(now.getSeconds());
}

function etestSay(fields) {
  if (fields.say) return String(fields.say);
  const event = fields.event;
  const ok = String(fields.ok) !== "0";
  const message = String(fields.message || "");
  if (event === "start") return "开始提交。使用选中时复制进内存的副本，不再读取原文件。";
  if (event === "pick") return "已选中测试表。马上复制进内存，这一步不等任务号。";
  if (event === "job") return "本机服务已建立任务。下一步把测试表读进内存再上传。任务号是 " + (fields.job || "") + "。";
  if (event === "memory" && ok) return "浏览器已把测试表完整读进内存，共 " + fields.bytes + " 字节。接下来上传的是这份内存副本。";
  if (event === "memory" && fields.error === "NotReadableError") {
    return "浏览器读不出文件内容。报 NotReadableError：选中文件之后权限变了。常见是 Excel 还开着这份表，或文件被占用。";
  }
  if (event === "memory") return "浏览器读不出文件内容。错误是 " + (fields.error || "Error") + "。" + message;
  if (event === "upload-file") return "内存读取失败，改为直接提交原文件。若文件仍被占用，上传会没有 HTTP 回应。";
  if (event === "upload" && ok) return "上传请求已得到成功回应。";
  if (event === "upload" && Number(fields.status) === 0) {
    const sent = fields.sent == null ? "未知" : String(fields.sent);
    return "上传没有得到任何 HTTP 回应（status=0，ready=4 表示请求已结束）。已发出 " + sent + " 字节。本机服务若没有「已接到上传」，文件就没进到服务。上一条若是读不出文件，发送时文件仍不可读。";
  }
  if (event === "upload") return "上传失败。HTTP 状态是 " + fields.status + "。" + message;
  if (event === "reject") return "测试表超过 80MB，没有提交。";
  if (event === "network") return "建立任务的请求没有被本机服务接住。" + message;
  if (event === "poll") return "轮询本机服务失败，停在「" + (fields.name || "") + "」。" + message;
  if (event === "done" && ok) return "对比结束。" + message;
  if (event === "done") return "对比停住。" + message;
  if (event === "error") return "这一步出错。" + message;
  return "";
}

function etestLog(fields) {
  const row = Object.assign({}, fields);
  const resetLog = !!row.resetLog;
  delete row.resetLog;
  if (!row.say) row.say = etestSay(row);
  const order = ["side", "event", "step", "name", "state", "ok", "say", "job", "file", "bytes", "mime", "modified", "error", "status", "ready", "sent", "message", "detail"];
  const keys = order.filter((key) => row[key] != null && String(row[key]) !== "");
  Object.keys(row).forEach((key) => {
    if (keys.indexOf(key) < 0 && row[key] != null && String(row[key]) !== "") keys.push(key);
  });
  const text = keys.map((key) => {
    const value = String(row[key]).replace(/\s+/g, " ").trim();
    const shown = /[\s"=]/.test(value) ? '"' + value.replace(/"/g, "'") + '"' : value;
    return key + "=" + shown;
  }).join(" ");
  etestDetect(etestStamp() + "  " + text);
  const headers = { "Content-Type": "application/json", ...authHeaders() };
  if (resetLog) headers["X-Etest-Reset"] = "1";
  return fetch(apiUrl("/api/enterprise-test/detect"), {
    method: "POST",
    credentials: "same-origin",
    headers,
    body: JSON.stringify({ line: text }),
  }).then(async (resp) => {
    const data = await resp.json().catch(() => ({}));
    if (data.detect_file) {
      const file = $("etest-detect-file");
      if (file) file.textContent = "本机文件：" + data.detect_file;
    }
  }).catch(() => {});
}

function etestFileFields(file) {
  const modified = file && file.lastModified ? new Date(file.lastModified) : null;
  const pad = (n) => String(n).padStart(2, "0");
  return {
    file: (file && file.name) || "",
    bytes: file ? file.size : "",
    mime: (file && file.type) || "none",
    modified: modified
      ? modified.getFullYear() + "-" + pad(modified.getMonth() + 1) + "-" + pad(modified.getDate())
        + " " + pad(modified.getHours()) + ":" + pad(modified.getMinutes())
      : "",
  };
}

function readEtestBuffer(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error("FileReader"));
    reader.readAsArrayBuffer(file);
  });
}

async function copyEtestFile(file) {
  const fields = etestFileFields(file);
  etestLog({
    side: "page",
    event: "pick",
    step: "read",
    name: "接收测试表",
    ok: 1,
    ...fields,
  });
  let buffer = null;
  let how = "";
  try {
    buffer = await file.arrayBuffer();
    how = "arrayBuffer";
  } catch (err) {
    etestLog({
      side: "page",
      event: "memory",
      step: "read",
      name: "接收测试表",
      ok: 0,
      error: (err && err.name) || "Error",
      message: String((err && err.message) || err || ""),
      say: "选中当下 arrayBuffer 读不出。接着用 FileReader 再读一次，仍然不上传。",
      ...fields,
    });
    try {
      buffer = await readEtestBuffer(file);
      how = "FileReader";
    } catch (second) {
      if (etestFile !== file) return;
      etestBytes = null;
      etestReadError = "浏览器读不出这份表。请重新点选文件，由本机直接读，Excel 开着也可以。";
      etestLog({
        side: "page",
        event: "memory",
        step: "read",
        name: "接收测试表",
        ok: 0,
        error: (second && second.name) || "Error",
        message: String((second && second.message) || second || ""),
        say: etestReadError,
        ...fields,
      });
      setEtestMsg(etestReadError);
      refreshEtestCompare();
      return;
    }
  }
  if (etestFile !== file) return;
  etestBytes = buffer;
  etestReadError = "";
  etestLog({
    ...fields,
    side: "page",
    event: "memory",
    step: "read",
    name: "接收测试表",
    ok: 1,
    bytes: buffer.byteLength,
    say: "选中时已复制进内存，共 " + buffer.byteLength + " 字节，方式是 " + how + "。提交时上传这份副本。",
  });
  setEtestMsg("测试表已复制进内存，可以读取。", "ok");
  refreshEtestCompare();
}

function takeEtestDetect(data) {
  if (!data) return;
  if (data.detect_file) {
    const file = $("etest-detect-file");
    if (file) file.textContent = "本机文件：" + data.detect_file;
  }
  for (const line of data.detect || []) etestDetect(line);
}

async function intakeEtest() {
  etestDetectLines.length = 0;
  renderEtestDetect();
  etestLog({
    side: "page",
    event: "pick",
    step: "read",
    name: "接收测试表",
    ok: 1,
    say: "请在弹出的窗口里选择测试表。本机直接读文件，不经过浏览器。",
  });
  renderEtestTrace("read", { read: "run" }, "正在打开本机文件窗口");
  setEtestMsg("请在弹出的窗口里选择测试表。", "ok");
  $("etest-send").disabled = true;
  let resp;
  try {
    resp = await fetch(apiUrl("/api/enterprise-test/intake"), {
      method: "POST",
      credentials: "same-origin",
      headers: authHeaders(),
    });
  } catch (err) {
    etestLog({
      side: "page",
      event: "network",
      step: "read",
      name: "接收测试表",
      ok: 0,
      error: (err && err.name) || "Error",
      message: String((err && err.message) || err || ""),
      say: "本机文件窗口没有打开，请求没有被本机服务接住。",
    });
    setEtestMsg("本机文件窗口没有打开。");
    refreshEtestCompare();
    return;
  }
  const data = await resp.json().catch(() => ({}));
  takeEtestDetect(data);
  if (data.cancelled) {
    etestLog({ side: "page", event: "reject", step: "read", name: "接收测试表", ok: 0, say: "没有选择文件。" });
    setEtestMsg("没有选择文件。");
    refreshEtestCompare();
    return;
  }
  if (!resp.ok || !data.ok) {
    const detail = data.detail || data.error || "测试表没有读入。";
    const say = typeof detail === "string" ? detail : JSON.stringify(detail);
    etestLog({ side: "page", event: "error", step: "read", name: "接收测试表", ok: 0, say: say, message: say });
    renderEtestTrace("read", { read: "fail" }, "");
    setEtestMsg(say);
    refreshEtestCompare();
    return;
  }
  etestHold = data.hold_id || "";
  const label = $("etest-table-name");
  if (label) label.textContent = data.name || "已读入";
  etestLog({
    side: "page",
    event: "memory",
    step: "extract",
    name: "抽出标准号和文件名",
    ok: 1,
    file: data.name || "",
    bytes: data.bytes || 0,
    say: data.say || "输入完成。",
  });
  renderEtestTrace("extract", { read: "done", extract: "done" }, (data.rows || 0) + " 行");
  setEtestMsg(data.say || "输入完成。", "ok");
  refreshEtestCompare();
}

function beginEtestRunSurface() {
  etestDetectLines.length = 0;
  renderEtestDetect();
  renderEtestSheet("", []);
  renderEtestTrace("", {}, "");
  clearEtestDownload();
}

async function sendHeldEtest(keepLog) {
  const hold = etestHold;
  if (!keepLog) beginEtestRunSurface();
  await etestLog({
    side: "page",
    event: "start",
    step: "extract",
    name: "抽出标准号和文件名",
    ok: 1,
    say: "测试表已读完。开始打开 http://arsm.aurobaytech.com/home/index ，按标准号检索。",
    resetLog: !keepLog,
  });
  $("etest-send").disabled = true;
  clearEtestDownload();
  renderEtestSheet("", []);
  setEtestMsg("正在生成对比表。", "ok");
  let opened;
  try {
    const resp = await fetch(apiUrl("/api/enterprise-test/compare"), {
      method: "POST",
      credentials: "same-origin",
      headers: { ...authHeaders(), "X-Hold-Id": hold },
    });
    opened = await resp.json().catch(() => ({}));
    if (!resp.ok || !opened.job_id) {
      const detail = opened.detail || opened.error || resp.statusText || "本机没有开始后续步骤。";
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
  } catch (err) {
    const raw = String((err && err.message) || err || "");
    etestLog({ side: "page", event: "error", step: "extract", name: "抽出标准号和文件名", ok: 0, message: raw, say: raw });
    setEtestMsg(raw);
    refreshEtestCompare();
    return;
  }
  etestHold = "";
  takeEtestDetect(opened);
  const jobId = opened.job_id;
  let current = opened.step || "extract";
  let lastStates = opened.steps || { read: "done", extract: "run" };
  renderEtestTrace(current, lastStates, opened.detail || "");
  const timer = window.setInterval(async () => {
    try {
      const resp = await fetch(apiUrl("/api/enterprise-test/compare/" + jobId), {
        credentials: "same-origin",
        headers: authHeaders(),
      });
      const polled = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(polled.detail || polled.error || resp.statusText);
      current = polled.step || current;
      lastStates = polled.steps || lastStates;
      renderEtestTrace(current, lastStates, polled.detail || "");
      takeEtestDetect(polled);
      if (!polled.done) {
        setEtestMsg("进行到「" + etestStepLabel(current) + "」。", "ok");
        return;
      }
      window.clearInterval(timer);
      if (polled.error) {
        setEtestMsg("停在「" + etestStepLabel(current) + "」。" + polled.error);
        etestLog({ side: "page", event: "done", step: current, name: etestStepLabel(current), ok: 0, message: polled.error });
      } else {
        showEtestResult(polled);
        etestLog({ side: "page", event: "done", step: "write", name: "写出对比表", ok: 1, message: String(polled.reply || "").split("\n")[0] });
      }
      refreshEtestCompare();
    } catch (err) {
      window.clearInterval(timer);
      lastStates[current] = "fail";
      renderEtestTrace(current, lastStates, "");
      setEtestMsg("停在「" + etestStepLabel(current) + "」之后，本机服务没有回应。");
      etestLog({ side: "page", event: "poll", step: current, name: etestStepLabel(current), ok: 0, error: (err && err.name) || "Error", message: String((err && err.message) || err || "") });
      refreshEtestCompare();
    }
  }, 1000);
}

function showPickedEtest(data) {
  etestHold = data.hold_id || "";
  etestBytes = null;
  etestRead = null;
  etestReadError = "";
  etestFile = { name: data.name || "", size: data.bytes || 0, type: "", lastModified: Date.now() };
  const nameEl = $("etest-table-name");
  if (nameEl) {
    nameEl.removeAttribute("data-i18n");
    nameEl.textContent = data.name || "";
    nameEl.classList.add("is-set");
  }
  takeEtestDetect(data);
  etestLog({
    side: "page",
    event: "memory",
    step: "read",
    name: "接收测试表",
    ok: 1,
    file: data.name || "",
    bytes: data.bytes || 0,
    say: data.say || "本机已读入测试表。",
  });
  setEtestMsg(data.say || "测试表已从本机读入。可以生成对比表。", "ok");
  refreshEtestCompare();
}

async function pickEtestLocal() {
  setEtestMsg("正在打开本机文件窗口。直接按共享方式读，Excel 开着也可以。", "ok");
  $("etest-send").disabled = true;
  try {
    const resp = await fetch(apiUrl("/api/enterprise-test/pick"), {
      method: "POST",
      credentials: "same-origin",
      headers: authHeaders(),
    });
    const data = await resp.json().catch(() => ({}));
    if (data.cancelled) {
      setEtestMsg(etestHold ? "没有更换文件。" : (etestReadError || "没有选择文件。"), etestHold ? "ok" : "");
      refreshEtestCompare();
      return;
    }
    if (!resp.ok || !data.ok) {
      const detail = data.detail || data.error || resp.statusText || "本机没有读入测试表。";
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    showPickedEtest(data);
  } catch (err) {
    const raw = String((err && err.message) || err || "");
    setEtestMsg(raw === "Failed to fetch" ? "本机服务没有打开文件窗口。请确认窗口还开着后再选一次。" : raw);
    refreshEtestCompare();
  }
}

async function sendEtestCompare() {
  if (etestHold && !etestBytes) {
    await sendHeldEtest();
    return;
  }
  const file = $("etest-table").files && $("etest-table").files[0];
  if (!file) {
    setEtestMsg(tx("etest.needTable"));
    return;
  }
  if (etestRead) await etestRead;
  if (!etestBytes) {
    const say = etestReadError || "这份表还没读进本机。请用「从本机选择」再选一次。";
    setEtestMsg(say);
    etestLog({
      side: "page",
      event: "reject",
      step: "read",
      name: "接收测试表",
      ok: 0,
      say: say,
      ...etestFileFields(file),
    });
    refreshEtestCompare();
    return;
  }
  const body = new FormData();
  body.append("file", new File([etestBytes], file.name, { type: file.type || "application/octet-stream", lastModified: file.lastModified }));
  beginEtestRunSurface();
  await etestLog({
    ...etestFileFields(file),
    side: "page",
    event: "start",
    step: "read",
    name: "接收测试表",
    ok: 1,
    bytes: etestBytes.byteLength,
    say: "按电子电器同一方式提交测试表。提交的是选中时复制的内存副本，共 " + etestBytes.byteLength + " 字节。",
    resetLog: true,
  });
  $("etest-send").disabled = true;
  renderEtestTrace("read", { read: "run" }, "正在生成对比表");
  setEtestMsg("正在生成对比表。", "ok");
  try {
    const resp = await fetch(apiUrl("/api/enterprise-test/intake"), {
      method: "POST",
      credentials: "same-origin",
      headers: authHeaders(),
      body,
    });
    const data = await resp.json().catch(() => ({}));
    takeEtestDetect(data);
    if (!resp.ok || !data.ok) {
      const detail = data.detail || data.error || resp.statusText || "测试表没有读入。";
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    etestHold = data.hold_id || "";
    etestLog({
      side: "page",
      event: "memory",
      step: "extract",
      name: "抽出标准号和文件名",
      ok: 1,
      file: data.name || file.name,
      bytes: data.bytes || file.size,
      say: data.say || "输入完成。",
    });
    renderEtestTrace("extract", { read: "done", extract: "run" }, (data.rows || 0) + " 行");
    setEtestMsg("测试表已读完，开始打开标准站。", "ok");
    if (etestHold) {
      await sendHeldEtest(true);
      return;
    }
    refreshEtestCompare();
  } catch (err) {
    renderEtestTrace("read", { read: "fail" }, "");
    const raw = String((err && err.message) || err || "");
    const say = raw === "Failed to fetch"
      ? "测试表没有送到本机服务。请确认窗口还开着后再点一次生成对比表。"
      : raw;
    setEtestMsg(say);
    etestLog({
      side: "page",
      event: "error",
      step: "read",
      name: "接收测试表",
      ok: 0,
      message: raw,
      say: say,
    });
    refreshEtestCompare();
  }
}

async function sendEtestCompareHeldUnused() {
  const file = etestFile;
  if (!file) {
    setEtestMsg(tx("etest.needTable"));
    return;
  }
  if (etestRead) await etestRead;
  if (!etestBytes) {
    const say = etestReadError || "没有内存副本。不建立任务，也不上传。请关掉 Excel 后重新选择这份表。";
    setEtestMsg(say);
    etestLog({
      side: "page",
      event: "reject",
      step: "read",
      name: "接收测试表",
      ok: 0,
      error: "no-bytes",
      say: say,
      ...etestFileFields(file),
    });
    return;
  }
  if (etestBytes.byteLength > 80 * 1024 * 1024) {
    setEtestMsg("测试表超过 80MB，没有提交。");
    etestLog({ side: "page", event: "reject", step: "read", name: "接收测试表", ok: 0, file: file.name, bytes: etestBytes.byteLength, error: "too-large" });
    return;
  }
  const body = new Blob([etestBytes], { type: "application/octet-stream" });
  etestDetectLines.length = 0;
  renderEtestDetect();
  etestLog({
    ...etestFileFields(file),
    side: "page",
    event: "start",
    step: "read",
    name: "接收测试表",
    ok: 1,
    bytes: body.size,
    say: "开始提交。使用选中时复制的 " + body.size + " 字节，不再读取原文件。",
  });
  $("etest-send").disabled = true;
  clearEtestDownload();
  renderEtestSheet("", []);
  renderEtestTrace("read", { read: "run" }, "正在建立任务");
  setEtestMsg("正在建立任务。", "ok");
  fetch(apiUrl("/api/enterprise-test/compare"), {
    method: "POST",
    credentials: "same-origin",
    headers: authHeaders(),
  }).then(async (resp) => {
    const opened = await resp.json().catch(() => ({}));
    if (!resp.ok || !opened.job_id) {
      const detail = opened.detail || opened.error || resp.statusText || "本机没有返回任务号。";
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return opened;
  }).then(async (opened) => {
    takeEtestDetect(opened);
    etestLog({ side: "page", event: "job", step: "read", name: "接收测试表", ok: 1, job: opened.job_id });
    renderEtestTrace("read", opened.steps || { read: "run" }, "任务已建立，正在交内存副本");
    setEtestMsg("任务已建立，正在提交内存里的测试表。", "ok");
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", apiUrl("/api/enterprise-test/compare/" + opened.job_id + "/file"));
    xhr.withCredentials = true;
    const headers = authHeaders();
    if (headers.Authorization) xhr.setRequestHeader("Authorization", headers.Authorization);
    xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    let sentBytes = 0;
    xhr.upload.onloadstart = () => {
      etestLog({
        side: "page",
        event: "upload",
        step: "read",
        name: "接收测试表",
        ok: 1,
        bytes: body.size || file.size,
        say: "浏览器开始把文件正文发给本机服务。",
      });
    };
    xhr.upload.onprogress = (ev) => {
      sentBytes = ev.loaded;
      if (!ev.lengthComputable) return;
      const sent = (ev.loaded / 1048576).toFixed(1);
      const total = (ev.total / 1048576).toFixed(1);
      renderEtestTrace("read", { read: "run" }, `已上传 ${sent}/${total} MB`);
      setEtestMsg(`正在接收测试表，已上传 ${sent}/${total} MB。`, "ok");
    };
    xhr.onerror = async () => {
      try {
        const resp = await fetch(apiUrl("/api/enterprise-test/compare/" + opened.job_id), {
          credentials: "same-origin",
          headers: authHeaders(),
        });
        takeEtestDetect(await resp.json().catch(() => ({})));
      } catch (err) {}
      renderEtestTrace("read", { read: "fail" }, "");
      setEtestMsg("停在「接收测试表」。上传没有得到 HTTP 回应，本机服务没有收下文件。");
      etestLog({
        side: "page",
        event: "upload",
        step: "read",
        name: "接收测试表",
        ok: 0,
        status: xhr.status,
        ready: xhr.readyState,
        sent: sentBytes,
        message: xhr.statusText || "no-response",
        detail: String(xhr.responseText || "").slice(0, 160),
        ...etestFileFields(file),
      });
      refreshEtestCompare();
    };
  xhr.onload = () => {
    let data = {};
    try {
      data = JSON.parse(xhr.responseText || "{}");
    } catch (err) {
      data = {};
    }
      if (xhr.status < 200 || xhr.status >= 300) {
        const detail = data.detail || data.error || xhr.statusText || "接收测试表失败";
        renderEtestTrace("read", { read: "fail" }, "");
        setEtestMsg(typeof detail === "string" ? detail : JSON.stringify(detail));
        etestLog({
          side: "page",
          event: "upload",
          step: "read",
          name: "接收测试表",
          ok: 0,
          status: xhr.status,
          message: typeof detail === "string" ? detail : JSON.stringify(detail),
        });
        refreshEtestCompare();
        return;
      }
      takeEtestDetect(data);
      etestLog({
        side: "page",
        event: "upload",
        step: "read",
        name: "接收测试表",
        ok: 1,
        status: xhr.status,
        say: "上传得到 HTTP " + xhr.status + "。测试表已交给本机服务，开始轮询抽出、检索和写表。",
      });
    const jobId = data.job_id || opened.job_id;
    renderEtestTrace(data.step || "read", data.steps || { read: "done" }, data.detail || "");
    let current = "read";
    let lastStates = data.steps || { read: "done" };
    const timer = window.setInterval(async () => {
      try {
        const resp = await fetch(apiUrl("/api/enterprise-test/compare/" + jobId), {
          credentials: "same-origin",
          headers: authHeaders(),
        });
        const polled = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          throw new Error(polled.detail || polled.error || resp.statusText);
        }
          current = polled.step || current;
          lastStates = polled.steps || lastStates;
          renderEtestTrace(current, lastStates, polled.detail || "");
          takeEtestDetect(polled);
        if (!polled.done) {
          setEtestMsg("进行到「" + etestStepLabel(current) + "」。", "ok");
          return;
        }
        window.clearInterval(timer);
          if (polled.error) {
            setEtestMsg("停在「" + etestStepLabel(current) + "」。" + polled.error);
            etestLog({ side: "page", event: "done", step: current, name: etestStepLabel(current), ok: 0, message: polled.error });
          } else {
            showEtestResult(polled);
            etestLog({ side: "page", event: "done", step: "write", name: "写出对比表", ok: 1, message: String(polled.reply || "").split("\n")[0] });
          }
        refreshEtestCompare();
      } catch (err) {
        window.clearInterval(timer);
        lastStates[current] = "fail";
        renderEtestTrace(current, lastStates, "");
        setEtestMsg("停在「" + etestStepLabel(current) + "」之后，本机服务没有回应。");
        etestLog({ side: "page", event: "poll", step: current, name: etestStepLabel(current), ok: 0, error: (err && err.name) || "Error", message: String((err && err.message) || err || "") });
        refreshEtestCompare();
      }
    }, 1000);
  };
    xhr.send(body);
  }).catch((err) => {
    renderEtestTrace("read", { read: "fail" }, "");
    const raw = String((err && err.message) || err || "");
    const down = /load failed|failed to fetch|networkerror/i.test(raw);
    setEtestMsg(down ? "停在「接收测试表」。请求没有被本机服务接住。" : raw);
    etestLog({
      side: "page",
      event: down ? "network" : "error",
      step: "read",
      name: "接收测试表",
      ok: 0,
      error: (err && err.name) || "Error",
      message: raw,
    });
    refreshEtestCompare();
  });
}

$("etest-detect-copy").onclick = async () => {
  const text = etestDetectLines.join("\n") || "还没有记录。";
  try {
    await navigator.clipboard.writeText(text);
    const file = $("etest-detect-file");
    if (file) file.textContent = "已复制。把这段检测日志发回来即可。";
  } catch (err) {
    const box = $("etest-detect-text");
    if (!box) return;
    const range = document.createRange();
    range.selectNodeContents(box);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }
};

$("etest-back").onclick = () => setPanel("home");
$("etest-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  sendEtestCompare();
});
async function saveEtestLink(ev) {
  const link = ev.currentTarget;
  const api = desktopSave();
  if (!api) return;
  ev.preventDefault();
  const href = link.getAttribute("href") || "";
  const name = decodeURIComponent(href.split("/").pop() || "");
  const filter = name.toLowerCase().endsWith(".docx") ? "Word (*.docx)" : "Excel (*.xlsx)";
  try {
    const out = await api.save_sheet(name, filter);
    if (out && out.canceled) return;
    if (out && out.ok) return;
    throw new Error((out && out.error) || tx("err.save"));
  } catch (e) {
    setEtestMsg(e.message || String(e));
  }
}
for (const id of ["etest-dl", "etest-report-dl", "etest-plan-dl"]) {
  const link = $(id);
  if (link) link.addEventListener("click", saveEtestLink);
}
$("bom-dl").addEventListener("click", async (ev) => {
  const link = ev.currentTarget;
  const api = desktopSave();
  if (!api) return;
  ev.preventDefault();
  const href = link.getAttribute("href") || "";
  const name = decodeURIComponent(href.split("/").pop() || "");
  try {
    const out = await api.save_sheet(name, "Excel (*.xlsx)");
    if (out && out.canceled) return;
    if (out && out.ok) return;
    throw new Error((out && out.error) || tx("err.save"));
  } catch (e) {
    setBomMsg(e.message || String(e));
  }
});
function setIcdMsg(text, kind) {
  const msg = $("icd-msg");
  const box = $("icd-result");
  if (!msg || !box) return;
  box.hidden = !text;
  msg.hidden = !text;
  msg.textContent = text || "";
  msg.className = "msg" + (kind === "ok" ? " is-ok" : "");
}

function clearIcdDownload() {
  const link = $("icd-dl");
  if (!link) return;
  link.hidden = true;
  link.removeAttribute("href");
  link.textContent = "";
}

function showIcdDownload(data) {
  const link = $("icd-dl");
  if (!link || !data || !data.download) return;
  link.hidden = false;
  link.href = apiUrl(data.download);
  link.textContent = tx("icd.download");
}

function refreshIcdGenerate() {
  const file = $("icd-file").files && $("icd-file").files[0];
  $("icd-build").disabled = !file;
}

$("icd-file").addEventListener("change", () => {
  syncIoFileName($("icd-file"), $("icd-file-name"));
  clearIcdDownload();
  setIcdMsg("");
  refreshIcdGenerate();
});
$("icd-previous").addEventListener("change", () => {
  syncIoFileName($("icd-previous"), $("icd-previous-name"));
  clearIcdDownload();
  setIcdMsg("");
});
$("icd-back").onclick = () => setPanel("home");
$("icd-build").onclick = async () => {
  const file = $("icd-file").files && $("icd-file").files[0];
  if (!file) {
    setIcdMsg(tx("icd.needFile"));
    return;
  }
  const previous = $("icd-previous").files && $("icd-previous").files[0];
  const body = new FormData();
  body.append("file", file);
  if (previous) body.append("previous", previous);
  $("icd-build").disabled = true;
  clearIcdDownload();
  setIcdMsg(tx("icd.working"), "ok");
  try {
    const resp = await fetch(apiUrl("/api/icd"), {
      method: "POST",
      credentials: "same-origin",
      headers: authHeaders(),
      body,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const detail = data.detail || data.error || resp.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    let text = tx("icd.done", { name: data.name, pins: data.pins, parts: data.parts, hv: data.hv });
    if (previous) text += " " + tx(data.changes ? "icd.changes" : "icd.noChanges", { n: data.changes || 0 });
    setIcdMsg(text, "ok");
    showIcdDownload(data);
  } catch (err) {
    clearIcdDownload();
    setIcdMsg(err.message || String(err));
  } finally {
    refreshIcdGenerate();
  }
};
$("icd-dl").addEventListener("click", async (ev) => {
  const link = ev.currentTarget;
  const api = desktopSave();
  if (!api) return;
  ev.preventDefault();
  const href = link.getAttribute("href") || "";
  const name = decodeURIComponent(href.split("/").pop() || "");
  try {
    const out = await api.save_sheet(name, "Excel (*.xlsx)");
    if (out && out.canceled) return;
    if (out && out.ok) return;
    throw new Error((out && out.error) || tx("err.save"));
  } catch (e) {
    setIcdMsg(e.message || String(e));
  }
});
$("arch-dl").addEventListener("click", async (ev) => {
  const link = ev.currentTarget;
  const api = desktopSave();
  if (!api) return;
  ev.preventDefault();
  const href = link.getAttribute("href") || "";
  const name = decodeURIComponent(href.split("/").pop() || "");
  try {
    const out = await api.save_sheet(name, "Excel (*.xlsx)");
    if (out && out.canceled) return;
    if (out && out.ok) return;
    throw new Error((out && out.error) || tx("err.save"));
  } catch (e) {
    setArchMsg(e.message || String(e));
  }
});
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
function openPicker(anchor) {
  openFileChoice(anchor || pick, "spec", "spec", "jobs");
}
pick.addEventListener("click", (ev) => {
  ev.stopPropagation();
  openPicker(pick);
});
drop.addEventListener("click", (ev) => {
  if (ev.target.closest("button, a, input, select")) return;
  ev.stopPropagation();
  openPicker(drop);
});
drop.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openPicker(drop); }
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

function loadAbout() {
  const client = document.querySelector('[data-about="client"]');
  const version = lastHealth && lastHealth.versions && lastHealth.versions.client;
  if (client && version) client.textContent = version;
}

function showSettingsTab(name) {
  document.querySelectorAll(".settings-tab").forEach((t) => {
    t.classList.toggle("is-on", t.getAttribute("data-tab") === name);
  });
  document.querySelectorAll(".settings-panel").forEach((panel) => {
    panel.hidden = panel.getAttribute("data-panel") !== name;
  });
  if (name === "about") loadAbout();
  if (name === "env") loadEnvironments();
}
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
