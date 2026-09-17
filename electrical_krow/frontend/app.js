/* 第 1 项出表功能页。完整客户端由同事 Electron 工程承载。
   嵌入：/?embed=1 ；跨源时加 api=http://127.0.0.1:端口 或 window.ELECTRICAL_API_BASE。 */
const $ = (id) => document.getElementById(id);

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

function isSite() {
  return delivery === "site";
}

function applyShellCopy() {
  const sub = $("brand-sub");
  if (sub) sub.textContent = isSite() ? "场所网页" : "本机工位";
  const railSub = $("rail-sub");
  if (railSub) railSub.textContent = isSite() ? "场所网页" : "本机工位";
  const badge = $("local-badge");
  if (badge) badge.textContent = isSite() ? "场所内处理" : "本机读取";
  const hint = $("drop-hint");
  if (hint) {
    hint.textContent = isSite()
      ? "文件上传到本场所服务器，不超过 80MB"
      : "文件只在本机读取，不超过 80MB";
  }
}

function envCaption(h) {
  if (h && h.environment_label) return h.environment_label;
  const server = String((h && h.server) || "");
  if (server) return server.replace(/^https?:\/\//, "");
  return "未设置";
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
  pauseBtn.textContent = paused ? "继续" : "暂停";
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
  return m ? (m + " 分 " + s + " 秒") : (s + " 秒");
}
function explainErr(e) {
  const msg = (e && e.message) ? e.message : String(e);
  if (msg === "Failed to fetch" || msg === "Load failed" || msg.indexOf("NetworkError") >= 0) {
    return isSite()
      ? "与场所页面断开。请刷新后重新出表。"
      : "与本机页面断开。请刷新后重新出表。";
  }
  return msg;
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
  throw last || new Error("查询进度失败");
}

// 推荐模型（服务端配置默认）；下拉里在名字后加「（推荐）」，value 仍是原名
let recommendedModel = "";
function modelLabel(name) {
  return name && name === recommendedModel ? name + "（推荐）" : name;
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
    opt.textContent = current || "登录后加载模型";
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
    av.textContent = ch ? ch.toUpperCase() : "工";
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
  $("home-card").hidden = !home;
  $("work-card").hidden = !extract;
  $("kb-card").hidden = !kb;
  document.body.classList.toggle("is-logged", on);
  document.body.classList.toggle("is-home", home);
  document.body.classList.toggle("is-kb", kb);
  document.querySelector("main")?.classList.toggle("is-work", on);
  document.querySelector("main")?.classList.toggle("is-kb", kb);
  $("rail-home")?.classList.toggle("is-on", home);
  $("rail-extract")?.classList.toggle("is-on", extract);
  $("rail-kb")?.classList.toggle("is-on", kb);
  if (!on) {
    $("kicker").textContent = isSite() ? "场所登录" : "工位登录";
    $("title").innerHTML = "登录后<span>出表</span>";
    $("lead").textContent = "请使用开通的邮箱和密码，不要填手机号。";
    return;
  }
  if (home) {
    $("kicker").textContent = "工位工作台";
    $("title").innerHTML = "你好，我是<span>电子电器智能体</span>";
    $("lead").textContent = "登录后选择功能、提交当份材料，按既定步骤生成输出物。不由模型自行规划路径。同一时刻只处理一份任务。";
    return;
  }
  if (kb) {
    $("kicker").textContent = "场所知识库";
    $("title").innerHTML = "电机控制器<span>知识库</span>";
    $("lead").textContent = "条款、物理关系与禁配已建图谱。抽出值只来自当份规格书，库不提供取值。";
    if (typeof window.kbEnsure === "function") window.kbEnsure();
    return;
  }
  $("kicker").textContent = "出表核对";
  $("title").innerHTML = "导入规格书，<span>出核对表</span>";
  $("lead").textContent = isSite()
    ? "将 PDF、Word 或 Excel 拖入下方。文件上传到本场所服务器，不出公网。"
    : "将 PDF、Word 或 Excel 拖入下方。文件只在本机读取。";
}

function escText(s) {
  return String(s || "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function jobStatusLabel(st) {
  if (st === "done") return { text: "已完成", cls: "done" };
  if (st === "error") return { text: "失败", cls: "fail" };
  if (st === "paused" || st === "pausing") return { text: "已暂停", cls: "run" };
  if (st === "stopping") return { text: "正在结束", cls: "run" };
  if (st === "queued") return { text: "排队中", cls: "run" };
  return { text: "进行中", cls: "run" };
}

function fmtWhen(ts) {
  const n = Number(ts);
  if (!isFinite(n) || n <= 0) return "";
  const d = new Date(n < 1e12 ? n * 1000 : n);
  if (!isFinite(d.getTime())) return "";
  return d.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
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

function renderJobs() {
  const host = $("job-list");
  if (!host) return;
  if (!jobRows.length) {
    host.innerHTML = "<p class='job-empty'>还没有出表任务。</p>";
    return;
  }
  const active = viewingJob || currentJob || "";
  const busy = !!currentJob;
  host.innerHTML = jobRows.map((row) => {
    const id = String(row.id || "");
    const st = jobStatusLabel(row.status || "");
    const name = String(row.source || "规格书");
    const when = fmtWhen(row.created_at);
    const bits = [];
    if (when) bits.push(when);
    if (row.status === "done" && row.found != null) bits.push("已检索到 " + row.found);
    if (row.status === "error" && row.detail) bits.push(String(row.detail).slice(0, 24));
    const on = id && id === active;
    const block = busy && id !== currentJob;
    return "<button type='button' class='job-row" + (on ? " is-on" : "") + "'"
      + " data-id='" + escText(id) + "'"
      + (block ? " disabled" : "") + ">"
      + "<span class='job-status " + st.cls + "'>" + st.text + "</span>"
      + "<span class='job-name'>" + escText(name) + "</span>"
      + "<span class='job-meta'>" + escText(bits.join(" · ") || (row.message || "")) + "</span>"
      + "</button>";
  }).join("");
  host.querySelectorAll(".job-row").forEach((btn) => {
    btn.addEventListener("click", () => openHistory(btn.getAttribute("data-id") || ""));
  });
}

async function loadJobs() {
  if (!loggedIn) return;
  try {
    const data = await json("/api/jobs");
    jobRows = data.jobs || [];
    renderJobs();
  } catch {
    if (!$("job-list").children.length) {
      $("job-list").innerHTML = "<p class='job-empty'>任务记录暂时无法读取。</p>";
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
    tip = "已结束抽取。核对表按当前已抽出内容生成，未抽完的条目仍为空。";
  } else if (!extract && data.kind_note) {
    tip = data.kind_note;
  } else if (Number(data.chunk_failures || 0) > 0) {
    tip = "有 " + Number(data.chunk_failures)
      + " 个分段识别失败，结果可能不完整；请重点复核未检索到和局部对应条目。";
  } else if (extract && Number(data.llm_calls || 0) < 1 && Number(miss) > 0) {
    tip = "识别没有成功调用。请退出后重新登录再出表。";
  }
  const verdict = String(data.qa_verdict || "").trim();
  const qa = String(data.qa_summary || "").trim();
  const qaNote = (
    (verdict === "warn" || verdict === "fail") && qa && qa !== tip
  ) ? ("质检：" + qa) : "";
  const incomplete = Number(data.chunk_failures || 0) > 0;
  const heading = data.stopped_early
    ? "已按已抽出内容出表"
    : (incomplete ? "核对表已生成（识别不完整）" : "核对表已生成");
  const dl = data.download
    ? "<a class='dl' href='" + escText(apiUrl(data.download)) + "' download>下载核对表</a>"
    : "";
  return "<div class='result-head'><h2>" + heading + "</h2>" + dl + "</div>"
    + "<div class='stats'>"
    + "<div class='stat'><b>" + elapsed + "</b><span>耗时</span></div>"
    + "<div class='stat'><b>" + found + "</b><span>已检索到</span></div>"
    + "<div class='stat'><b>" + partial + "</b><span>局部对应</span></div>"
    + "<div class='stat'><b>" + miss + "</b><span>未检索到</span></div>"
    + "</div>"
    + (qaNote || tip
      ? "<p class='result-note'>" + [qaNote, tip].filter(Boolean).join(" ") + "</p>"
      : "");
}

function showFinishedJob(data) {
  progress.classList.add("show");
  barfill.style.width = "100%";
  setStage("write");
  steps.write.className = "step done";
  const elapsed = fmtElapsed(data.elapsed_seconds);
  status.className = "status";
  status.dataset.stage = "";
  status.textContent = (data.stopped_early
    ? "已按已抽出内容出表"
    : (Number(data.chunk_failures || 0) > 0 ? "出表完成 · 识别不完整" : "出表完成"))
    + "  ·  已用 " + elapsed;
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
      result.innerHTML = "<h2>未能完成出表</h2><p class='result-note'>"
        + escText(data.detail || data.message || "出表失败") + "</p>";
      status.className = "status err";
      status.textContent = data.detail || data.message || "出表失败";
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
    delivery = h.delivery === "site" ? "site" : "client";
    applyShellCopy();
    llmOk = !!h.ok;
    health.className = "health " + (h.ok ? "ok" : "err");
    let ready = "服务就绪 · 请登录";
    if (h.logged_in) ready = "服务就绪";
    if (h.busy) ready = "服务就绪 · 当前有任务在出表";
    $("health-text").textContent = h.ok ? ready : (h.detail || "识别服务未就绪");
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
  btn.setAttribute("aria-label", show ? "隐藏密码" : "显示密码");
  btn.title = show ? "隐藏密码" : "显示密码";
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

$("rail-home").onclick = () => setPanel("home");
$("rail-extract").onclick = () => setPanel("extract");
$("rail-kb").onclick = () => setPanel("kb");
$("rail-new").onclick = () => {
  if (!currentJob && !submitting && !attaching) {
    setFile(null);
    if (fileInput) fileInput.value = "";
  }
  setPanel("extract");
};
// 工作台卡片只切页，不自动弹文件选择；选文件由页内拖放区/按钮触发
document.querySelectorAll(".fn-card[data-go]").forEach((btn) => {
  btn.addEventListener("click", () => setPanel(btn.getAttribute("data-go") || "home"));
});

function revealResult() {
  $("work-card")?.classList.add("has-result");
  requestAnimationFrame(() => {
    result.scrollIntoView({ behavior: "smooth", block: "nearest" });
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
      const prev = (status.textContent || "出表完成").replace(/\s*·\s*核对表已保存$/, "");
      status.textContent = prev + "  ·  核对表已保存";
      return;
    }
    throw new Error((out && out.error) || "保存失败");
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
  pick.textContent = chosen ? "更换文件" : "选择文件";
  result.classList.remove("show");
  result.innerHTML = "";
  $("work-card")?.classList.remove("has-result");
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
    if (!pr.ok) throw new Error(detailText(data) || data.detail || "查询进度失败");
    const pct = Math.max(0, Math.min(100, data.percent || 0));
    barfill.style.width = pct + "%";
    setStage(data.stage || "extract");
    status.dataset.stage = data.message || "正在出表…";
    status.textContent = status.dataset.stage + "  ·  已用 " + fmtElapsed((Date.now() - t0) / 1000);
    const st = data.status || "";
    runPaused = st === "paused" || st === "pausing";
    setRunButtons(true, runPaused, st === "stopping" || st === "queued");
    if (st === "done") {
      showFinishedJob(data);
      // 只对本页发起的出表自动打开 / 提醒；刷新后接回的旧任务不打开
      if (startedHere) {
        const sheet = decodeURIComponent(String(data.download || "").split("/").pop() || "");
        finishAlert("出表完成", sheet || "核对表已生成");
        if (prefs.autoOpen === "on" && !embedMode()) openWorkbookLocally(data.download);
      }
      await waitUntilIdle();
      break;
    }
    if (st === "error") {
      const why = detailText(data) || data.detail || "出表失败";
      if (startedHere) finishAlert("出表失败", why);
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
      status.dataset.stage = "上一份正在收尾出表，完成后即可再提交";
      status.textContent = status.dataset.stage;
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
      result.innerHTML = "<h2>未能完成出表</h2><p class='result-note'>" + explainErr(e) + "</p>";
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
  runPaused = false;
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
  status.dataset.stage = "已接收文件，开始读取…";
  status.textContent = status.dataset.stage + "  ·  已用 0 秒";
  let tick = setInterval(() => {
    if (!status.dataset.stage) return;
    status.textContent = status.dataset.stage + "  ·  已用 " + fmtElapsed((Date.now() - t0) / 1000);
  }, 1000);
  try {
    const waitNote = "上一份正在结束，结束后立即开始这份";
    const deadline = Date.now() + 20 * 60 * 1000;
    let job = null;
    while (!job) {
      if (Date.now() > deadline) {
        throw new Error("上一份仍未结束，请稍后再提交。");
      }
      let busy = false;
      try {
        const h = await json("/api/health");
        busy = !!h.busy;
      } catch {
        busy = false;
      }
      if (busy) {
        status.dataset.stage = waitNote;
        status.textContent = waitNote + "  ·  已用 " + fmtElapsed((Date.now() - t0) / 1000);
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
        status.dataset.stage = waitNote;
        status.textContent = waitNote + "  ·  已用 " + fmtElapsed((Date.now() - t0) / 1000);
        setRunButtons(true, false, true);
        await sleep(800);
        continue;
      }
      throw new Error(detailText(payload) || payload.detail || "无法开始出表");
    }
    setRunButtons(true, false, false);
    status.dataset.stage = "已接收文件，开始读取…";
    await followJob(job.id, t0, { startedHere: true });
  } catch (e) {
    status.className = "status err";
    status.dataset.stage = "";
    status.textContent = explainErr(e);
    result.className = "result fail show";
    result.innerHTML = "<h2>未能完成出表</h2><p class='result-note'>" + explainErr(e) + "</p>";
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
  if (!res.ok) throw new Error(data.detail || "操作失败");
  return data;
}
pauseBtn.addEventListener("click", async () => {
  if (!currentJob) return;
  pauseBtn.disabled = true;
  try {
    if (runPaused) {
      await sendControl("resume");
      runPaused = false;
      pauseBtn.textContent = "暂停";
    } else {
      await sendControl("pause");
      runPaused = true;
      pauseBtn.textContent = "继续";
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
    status.dataset.stage = "将在本批结束后结束，并按已抽出内容出表…";
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
  density: "cozy",
  rail: "left",
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
  zoom: ["90", "100", "110", "125"],
  font: ["system", "yahei", "songti", "mono"],
  density: ["cozy", "compact"],
  rail: ["left", "right"],
  autoOpen: ["off", "on"],
  rememberUser: ["off", "on"],
  notify: ["off", "on"],
  sound: ["off", "on"],
  confirmClose: ["off", "on"],
};
// 挂到 <html> 的只有外观 / 布局；出表偏好走请求参数
const PREF_ATTRS = ["theme", "accent", "zoom", "font", "density", "rail"];

function validModelName(v) {
  return typeof v === "string" && v.length > 0 && v.length <= 80 && !/\s/.test(v);
}
const darkQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

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
  // 父壳可用 ?theme= 指定主题（不落盘）
  const forced = themeFromQuery();
  if (forced) out.theme = forced;
  return out;
}

function savePrefs(prefs) {
  const toStore = Object.assign({}, prefs);
  if (themeFromQuery()) delete toStore.theme;
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
    h.setAttribute("data-" + k, v);
  });
}

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
    say("当前窗口不支持系统通知。");
    return;
  }
  if (Notification.permission === "granted") return;
  if (Notification.permission === "denied") {
    say("系统通知已被拒绝，请在系统或浏览器的通知设置里允许本程序。");
    return;
  }
  Notification.requestPermission().then((p) => {
    if (p !== "granted") say("没有拿到通知权限，完成时不会弹系统通知。");
    else say("已允许系统通知。", true);
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
    head.textContent = names.length ? "用服务端默认" : "登录后可选";
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
      opt.textContent = prefs.model + "（当前环境未列出）";
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
  savePrefs(prefs);
  applyPrefs(prefs);
  renderPrefControls();
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
    put("server", (h.environment_label ? h.environment_label + "  " : "") + (h.server || ""));
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
  const text = rows.map((dt) => dt.textContent + "：" + (dt.nextElementSibling?.textContent || "")).join("\n");
  const msg = $("settings-msg");
  try {
    await navigator.clipboard.writeText(text);
    if (msg) { msg.hidden = false; msg.classList.add("is-info"); msg.textContent = "已复制。"; }
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
  box.innerHTML = "<p>正在读取环境…</p>";
  try {
    const data = await json("/api/settings");
    box.innerHTML = "";
    (data.environments || []).forEach((env) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "env-choice" + (env.id === data.id ? " is-on" : "");
      btn.innerHTML = "<strong>" + escText(env.label) + "</strong><span>"
        + escText(env.server) + "</span>";
      btn.addEventListener("click", () => pickEnvironment(env.id));
      box.appendChild(btn);
    });
  } catch (err) {
    box.innerHTML = "";
    msg.hidden = false;
    msg.textContent = String(err.message || err);
  }
}

async function pickEnvironment(id) {
  const msg = $("settings-msg");
  msg.hidden = true;
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
      const note = $("login-msg");
      note.hidden = false;
      note.classList.add("is-info");
      note.textContent = "已切换到" + (data.label || "新环境") + "，请重新登录。";
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

refresh();
