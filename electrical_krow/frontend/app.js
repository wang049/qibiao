const $ = (id) => document.getElementById(id);

let loggedIn = false;

function authHeaders() {
  return loggedIn ? { Authorization: "Bearer local" } : {};
}

async function json(url, opts) {
  const extra = opts || {};
  const { headers, ...rest } = extra;
  const resp = await fetch(url, {
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
  extract: $("st-extract"),
  write: $("st-write"),
};
let chosen = null;
let llmOk = false;
let currentJob = null;
let runPaused = false;
let delivery = "client";

function isSite() {
  return delivery === "site";
}

function applyShellCopy() {
  const sub = $("brand-sub");
  if (sub) sub.textContent = isSite() ? "场所网页" : "本机工位";
  const hint = $("drop-hint");
  if (hint) {
    hint.textContent = isSite()
      ? "文件上传到本场所服务器，不超过 80MB"
      : "文件只在本机读取，不超过 80MB";
  }
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
  const order = ["read", "ocr", "extract", "write"];
  let hit = order.indexOf(stage);
  if (hit < 0) hit = 0;
  order.forEach((key, i) => {
    steps[key].className = "step" + (i < hit ? " done" : i === hit ? " on" : "");
  });
}
async function pollJob(id) {
  let last = null;
  for (let i = 0; i < 6; i++) {
    try {
      const pr = await fetch("/api/jobs/" + id, {
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
      opt.textContent = name;
      sel.appendChild(opt);
    });
  }
  sel.value = current || list[0] || "";
}

async function loadModels() {
  if (!loggedIn) return;
  try {
    const data = await json("/api/models");
    fillModels(data.models || [], data.model || "");
  } catch {
    fillModels([], $("model") && $("model").value);
  }
}

async function showWork(on, username) {
  loggedIn = on;
  $("login-card").hidden = on;
  $("work-card").hidden = !on;
  $("who-wrap").hidden = !on;
  $("logout").hidden = !on;
  document.querySelector("main")?.classList.toggle("is-work", on);
  if (on) $("who").textContent = username || "";
  $("kicker").textContent = on ? "出表核对" : (isSite() ? "场所登录" : "工位登录");
  $("title").innerHTML = on
    ? "导入规格书，<span>出核对表</span>"
    : "登录后<span>出表</span>";
  $("lead").textContent = on
    ? (isSite()
        ? "将 PDF、Word 或 Excel 拖入下方。文件上传到本场所服务器，不出公网。"
        : "将 PDF、Word 或 Excel 拖入下方。文件只在本机读取。")
    : "请使用开通的邮箱和密码，不要填手机号。";
  go.disabled = !(chosen && llmOk && loggedIn);
  if (on) await loadModels();
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
    if (h.busy) ready = "服务就绪 · 当前有任务在出表，请排队";
    $("health-text").textContent = h.ok ? ready : (h.detail || "识别服务未就绪");
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
  try {
    const body = {
      username: $("user").value,
      password: $("pass").value,
    };
    const data = await json("/api/login", { method: "POST", body: JSON.stringify(body) });
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
  await showWork(false, "");
  await refresh();
};

function revealResult() {
  $("work-card")?.classList.add("has-result");
  requestAnimationFrame(() => {
    result.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
}

function desktopSave() {
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
  if (!name) return;
  try {
    await json("/api/model", { method: "POST", body: JSON.stringify({ model: name }) });
    await refresh();
  } catch (err) {
    status.className = "status err";
    status.textContent = String(err.message || err);
  }
});

go.addEventListener("click", async () => {
  if (!chosen) return;
  currentJob = null;
  runPaused = false;
  setRunButtons(true, false, false);
  result.classList.remove("show");
  result.innerHTML = "";
  $("work-card")?.classList.remove("has-result");
  progress.classList.add("show");
  barfill.style.width = "2%";
  setStage("read");
  const t0 = Date.now();
  status.className = "status";
  status.textContent = "已接收文件，开始读取…  ·  已用 0 秒";
  const body = new FormData();
  body.append("file", chosen);
  let tick = setInterval(() => {
    if (!status.dataset.stage) return;
    status.textContent = status.dataset.stage + "  ·  已用 " + fmtElapsed((Date.now() - t0) / 1000);
  }, 1000);
  try {
    const started = await fetch("/api/jobs", {
      method: "POST",
      body,
      credentials: "same-origin",
      headers: authHeaders(),
    });
    const job = await started.json();
    if (!started.ok) throw new Error(job.detail || "无法开始出表");
    currentJob = job.id;
    while (true) {
      await new Promise((r) => setTimeout(r, 800));
      const { pr, data } = await pollJob(job.id);
      if (!pr.ok) throw new Error(data.detail || "查询进度失败");
      const pct = Math.max(0, Math.min(100, data.percent || 0));
      barfill.style.width = pct + "%";
      setStage(data.stage || "extract");
      status.dataset.stage = data.message || "正在出表…";
      status.textContent = status.dataset.stage + "  ·  已用 " + fmtElapsed((Date.now() - t0) / 1000);
      const st = data.status || "";
      runPaused = st === "paused" || st === "pausing";
      setRunButtons(true, runPaused, st === "stopping");
      if (st === "done") {
        status.dataset.stage = "";
        const elapsed = fmtElapsed(data.elapsed_seconds);
        status.textContent = (data.stopped_early ? "已按已抽出内容出表" : "出表完成")
          + "  ·  已用 " + elapsed;
        barfill.style.width = "100%";
        setStage("write");
        steps.write.className = "step done";
        const filled = (data.filled != null) ? data.filled : "—";
        const extract = data.extract !== false;
        const found = extract
          ? ((data.found != null) ? data.found : filled)
          : "—";
        const partial = extract
          ? ((data.partial != null) ? data.partial : "—")
          : "—";
        const miss = extract
          ? ((data.miss != null) ? data.miss : "—")
          : "—";
        let tip = "";
        if (data.stopped_early) {
          tip = "已结束抽取。核对表按当前已抽出内容生成，未抽完的条目仍为空。";
        } else if (!extract && data.kind_note) {
          tip = data.kind_note;
        }
        const heading = data.stopped_early ? "已按已抽出内容出表" : "核对表已生成";
        result.className = "result show";
        result.innerHTML =
          "<div class='result-head'>" +
          "<h2>" + heading + "</h2>" +
          "<a class='dl' href='" + data.download + "' download>下载核对表</a>" +
          "</div>" +
          "<div class='stats'>" +
          "<div class='stat'><b>" + elapsed + "</b><span>耗时</span></div>" +
          "<div class='stat'><b>" + found + "</b><span>已检索到</span></div>" +
          "<div class='stat'><b>" + partial + "</b><span>局部对应</span></div>" +
          "<div class='stat'><b>" + miss + "</b><span>未检索到</span></div>" +
          "</div>" +
          (tip ? "<p class='result-note'>" + tip + "</p>" : "");
        revealResult();
        break;
      }
      if (st === "error") throw new Error(data.detail || "出表失败");
    }
  } catch (e) {
    status.className = "status err";
    status.dataset.stage = "";
    status.textContent = explainErr(e);
    result.className = "result fail show";
    result.innerHTML = "<h2>未能完成出表</h2><p class='result-note'>" + explainErr(e) + "</p>";
    revealResult();
  } finally {
    clearInterval(tick);
    currentJob = null;
    runPaused = false;
    setRunButtons(false, false, false);
    go.disabled = !(chosen && llmOk && loggedIn);
  }
});

async function sendControl(action) {
  if (!currentJob) return;
  const res = await fetch("/api/jobs/" + currentJob + "/" + action, {
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

refresh();
