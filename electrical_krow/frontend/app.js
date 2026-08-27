const $ = (id) => document.getElementById(id);

async function json(url, opts) {
  const resp = await fetch(url, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(opts && opts.headers) },
    ...opts,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const msg = data.detail || data.error || resp.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

async function refresh() {
  const health = $("health");
  try {
    const h = await json("/api/health");
    health.className = "health " + (h.ok ? "ok" : "bad");
    $("health-text").textContent = h.ok
      ? (h.logged_in ? "识别已就绪 · 已登录" : "识别已就绪 · 请登录")
      : h.detail || "识别服务未就绪";
  } catch (err) {
    health.className = "health bad";
    $("health-text").textContent = String(err.message || err);
  }
  try {
    const s = await json("/api/session");
    showChat(Boolean(s.logged_in), s.username || "");
  } catch {
    showChat(false, "");
  }
}

function showChat(on, username) {
  $("login-card").hidden = on;
  $("chat-card").hidden = !on;
  if (on) $("who").textContent = username;
}

$("login").onclick = async () => {
  const msg = $("login-msg");
  msg.hidden = true;
  try {
    const body = {
      username: $("user").value,
      password: $("pass").value,
      api_key: $("key").value,
    };
    const data = await json("/api/login", { method: "POST", body: JSON.stringify(body) });
    showChat(true, data.username);
    await refresh();
  } catch (err) {
    msg.hidden = false;
    msg.textContent = String(err.message || err);
  }
};

$("logout").onclick = async () => {
  await json("/api/logout", { method: "POST", body: "{}" });
  showChat(false, "");
  await refresh();
};

$("send").onclick = async () => {
  const out = $("out");
  out.textContent = "发送中…";
  try {
    const data = await json("/v1/chat/completions", {
      method: "POST",
      body: JSON.stringify({
        messages: [{ role: "user", content: $("prompt").value }],
        temperature: 0,
      }),
    });
    out.textContent = data.choices[0].message.content;
  } catch (err) {
    out.textContent = String(err.message || err);
  }
};

refresh();
