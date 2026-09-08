(() => {
  const $ = (id) => document.getElementById(id);
  const REL_COLOR = {
    related: "#c5ced6",
    not: "#d48a84",
    same_slot: "#c9a36b",
    interprets: "#7eb3c4",
  };
  const REL_RANK = { not: 0, same_slot: 1, interprets: 2, related: 3 };

  let catalog = null;
  let loading = null;
  let bound = false;
  let tab = "dir";
  let groupName = "";
  let selected = null;
  let graphFocus = null;

  function esc(s) {
    return String(s || "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  async function kbJson(url) {
    const href = typeof window.electricalApiUrl === "function" ? window.electricalApiUrl(url) : url;
    const resp = await fetch(href, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Authorization: "Bearer local" },
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data.detail || data.error || resp.statusText || "知识库未能加载");
    }
    return data;
  }

  function fold(s) {
    return String(s || "").toLowerCase().replace(/[\s,，;；~～\-—–]/g, "");
  }

  function clauseBySeq(seq) {
    return (catalog.clauses || []).find((c) => c.seq === Number(seq));
  }

  function physicsById(id) {
    const cid = String(id || "").replace(/^physics:/, "");
    return (catalog.physics || []).find((p) => p.id === cid);
  }

  function selectClause(seq, fromGraph) {
    const row = clauseBySeq(seq);
    if (!row) return;
    selected = { kind: "clause", id: "clause:" + row.seq, seq: row.seq };
    if (!fromGraph) graphFocus = selected;
    if (tab === "dir") {
      renderList();
      renderDetail($("kb-detail"));
      renderMiniGraph();
    }
    if (tab === "graph") {
      graphFocus = selected;
      renderOverviewGraph();
      renderDetail($("kb-graph-detail"));
    }
  }

  function selectPhysics(id) {
    const card = physicsById(id);
    if (!card) return;
    selected = { kind: "physics", id: "physics:" + card.id };
    graphFocus = selected;
    if (tab === "dir") {
      renderDetail($("kb-detail"));
      renderMiniGraph();
    }
    if (tab === "graph") {
      renderOverviewGraph();
      renderDetail($("kb-graph-detail"));
    }
    if (tab === "physics") {
      renderPhysics();
      renderDetail($("kb-phys-detail"));
    }
  }

  function matchesQuery(row, query) {
    if (!query) return true;
    const blob = fold(
      [
        row.seq,
        row.name,
        row.group,
        row.gloss,
        (row.aliases || []).join(" "),
        (row.reject || []).join(" "),
        (row.std || []).join(" "),
      ].join(" ")
    );
    return blob.indexOf(query) >= 0;
  }

  function bindOnce() {
    if (bound) return;
    bound = true;
    $("kb-q").addEventListener("input", () => {
      renderList();
      if (tab === "physics") renderPhysics();
    });
    document.querySelectorAll(".kb-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        tab = btn.getAttribute("data-tab") || "dir";
        document.querySelectorAll(".kb-tab").forEach((b) => {
          b.classList.toggle("is-on", b === btn);
        });
        $("kb-panel-dir").hidden = tab !== "dir";
        $("kb-panel-graph").hidden = tab !== "graph";
        $("kb-panel-physics").hidden = tab !== "physics";
        $("kb-panel-scope").hidden = tab !== "scope";
        if (tab === "graph") {
          graphFocus = { kind: "group", id: "" };
          renderOverviewGraph();
          renderDetail($("kb-graph-detail"));
        }
        if (tab === "physics") {
          renderPhysics();
          renderDetail($("kb-phys-detail"));
        }
      });
    });
  }

  function renderAll() {
    const stats = catalog.stats || {};
    $("kb-version").textContent = "版本 " + (catalog.version || "");
    $("kb-banner").textContent =
      catalog.rule ||
      "抽出值只来自当份规格书。知识库提供条目、互斥与公式关系，不提供取值。";
    $("kb-stats").innerHTML = [
      ["clauses", "条款卡片"],
      ["physics", "物理关系"],
      ["groups", "业务分组"],
      ["edges", "图谱关系"],
      ["retrieve", "已开通检索"],
    ]
      .map(([key, label]) => {
        return `<div class="kb-stat"><b>${esc(stats[key] ?? 0)}</b><span>${label}</span></div>`;
      })
      .join("") +
      `<div class="kb-stat"><b>内部</b><span>密级 · 不出公网</span></div>`;
    renderGroups();
    renderList();
    if (!selected && catalog.clauses && catalog.clauses.length) {
      const first = catalog.clauses.find((c) => c.retrieve) || catalog.clauses[0];
      selected = { kind: "clause", id: "clause:" + first.seq, seq: first.seq };
      graphFocus = selected;
    }
    renderDetail($("kb-detail"));
    renderMiniGraph();
    renderPhysics();
    renderScope();
  }

  function renderGroups() {
    const host = $("kb-groups");
    const items = [{ name: "", count: (catalog.clauses || []).length }, ...(catalog.groups || [])];
    host.innerHTML = items
      .map((g) => {
        const on = (g.name || "") === groupName;
        const label = g.name || "全部";
        return `<button type="button" class="kb-group${on ? " is-on" : ""}" data-group="${esc(g.name || "")}">${esc(label)}<i>${esc(g.count)}</i></button>`;
      })
      .join("");
    host.querySelectorAll(".kb-group").forEach((btn) => {
      btn.addEventListener("click", () => {
        groupName = btn.getAttribute("data-group") || "";
        renderGroups();
        renderList();
      });
    });
  }

  function filteredClauses() {
    const query = fold($("kb-q").value);
    return (catalog.clauses || []).filter((row) => {
      if (groupName && row.group !== groupName) return false;
      return matchesQuery(row, query);
    });
  }

  function renderList() {
    const host = $("kb-list");
    const rows = filteredClauses();
    if (!rows.length) {
      host.innerHTML = `<p class="kb-empty">没有匹配的条款。</p>`;
      return;
    }
    host.innerHTML = rows
      .map((row) => {
        const on = selected && selected.kind === "clause" && selected.seq === row.seq;
        const mark = row.retrieve ? "已开通" : row.status_label || "待确认";
        return `<button type="button" class="kb-row${on ? " is-on" : ""}" data-seq="${row.seq}">
          <b>#${row.seq}</b>
          <span class="kb-row-name">${esc(row.name)}</span>
          <em>${esc(row.group)} · ${esc(mark)}</em>
        </button>`;
      })
      .join("");
    host.querySelectorAll(".kb-row").forEach((btn) => {
      btn.addEventListener("click", () => selectClause(Number(btn.getAttribute("data-seq"))));
    });
  }

  function chips(values, cls) {
    if (!values || !values.length) return "";
    return `<div class="kb-chips">${values
      .map((v) => `<span class="${cls || ""}">${esc(v)}</span>`)
      .join("")}</div>`;
  }

  function relatedHtml(related) {
    if (!related || !related.length) return "";
    return `<ul class="kb-links">${related
      .map((item) => {
        if (item.kind === "physics") {
          return `<li><button type="button" class="kb-link" data-kind="physics" data-id="${esc(item.physics_id)}"><i>${esc(item.rel_label)}</i>${esc(item.name)}${item.law ? " · " + esc(item.law) : ""}</button></li>`;
        }
        return `<li><button type="button" class="kb-link" data-kind="clause" data-seq="${item.seq}"><i>${esc(item.rel_label)}</i>#${item.seq} ${esc(item.name)}</button></li>`;
      })
      .join("")}</ul>`;
  }

  function bindLinks(host) {
    host.querySelectorAll(".kb-link").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.getAttribute("data-kind") === "physics") {
          tabTo("graph");
          selectPhysics(btn.getAttribute("data-id"));
        } else {
          selectClause(Number(btn.getAttribute("data-seq")));
        }
      });
    });
  }

  function tabTo(name) {
    const btn = document.querySelector(`.kb-tab[data-tab="${name}"]`);
    if (btn) btn.click();
  }

  function renderDetail(host) {
    if (!host) return;
    if (!selected) {
      host.innerHTML = `<p class="kb-empty">从左侧选择一条条款。</p>`;
      return;
    }
    if (selected.kind === "physics") {
      const card = physicsById(selected.id);
      if (!card) {
        host.innerHTML = "";
        return;
      }
      const see = (card.see_seq || [])
        .map((seq) => clauseBySeq(seq))
        .filter(Boolean)
        .map((c) => ({ kind: "clause", seq: c.seq, name: c.name, rel_label: "适用条款" }));
      host.innerHTML = `
        <div class="kb-kicker">物理关系</div>
        <h3>${esc(card.title)}</h3>
        <p class="kb-law">${esc(card.law)}</p>
        <div class="kb-flags">
          <span class="kb-chip">${card.derive ? "当份已给量可推算缺项" : "只用于读表 / 校验"}</span>
          <span class="kb-chip warn">不提供抽出值</span>
        </div>
        ${card.gloss ? `<p class="kb-gloss">${esc(card.gloss)}</p>` : ""}
        <h4>关联条款</h4>
        ${relatedHtml(see) || `<p class="kb-empty">暂无直接挂接条款。</p>`}
      `;
      bindLinks(host);
      return;
    }
    const row = clauseBySeq(selected.seq);
    if (!row) {
      host.innerHTML = "";
      return;
    }
    host.innerHTML = `
      <div class="kb-kicker">${esc(row.group)} · #${row.seq}</div>
      <h3>${esc(row.name)}</h3>
      <div class="kb-flags">
        <span class="kb-chip ${row.retrieve ? "ok" : ""}">${esc(row.status_label)}</span>
        <span class="kb-chip">密级 内部</span>
        <span class="kb-chip">知识库 ${esc(catalog.version)}</span>
      </div>
      ${row.gloss ? `<p class="kb-gloss">${esc(row.gloss)}</p>` : ""}
      <p class="kb-cite">出处：电机控制需求清单 #${row.seq}${row.name ? " " + esc(row.name) : ""}；知识库 ${esc(catalog.version)}</p>
      ${row.aliases && row.aliases.length ? `<h4>常见写法</h4>${chips(row.aliases)}` : ""}
      ${row.units && row.units.length ? `<h4>单位形态</h4>${chips(row.units)}` : ""}
      ${row.reject && row.reject.length ? `<h4>禁配 / 易混</h4>${chips(row.reject, "warn")}` : ""}
      ${row.std && row.std.length ? `<h4>适用标准</h4>${chips(row.std)}` : ""}
      <h4>图谱邻域</h4>
      ${relatedHtml(row.related) || `<p class="kb-empty">尚无已登记关联。</p>`}
    `;
    bindLinks(host);
  }

  function renderPhysics() {
    const host = $("kb-physics");
    const query = fold($("kb-q").value);
    const cards = (catalog.physics || []).filter((card) => {
      if (!query) return true;
      return fold([card.title, card.law, card.gloss, (card.see_seq || []).join(" ")].join(" ")).indexOf(query) >= 0;
    });
    host.innerHTML = cards
      .map((card) => {
        const on = selected && selected.kind === "physics" && selected.id === "physics:" + card.id;
        return `<button type="button" class="kb-phys${on ? " is-on" : ""}" data-id="${esc(card.id)}">
          <span class="kb-phys-title">${esc(card.title)}</span>
          <span class="kb-law">${esc(card.law)}</span>
          <span class="kb-phys-meta">${card.derive ? "可推算缺项" : "读表 / 校验"} · 不填数</span>
        </button>`;
      })
      .join("");
    host.querySelectorAll(".kb-phys").forEach((btn) => {
      btn.addEventListener("click", () => {
        selectPhysics(btn.getAttribute("data-id"));
      });
    });
  }

  function renderScope() {
    const scope = catalog.scope || {};
    const answers = (scope.answers || []).map((x) => `<li>${esc(x)}</li>`).join("");
    const doesNot = (scope.does_not || []).map((x) => `<li>${esc(x)}</li>`).join("");
    const sources = (catalog.sources || [])
      .map((s) => {
        return `<article class="kb-source">
          <h4>${esc(s.title)}</h4>
          <p>${esc(s.provided_by || "")}${s.version ? " · " + esc(s.version) : ""} · 密级 ${esc(s.classification || "内部")} · 不出场所</p>
          ${s.used_for ? `<p class="kb-gloss">${esc(s.used_for)}</p>` : ""}
        </article>`;
      })
      .join("");
    $("kb-scope").innerHTML = `
      <div class="kb-scope-grid">
        <section>
          <h3>本库回答什么</h3>
          <ul>${answers}</ul>
        </section>
        <section>
          <h3>明确不做</h3>
          <ul>${doesNot}</ul>
        </section>
      </div>
      <p class="kb-cite">${esc(scope.owner || "")}。${esc(scope.site || "")}</p>
      <h3>来源登记</h3>
      <div class="kb-sources">${sources}</div>
    `;
  }

  function svgEl(name, attrs) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attrs || {}).forEach(([k, v]) => node.setAttribute(k, String(v)));
    return node;
  }

  function layoutRing(items, cx, cy, rx, ry, start) {
    const n = items.length || 1;
    return items.map((item, i) => {
      const a = (start || -Math.PI / 2) + (i * 2 * Math.PI) / n;
      return { ...item, x: cx + rx * Math.cos(a), y: cy + ry * Math.sin(a) };
    });
  }

  function drawGraph(host, spec) {
    host.innerHTML = "";
    const width = Math.max(host.clientWidth || 640, 480);
    const height = spec.height || 420;
    const svg = svgEl("svg", {
      viewBox: `0 0 ${width} ${height}`,
      width: "100%",
      height: String(height),
      role: "img",
    });
    const byId = {};
    (spec.nodes || []).forEach((n) => {
      byId[n.id] = n;
    });
    (spec.edges || []).forEach((e) => {
      const a = byId[e.from];
      const b = byId[e.to];
      if (!a || !b) return;
      const line = svgEl("line", {
        x1: a.x,
        y1: a.y,
        x2: b.x,
        y2: b.y,
        stroke: REL_COLOR[e.rel] || REL_COLOR.related,
        "stroke-width": e.rel === "related" ? 1 : 1.6,
        "stroke-linecap": "round",
      });
      svg.appendChild(line);
    });
    (spec.nodes || []).forEach((n) => {
      const g = svgEl("g", { class: "kb-gn", style: "cursor:pointer" });
      const on = spec.active && spec.active === n.id;
      const fill = n.kind === "physics" ? "#eef6f8" : n.kind === "group" ? "#1e3a4c" : "#fff";
      const stroke = on ? "#1f6f8a" : n.kind === "physics" ? "#1f6f8a" : "#1e3a4c";
      const r = n.kind === "group" ? 22 : n.kind === "physics" ? 16 : 11;
      g.appendChild(
        svgEl("circle", {
          cx: n.x,
          cy: n.y,
          r: on ? r + 3 : r,
          fill,
          stroke,
          "stroke-width": on ? 2.4 : 1.4,
        })
      );
      const label = svgEl("text", {
        x: n.x,
        y: n.y + (n.kind === "group" ? 36 : n.kind === "physics" ? 28 : 22),
        "text-anchor": "middle",
        fill: "#1a2330",
        "font-size": n.kind === "group" ? 11 : 10,
        "font-family": "PingFang SC, Microsoft YaHei, sans-serif",
      });
      label.textContent = n.label;
      g.appendChild(label);
      if (n.kind === "clause" || n.kind === "group") {
        const inner = svgEl("text", {
          x: n.x,
          y: n.y + 4,
          "text-anchor": "middle",
          fill: n.kind === "group" ? "#fff" : "#1e3a4c",
          "font-size": 9,
          "font-weight": 650,
          "font-family": "PingFang SC, Microsoft YaHei, sans-serif",
        });
        inner.textContent = n.mark || "";
        g.appendChild(inner);
      }
      g.addEventListener("click", () => spec.onClick && spec.onClick(n));
      svg.appendChild(g);
    });
    host.appendChild(svg);
    if (spec.legend !== false) {
      const legend = document.createElement("div");
      legend.className = "kb-legend";
      legend.innerHTML =
        `<i class="lg-c"></i>条款 <i class="lg-p"></i>物理 <i class="lg-x"></i>互斥 <i class="lg-n"></i>禁配 <i class="lg-f"></i>公式`;
      host.appendChild(legend);
    }
  }

  function neighborhood(id) {
    const edges = (catalog.graph.edges || [])
      .filter((e) => e.from === id || e.to === id)
      .sort((a, b) => (REL_RANK[a.rel] ?? 9) - (REL_RANK[b.rel] ?? 9))
      .slice(0, 16);
    const ids = new Set([id]);
    edges.forEach((e) => {
      ids.add(e.from);
      ids.add(e.to);
    });
    const nodeMap = {};
    (catalog.graph.nodes || []).forEach((n) => {
      nodeMap[n.id] = n;
    });
    const nodes = [...ids]
      .map((nid) => nodeMap[nid])
      .filter(Boolean)
      .map((n) => ({
        id: n.id,
        kind: n.kind,
        label: n.kind === "physics" ? n.label : "#" + n.seq,
        mark: n.kind === "clause" ? String(n.seq) : "",
        law: n.law || "",
      }));
    return { nodes, edges };
  }

  function renderMiniGraph() {
    const host = $("kb-mini-graph");
    if (!selected) {
      host.innerHTML = "";
      return;
    }
    const nb = neighborhood(selected.id);
    const others = nb.nodes.filter((n) => n.id !== selected.id);
    const cx = Math.max(($("kb-mini-graph").clientWidth || 520) / 2, 240);
    const placed = [
      { ...nb.nodes.find((n) => n.id === selected.id), x: cx, y: 118 },
      ...layoutRing(others, cx, 118, Math.min(cx - 70, 210), 86),
    ].filter(Boolean);
    drawGraph(host, {
      nodes: placed,
      edges: nb.edges,
      height: 250,
      active: selected.id,
      onClick: (n) => {
        if (n.kind === "physics") selectPhysics(n.id);
        else selectClause(Number(String(n.id).split(":")[1]), true);
      },
    });
  }

  function overviewSpec() {
    const groups = catalog.groups || [];
    const width = Math.max(($("kb-graph").clientWidth || 720), 560);
    const height = 460;
    const cx = width / 2;
    const cy = 210;
    const groupNodes = layoutRing(
      groups.map((g) => ({
        id: "group:" + g.name,
        kind: "group",
        label: g.name,
        mark: String(g.count),
        group: g.name,
      })),
      cx,
      cy,
      Math.min(cx - 90, 280),
      150
    );
    const degree = {};
    (catalog.graph.edges || []).forEach((e) => {
      if (e.rel !== "interprets") return;
      const pid = e.from.startsWith("physics:") ? e.from : e.to;
      degree[pid] = (degree[pid] || 0) + 1;
    });
    const topPhys = (catalog.graph.nodes || [])
      .filter((n) => n.kind === "physics")
      .sort((a, b) => (degree[b.id] || 0) - (degree[a.id] || 0))
      .slice(0, 10)
      .map((n) => ({
        id: n.id,
        kind: "physics",
        label: n.label,
        mark: "",
      }));
    const physNodes = layoutRing(topPhys, cx, cy, 110, 70, 0.2);
    const clauseGroup = {};
    (catalog.clauses || []).forEach((c) => {
      clauseGroup["clause:" + c.seq] = c.group;
    });
    const edges = [];
    const seen = new Set();
    (catalog.graph.edges || []).forEach((e) => {
      const g1 = clauseGroup[e.from];
      const g2 = clauseGroup[e.to];
      if (g1 && g2 && g1 !== g2 && (e.rel === "not" || e.rel === "same_slot")) {
        const key = ["group:" + g1, "group:" + g2, e.rel].sort().join("|");
        if (seen.has(key)) return;
        seen.add(key);
        edges.push({ from: "group:" + g1, to: "group:" + g2, rel: e.rel });
      }
      const phys = e.from.startsWith("physics:") ? e.from : e.to.startsWith("physics:") ? e.to : "";
      const clause = e.from.startsWith("clause:") ? e.from : e.to.startsWith("clause:") ? e.to : "";
      if (phys && clause && e.rel === "interprets" && clauseGroup[clause]) {
        const key = phys + "|group:" + clauseGroup[clause];
        if (seen.has(key)) return;
        seen.add(key);
        edges.push({ from: phys, to: "group:" + clauseGroup[clause], rel: "interprets" });
      }
    });
    return {
      nodes: [...groupNodes, ...physNodes],
      edges,
      height,
      width,
    };
  }

  function groupCluster(name) {
    const rows = (catalog.clauses || []).filter((c) => c.group === name).slice(0, 22);
    const ids = new Set(rows.map((c) => "clause:" + c.seq));
    (catalog.graph.edges || []).forEach((e) => {
      if (!ids.has(e.from) && !ids.has(e.to)) return;
      if (e.from.startsWith("physics:")) ids.add(e.from);
      if (e.to.startsWith("physics:")) ids.add(e.to);
    });
    const nodeMap = {};
    (catalog.graph.nodes || []).forEach((n) => {
      nodeMap[n.id] = n;
    });
    const nodes = [...ids]
      .map((nid) => nodeMap[nid])
      .filter(Boolean)
      .map((n) => ({
        id: n.id,
        kind: n.kind,
        label: n.kind === "physics" ? n.label : "#" + n.seq,
        mark: n.kind === "clause" ? String(n.seq) : "",
      }));
    const edges = (catalog.graph.edges || []).filter(
      (e) => ids.has(e.from) && ids.has(e.to)
    );
    return { nodes, edges };
  }

  function renderOverviewGraph() {
    const host = $("kb-graph");
    if (graphFocus && graphFocus.kind === "group" && graphFocus.group) {
      const nb = groupCluster(graphFocus.group);
      const phys = nb.nodes.filter((n) => n.kind === "physics");
      const clauses = nb.nodes.filter((n) => n.kind === "clause");
      const width = Math.max(host.clientWidth || 720, 560);
      const cx = width / 2;
      const placed = [
        ...layoutRing(clauses, cx, 205, Math.min(cx - 70, 250), 145),
        ...layoutRing(phys, cx, 205, 90, 55, 0.4),
      ];
      drawGraph(host, {
        nodes: placed,
        edges: nb.edges,
        height: 440,
        active: selected && selected.id,
        onClick: (n) => {
          if (n.kind === "physics") selectPhysics(n.id);
          else selectClause(Number(String(n.id).split(":")[1]), true);
        },
      });
      const back = document.createElement("button");
      back.type = "button";
      back.className = "kb-back";
      back.textContent = "返回总览";
      back.onclick = () => {
        graphFocus = { kind: "group", id: "" };
        renderOverviewGraph();
      };
      host.insertBefore(back, host.firstChild);
      return;
    }
    if (graphFocus && graphFocus.kind !== "group") {
      const nb = neighborhood(graphFocus.id);
      const others = nb.nodes.filter((n) => n.id !== graphFocus.id);
      const width = Math.max(host.clientWidth || 720, 560);
      const cx = width / 2;
      const placed = [
        { ...(nb.nodes.find((n) => n.id === graphFocus.id) || {}), x: cx, y: 200 },
        ...layoutRing(others, cx, 200, Math.min(cx - 80, 260), 130),
      ].filter((n) => n.id);
      drawGraph(host, {
        nodes: placed,
        edges: nb.edges,
        height: 430,
        active: graphFocus.id,
        onClick: (n) => {
          if (n.kind === "physics") selectPhysics(n.id);
          else selectClause(Number(String(n.id).split(":")[1]), true);
        },
      });
      const back = document.createElement("button");
      back.type = "button";
      back.className = "kb-back";
      back.textContent = "返回总览";
      back.onclick = () => {
        graphFocus = { kind: "group", id: "" };
        renderOverviewGraph();
      };
      host.insertBefore(back, host.firstChild);
      return;
    }
    const spec = overviewSpec();
    drawGraph(host, {
      ...spec,
      active: selected && selected.kind === "group" ? selected.id : "",
      onClick: (n) => {
        if (n.kind === "physics") {
          graphFocus = { kind: "physics", id: n.id };
          selected = graphFocus;
          renderOverviewGraph();
          renderDetail($("kb-graph-detail"));
          return;
        }
        groupName = n.group || "";
        graphFocus = { kind: "group", id: "group:" + groupName, group: groupName };
        const first = (catalog.clauses || []).find((c) => c.group === groupName);
        if (first) selected = { kind: "clause", id: "clause:" + first.seq, seq: first.seq };
        renderOverviewGraph();
        renderDetail($("kb-graph-detail"));
        renderGroups();
        renderList();
      },
    });
    if (!selected) renderDetail($("kb-graph-detail"));
  }

  window.kbEnsure = async function kbEnsure() {
    if (catalog) {
      renderMiniGraph();
      if (tab === "graph") renderOverviewGraph();
      return catalog;
    }
    if (loading) return loading;
    $("kb-banner").textContent = "正在载入知识库…";
    loading = (async () => {
      catalog = await kbJson("/api/knowledge");
      bindOnce();
      renderAll();
      return catalog;
    })();
    try {
      return await loading;
    } catch (err) {
      $("kb-banner").textContent = String(err.message || err);
      throw err;
    } finally {
      loading = null;
    }
  };
})();
