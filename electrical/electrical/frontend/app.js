    const fileInput = document.getElementById("file");
    const pick = document.getElementById("pick");
    const drop = document.getElementById("drop");
    const fname = document.getElementById("fname");
    const fsize = document.getElementById("fsize");
    const go = document.getElementById("go");
    const pauseBtn = document.getElementById("pause");
    const stopBtn = document.getElementById("stop");
    const status = document.getElementById("status");
    const health = document.getElementById("health");
    const progress = document.getElementById("progress");
    const barfill = document.getElementById("barfill");
    const result = document.getElementById("result");
    const steps = {
      read: document.getElementById("st-read"),
      ocr: document.getElementById("st-ocr"),
      qc: document.getElementById("st-qc"),
      extract: document.getElementById("st-extract"),
      write: document.getElementById("st-write"),
    };
    let chosen = null;
    let llmOk = false;
    let currentJob = null;
    let runPaused = false;

    function setRunButtons(running, paused, stopping) {
      go.style.display = running ? "none" : "";
      pauseBtn.classList.toggle("show", !!running);
      stopBtn.classList.toggle("show", !!running);
      pauseBtn.textContent = paused ? "继续" : "暂停";
      pauseBtn.disabled = !running || !!stopping;
      stopBtn.disabled = !running || !!stopping;
      pick.disabled = !!running;
      drop.style.pointerEvents = running ? "none" : "";
    }

    function fmtSize(n) {
      if (n < 1024) return n + " B";
      if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
      return (n / 1048576).toFixed(1) + " MB";
    }
    function fmtElapsed(sec) {
      sec = Math.max(0, Math.floor(sec));
      const m = Math.floor(sec / 60);
      const s = sec % 60;
      return m ? (m + " 分 " + s + " 秒") : (s + " 秒");
    }
    function explainErr(e) {
      const msg = (e && e.message) ? e.message : String(e);
      if (msg === "Failed to fetch" || msg === "Load failed" || msg.indexOf("NetworkError") >= 0) {
        return "与本机页面断开。请刷新后重新出表。";
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
          const pr = await fetch("/api/jobs/" + id);
          const data = await pr.json().catch(() => ({}));
          return { pr, data };
        } catch (e) {
          last = e;
          await new Promise(r => setTimeout(r, 800));
        }
      }
      throw last || new Error("查询进度失败");
    }

    fetch("/api/health").then(r => r.json()).then(d => {
      llmOk = !!d.ok;
      health.className = "health " + (d.ok ? "ok" : "err");
      health.innerHTML = d.ok
        ? '<i class="dot"></i>本机识别已就绪'
        : '<i class="dot"></i>本机识别未就绪：请确认工位模型服务已启动';
      go.disabled = !(chosen && llmOk);
    }).catch(() => {
      health.className = "health err";
      health.innerHTML = '<i class="dot"></i>页面无法连接本机服务。请确认程序仍在运行。';
    });

    function revealResult() {
      document.querySelector(".card")?.classList.add("has-result");
      requestAnimationFrame(() => {
        result.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    }
    function setFile(f) {
      chosen = f || null;
      drop.classList.toggle("has", !!chosen);
      fname.textContent = chosen ? chosen.name : "";
      fsize.textContent = chosen ? fmtSize(chosen.size) : "";
      go.disabled = !(chosen && llmOk);
      pick.textContent = chosen ? "更换文件" : "选择文件";
      result.classList.remove("show");
      result.innerHTML = "";
      document.querySelector(".card")?.classList.remove("has-result");
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

    go.addEventListener("click", async () => {
      if (!chosen) return;
      currentJob = null;
      runPaused = false;
      setRunButtons(true, false, false);
      result.classList.remove("show");
      result.innerHTML = "";
      document.querySelector(".card")?.classList.remove("has-result");
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
        const started = await fetch("/api/jobs", { method: "POST", body });
        const job = await started.json();
        if (!started.ok) throw new Error(job.detail || "无法开始出表");
        currentJob = job.id;
        while (true) {
          await new Promise(r => setTimeout(r, 800));
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
            status.textContent = data.stopped_early ? "已按已抽出内容出表" : "出表完成";
            barfill.style.width = "100%";
            setStage("write");
            steps.write.className = "step done";
            const filled = (data.filled != null) ? data.filled : "—";
            const extract = data.extract !== false;
            let tip = "";
            if (data.stopped_early) {
              tip = "已结束抽取。核对表按当前已抽出内容生成，未抽完的条目仍为空。";
            } else if (!extract && data.kind_note) {
              tip = data.kind_note;
            } else if (data.pending_review) {
              tip = data.pending_review + " 行需按「已检索到 / 未检索到 / 局部对应」过目。";
            } else {
              tip = "已填项可进入核对。";
            }
            const qa = String(data.qa_summary || "").trim();
            const verdict = String(data.qa_verdict || "").trim();
            if ((verdict === "warn" || verdict === "fail") && qa && qa !== tip) {
              tip = "质检：" + qa + " " + tip;
            }
            result.className = "result show";
            result.innerHTML =
              "<h2>" + (data.stopped_early ? "已按已抽出内容出表" : "核对表已生成") + "</h2>" +
              "<div class='stats'>" +
              "<div class='stat'><b>" + data.elapsed_seconds.toFixed(1) + "s</b><span>耗时</span></div>" +
              "<div class='stat'><b>" + filled + "</b><span>已检索到值</span></div>" +
              "<div class='stat'><b>" + (extract ? data.pending_review : "—") + "</b><span>待过目</span></div>" +
              "</div>" +
              "<p class='status' style='margin:0 0 12px'>" + tip + "</p>" +
              "<a class='dl' href='" + data.download + "'>下载核对表</a>";
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
        result.innerHTML = "<h2>未能完成出表</h2><p class='status' style='margin:0'>" + explainErr(e) + "</p>";
        revealResult();
      } finally {
        clearInterval(tick);
        currentJob = null;
        runPaused = false;
        setRunButtons(false, false, false);
        go.disabled = !(chosen && llmOk);
      }
    });

    async function sendControl(action) {
      if (!currentJob) return;
      const res = await fetch("/api/jobs/" + currentJob + "/" + action, { method: "POST" });
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
        status.dataset.stage = "将在本段结束后结束，并按已抽出内容出表…";
      } catch (e) {
        status.className = "status err";
        status.textContent = explainErr(e);
        pauseBtn.disabled = !currentJob;
        stopBtn.disabled = !currentJob;
      }
    });
  