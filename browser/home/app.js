/* Sophyane Browser — Perplexity-style ask + sources + agent tools */
(function () {
  const HW = localStorage.getItem("sophyane_hw") || "http://127.0.0.1:8770";
  const MESH = localStorage.getItem("sophyane_mesh") || "http://127.0.0.1:8777";
  const CLOUD = localStorage.getItem("sophyane_cloud") || "";

  const qEl = document.getElementById("q");
  const answerCard = document.getElementById("answerCard");
  const answerBody = document.getElementById("answerBody");
  const answerMode = document.getElementById("answerMode");
  const answerTime = document.getElementById("answerTime");
  const sourcesRow = document.getElementById("sourcesRow");
  const sourcesList = document.getElementById("sourcesList");
  const histList = document.getElementById("histList");
  const connDot = document.getElementById("connDot");
  const statusOut = document.getElementById("statusOut");
  const meshOut = document.getElementById("meshOut");
  const agentOut = document.getElementById("agentOut");

  let mode = "answer";
  let history = JSON.parse(localStorage.getItem("sophyane_browser_hist") || "[]");
  let lastSources = [];

  function isUrl(s) {
    return /^https?:\/\//i.test(s.trim());
  }

  async function jget(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async function jpost(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  function setView(name) {
    document.querySelectorAll(".nav-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.view === name);
    });
    document.getElementById("view-search").classList.toggle("hidden", name !== "search");
    ["agent", "sources", "mesh", "status", "history"].forEach((v) => {
      const el = document.getElementById("view-" + v);
      if (el) el.classList.toggle("hidden", name !== v);
    });
  }

  document.querySelectorAll(".nav-btn").forEach((b) => {
    b.onclick = () => setView(b.dataset.view);
  });

  document.querySelectorAll(".chip").forEach((c) => {
    c.onclick = () => {
      document.querySelectorAll(".chip").forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
      mode = c.dataset.mode;
    };
  });

  document.querySelectorAll(".sug").forEach((b) => {
    b.onclick = () => {
      qEl.value = b.textContent;
      ask(qEl.value);
    };
  });

  document.querySelectorAll(".follow-btn").forEach((b) => {
    b.onclick = () => {
      const base = qEl.value.trim() || "Continue";
      qEl.value = base + " — " + b.dataset.f;
      ask(qEl.value);
    };
  });

  function renderSources(sources) {
    lastSources = sources || [];
    sourcesRow.innerHTML = "";
    if (!lastSources.length) {
      sourcesList.innerHTML = '<p class="muted">No sources yet for this answer.</p>';
      return;
    }
    lastSources.forEach((s, i) => {
      const chip = document.createElement("div");
      chip.className = "source-chip";
      const a = document.createElement("a");
      a.href = s.url || "#";
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = s.title || s.url || "source " + (i + 1);
      chip.appendChild(document.createTextNode((i + 1) + ". "));
      chip.appendChild(a);
      sourcesRow.appendChild(chip);
    });
    sourcesList.innerHTML = lastSources
      .map(
        (s, i) =>
          `<div class="source-card"><strong>${i + 1}. ${escapeHtml(s.title || "Source")}</strong><br/>` +
          `<a href="${escapeAttr(s.url || "#")}" target="_blank" rel="noopener">${escapeHtml(s.url || "")}</a>` +
          `<p class="muted">${escapeHtml((s.snippet || "").slice(0, 280))}</p></div>`
      )
      .join("");
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }
  function escapeAttr(s) {
    return escapeHtml(s).replace(/"/g, "&quot;");
  }

  function pushHistory(q, answer) {
    history.unshift({ q, answer: String(answer).slice(0, 500), ts: Date.now() });
    history = history.slice(0, 40);
    localStorage.setItem("sophyane_browser_hist", JSON.stringify(history));
    renderHistory();
  }

  function renderHistory() {
    histList.innerHTML = history
      .map(
        (h, i) =>
          `<li data-i="${i}"><strong>${escapeHtml(h.q)}</strong><br/><span class="muted">${escapeHtml(
            (h.answer || "").slice(0, 120)
          )}</span></li>`
      )
      .join("");
    histList.querySelectorAll("li").forEach((li) => {
      li.onclick = () => {
        const h = history[Number(li.dataset.i)];
        if (!h) return;
        qEl.value = h.q;
        answerBody.textContent = h.answer;
        answerCard.classList.remove("hidden");
        setView("search");
      };
    });
  }

  async function fetchUrl(url) {
    try {
      return await jpost(HW + "/v1/hardware/rpc", { method: "web_fetch", params: { url } });
    } catch (e) {
      return { ok: false, error: String(e) };
    }
  }

  async function chat(message, edge) {
    // Prefer hardware chat, then cloud portal if key set
    try {
      return await jpost(HW + "/v1/hardware/chat", { message, edge: !!edge });
    } catch (e1) {
      const key = localStorage.getItem("sophyane_api_key");
      if (CLOUD && key) {
        try {
          const res = await fetch(CLOUD.replace(/\/$/, "") + "/api/v1/chat", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: "Bearer " + key,
            },
            body: JSON.stringify({ message, edge: !!edge }),
          });
          return await res.json();
        } catch (e2) {
          return { ok: false, error: String(e1) + " / " + String(e2) };
        }
      }
      return { ok: false, error: String(e1) };
    }
  }

  async function ask(raw) {
    const q = (raw || qEl.value || "").trim();
    if (!q) return;
    answerCard.classList.remove("hidden");
    answerBody.textContent = "Thinking…";
    answerMode.textContent = mode;
    answerTime.textContent = new Date().toLocaleTimeString();
    sourcesRow.innerHTML = "";
    setView("search");

    let sources = [];
    let answer = "";

    try {
      if (mode === "search" || mode === "learn" || isUrl(q)) {
        const url = isUrl(q) ? q.split(/\s+/)[0] : null;
        if (url) {
          const fetched = await fetchUrl(url);
          const result = fetched.result || fetched;
          const title = result.title || url;
          const text = result.text || result.content || JSON.stringify(result).slice(0, 2000);
          sources.push({ url, title, snippet: String(text).slice(0, 240) });
          if (mode === "learn") {
            try {
              await jpost(HW + "/v1/hardware/rpc", {
                method: "improve_from_url",
                params: { url },
              });
            } catch (_) {}
          }
          const chatRes = await chat(
            `Summarize and answer using this page content.\nURL: ${url}\nTitle: ${title}\n\n${String(text).slice(0, 3500)}\n\nUser question: ${q}`,
            mode === "edge"
          );
          answer =
            (chatRes.reply || chatRes.result?.reply || chatRes.result || chatRes.error || JSON.stringify(chatRes)).toString();
        } else {
          // Web-style answer without URL: AI + optional note
          const chatRes = await chat(
            `You are Sophyane Browser (AI search mode). Answer clearly with bullet points when helpful. Question: ${q}`,
            mode === "edge"
          );
          answer =
            (chatRes.reply || chatRes.result?.reply || chatRes.result || chatRes.error || JSON.stringify(chatRes)).toString();
          sources.push({
            url: "https://github.com/badrpk/sophyane",
            title: "Sophyane knowledge / local model",
            snippet: "Answer generated via Sophyane agent APIs",
          });
        }
      } else {
        const chatRes = await chat(q, mode === "edge" || mode === "answer");
        answer =
          (chatRes.reply || chatRes.result?.reply || chatRes.result || chatRes.error || JSON.stringify(chatRes)).toString();
        sources.push({
          url: "https://github.com/badrpk/sophyane",
          title: "Sophyane agent",
          snippet: mode === "edge" ? "Hybrid edge / expert path" : "Cloud or local provider",
        });
      }
    } catch (e) {
      answer = "Request failed: " + e + "\n\nStart local APIs: sophyane-browser  or  sophyane --hardware-api";
    }

    answerBody.textContent = typeof answer === "string" ? answer : JSON.stringify(answer, null, 2);
    renderSources(sources);
    pushHistory(q, answerBody.textContent);
  }

  document.getElementById("askForm").onsubmit = (e) => {
    e.preventDefault();
    ask(qEl.value);
  };

  async function refreshStatus() {
    try {
      const health = await jget(HW + "/v1/hardware/health");
      statusOut.textContent = JSON.stringify(health, null, 2);
      connDot.classList.add("on");
      connDot.classList.remove("off");
    } catch (e) {
      statusOut.textContent = "Hardware API offline on :8770\n" + e;
      connDot.classList.remove("on");
      connDot.classList.add("off");
    }
    try {
      const mesh = await jget(MESH + "/v1/mesh/hello");
      meshOut.textContent = JSON.stringify(mesh, null, 2);
    } catch (e) {
      meshOut.textContent = "Mesh offline on :8777\n" + e;
    }
  }

  document.getElementById("btnPlatform").onclick = async () => {
    agentOut.textContent = "…";
    try {
      agentOut.textContent = JSON.stringify(await jget(HW + "/v1/hardware/platform"), null, 2);
    } catch (e) {
      agentOut.textContent = String(e);
    }
  };
  document.getElementById("btnHardware").onclick = async () => {
    agentOut.textContent = "…";
    try {
      agentOut.textContent = JSON.stringify(await jget(HW + "/v1/hardware/compat"), null, 2);
    } catch (e) {
      agentOut.textContent = String(e);
    }
  };
  document.getElementById("btnKernel").onclick = async () => {
    agentOut.textContent = "…";
    try {
      agentOut.textContent = JSON.stringify(await jget(HW + "/v1/kernel/status"), null, 2);
    } catch (e) {
      agentOut.textContent = String(e);
    }
  };
  document.getElementById("btnTrain").onclick = async () => {
    agentOut.textContent = "…";
    try {
      agentOut.textContent = JSON.stringify(await jget(HW + "/v1/train/status"), null, 2);
    } catch (e) {
      agentOut.textContent = String(e);
    }
  };

  renderHistory();
  refreshStatus();
  setInterval(refreshStatus, 20000);
})();
