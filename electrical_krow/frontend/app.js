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
  const arch = on && workPanel === "arch";
  $("home-card").hidden = !home;
  $("work-card").hidden = !extract;
  $("kb-card").hidden = !kb;
  $("io-card").hidden = !io;
  $("icd-card").hidden = !icd;
  $("bom-card").hidden = !bom;
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
  $("rail-arch")?.classList.toggle("is-on", arch);
  $("rail-kb")?.classList.toggle("is-on", kb);
  if (io) setRailRecordTab("hsi");
  else if (icd) setRailRecordTab("icd");
  else if (bom) setRailRecordTab("bom");
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
let recordFolders = { jobs: [], hsi: [], arch: [], icd: [], bom: [] };
let icdRows = [];
let bomRows = [];
let icdSources = [];
let bomSources = [];
let recordNote = null;
let recordOpen = {};
let recordDraft = null;

function renderByKind(kind) {
  if (kind === "hsi") renderHsi();
  else if (kind === "arch") renderArch();
  else if (kind === "icd") renderSheetRecords("icd");
  else if (kind === "bom") renderSheetRecords("bom");
  else renderJobs();
}

function recordListId(kind) {
  return { hsi: "hsi-list", arch: "arch-list", icd: "icd-list", bom: "bom-list" }[kind] || "job-list";
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

function folderIsOpen(kind, id, rows) {
  const key = kind + ":" + id;
  if (Object.prototype.hasOwnProperty.call(recordOpen, key)) return !!recordOpen[key];
  const active = viewingJob || currentJob || "";
  return kind === "jobs" && rows.some((row) => String(row.id || "") === active);
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
  return "<div class='job-folder-bar'>"
    + "<button type='button' class='job-new-folder' data-kind='" + escText(kind) + "'>" + tx("record.newFolder") + "</button>"
    + "<button type='button' class='job-add-source' data-kind='" + escText(kind) + "'>" + tx("record.addSource") + "</button>"
    + "<input class='job-source-input' type='file' hidden accept='.pdf,.docx,.xlsx,.xlsm,application/pdf' />"
    + "</div>" + note;
}

function fillRecordHost(host, kind, rows, cardHtml, onEmpty) {
  const folders = recordFolders[kind] || [];
  let html = recordToolbar(kind);
  if (!rows.length && !folders.length) {
    host.innerHTML = html + onEmpty();
    bindRecordChrome(host, kind);
    return;
  }
  html += layoutRecords(rows, kind).map((block) => {
    if (block.type === "single") return cardHtml(block.row);
    const open = folderIsOpen(kind, block.id, block.rows);
    const body = block.rows.length
      ? block.rows.map(cardHtml).join("")
      : "<p class='job-folder-empty'>" + tx("record.folderEmpty") + "</p>";
    return "<section class='job-folder" + (open ? " is-open" : "") + "'>"
      + "<button type='button' class='job-folder-head' data-folder='" + escText(kind + ":" + block.id) + "'>"
      + "<span class='job-folder-chev' aria-hidden='true'></span>"
      + "<span class='job-folder-name'>" + escText(block.title) + "</span>"
      + "<span class='job-folder-count'>" + block.rows.length + "</span>"
      + "</button><div class='job-folder-body'>" + body + "</div></section>";
  }).join("");
  host.innerHTML = html;
  bindRecordChrome(host, kind);
}

function bindRecordChrome(host, kind) {
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
    if (kind === "bom" && row.rows) bits.push(tx("arch.rows", { n: row.rows }));
    const meta = "<span class='job-meta'><span class='job-meta-text'>" + escText(bits.join(" · ")) + "</span></span>";
    const kindLabel = kind === "bom" ? tx("record.kind.bom") : tx("record.kind.icd");
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
    const [data, hsi, arch, icd, bom] = await Promise.all([
      json("/api/jobs"),
      json("/api/hsi/history").catch(() => ({ records: [] })),
      json("/api/arch/history").catch(() => ({ records: [] })),
      json("/api/icd/history").catch(() => ({ records: [] })),
      json("/api/ce-bom/history").catch(() => ({ records: [] })),
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
    recordFolders = {
      jobs: data.folders || [],
      hsi: hsi.folders || [],
      arch: arch.folders || [],
      icd: icd.folders || [],
      bom: bom.folders || [],
    };
    renderJobs();
    renderHsi();
    renderArch();
    renderSheetRecords("icd");
    renderSheetRecords("bom");
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
  const pick = ["hsi", "arch", "icd", "bom"].includes(tab) ? tab : "jobs";
  const panels = { jobs: $("job-list"), hsi: $("hsi-list"), icd: $("icd-list"), bom: $("bom-list"), arch: $("arch-list") };
  const tabs = { jobs: $("rail-tab-jobs"), hsi: $("rail-tab-hsi"), icd: $("rail-tab-icd"), bom: $("rail-tab-bom"), arch: $("rail-tab-arch") };
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
$("rail-arch").onclick = () => setPanel("arch");
$("rail-kb").onclick = () => setPanel("kb");
$("rail-tab-jobs").onclick = () => setRailRecordTab("jobs");
$("rail-tab-hsi").onclick = () => setRailRecordTab("hsi");
$("rail-tab-icd").onclick = () => setRailRecordTab("icd");
$("rail-tab-bom").onclick = () => setRailRecordTab("bom");
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
  refreshIoGenerate();
}

function refreshIoGenerate() {
  const btn = $("io-hsi");
  if (!btn) return;
  if (ioMode() === "schematic") {
    const file = $("io-schematic") && $("io-schematic").files && $("io-schematic").files[0];
    const name = file ? file.name.toLowerCase() : "";
    btn.disabled = !(name.endsWith(".edf") || name.endsWith(".pdf"));
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
  const rows = kind === "hsi" ? hsiSources : kind === "arch" ? archSources : kind === "icd" ? icdSources : kind === "bom" ? bomSources : jobSources;
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
  if (target === "io-manual" || target === "io-previous" || target === "io-schematic") setIoMsg(msg);
  else if (target === "icd-file" || target === "icd-previous") setIcdMsg(msg);
  else if (target === "bom-manuals" || target === "bom-template") setBomMsg(msg);
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
    if (mode === "root") {
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
$("bom-back").onclick = () => setPanel("home");
$("bom-build").onclick = async () => {
  const manuals = $("bom-manuals").files;
  const body = new FormData();
  if (manuals && manuals.length) Array.from(manuals).forEach((file) => body.append("manuals", file));
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

function showSettingsTab(name) {
  document.querySelectorAll(".settings-tab").forEach((t) => {
    t.classList.toggle("is-on", t.getAttribute("data-tab") === name);
  });
  document.querySelectorAll(".settings-panel").forEach((panel) => {
    panel.hidden = panel.getAttribute("data-panel") !== name;
  });
  if (name === "about") {
    const client = document.querySelector('[data-about="client"]');
    const version = lastHealth && lastHealth.versions && lastHealth.versions.client;
    if (client && version) client.textContent = version;
  }
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
