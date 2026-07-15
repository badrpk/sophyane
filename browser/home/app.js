/* Sophyane Browser — ChatGPT-format chat (browser app · new tab · mobile) */
(function () {
  "use strict";

  const HW = localStorage.getItem("sophyane_hw") || "http://127.0.0.1:8770";
  const MESH = localStorage.getItem("sophyane_mesh") || "http://127.0.0.1:8777";
  const CLOUD = localStorage.getItem("sophyane_cloud") || "";
  const STORAGE_KEY = "sophyane_chatgpt_sessions_v1";

  const els = {
    sidebar: document.getElementById("sidebar"),
    overlay: document.getElementById("overlay"),
    btnMenu: document.getElementById("btnMenu"),
    btnNew: document.getElementById("btnNewChat"),
    chatList: document.getElementById("chatList"),
    empty: document.getElementById("emptyState"),
    thread: document.getElementById("thread"),
    threadInner: document.getElementById("threadInner"),
    composer: document.getElementById("composer"),
    input: document.getElementById("input"),
    btnSend: document.getElementById("btnSend"),
    edgeMode: document.getElementById("edgeMode"),
    drawer: document.getElementById("drawer"),
    btnTools: document.getElementById("btnTools"),
    btnCloseDrawer: document.getElementById("btnCloseDrawer"),
    toolOut: document.getElementById("toolOut"),
    btnShare: document.getElementById("btnShare"),
  };

  /** @type {{id:string,title:string,messages:{role:string,content:string,sources?:any[]}[]}[]} */
  let sessions = loadSessions();
  let activeId = sessions[0]?.id || null;
  let busy = false;

  function loadSessions() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      return Array.isArray(raw) ? raw : [];
    } catch {
      return [];
    }
  }

  function saveSessions() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions.slice(0, 50)));
  }

  function uid() {
    return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
  }

  function active() {
    return sessions.find((s) => s.id === activeId) || null;
  }

  function ensureSession() {
    let s = active();
    if (!s) {
      s = { id: uid(), title: "New chat", messages: [] };
      sessions.unshift(s);
      activeId = s.id;
      saveSessions();
    }
    return s;
  }

  function renderSidebar() {
    els.chatList.innerHTML = sessions
      .map((s) => {
        const title = escapeHtml(s.title || "New chat");
        const cls = s.id === activeId ? "active" : "";
        return `<li class="${cls}" data-id="${s.id}">${title}</li>`;
      })
      .join("");
    els.chatList.querySelectorAll("li").forEach((li) => {
      li.onclick = () => {
        activeId = li.dataset.id;
        renderSidebar();
        renderThread();
        closeSidebarMobile();
      };
    });
  }

  function renderThread() {
    const s = active();
    const has = s && s.messages.length > 0;
    els.empty.hidden = !!has;
    els.thread.hidden = !has;
    if (!has) {
      els.threadInner.innerHTML = "";
      return;
    }
    els.threadInner.innerHTML = s.messages
      .map((m) => {
        const role = m.role === "user" ? "user" : "assistant";
        const label = role === "user" ? "You" : "Sophyane";
        const av = role === "user" ? "Y" : "S";
        let sources = "";
        if (m.sources && m.sources.length) {
          sources =
            `<div class="sources">` +
            m.sources
              .map(
                (src, i) =>
                  `<a class="source-chip" href="${escapeAttr(src.url || "#")}" target="_blank" rel="noopener">${i + 1}. ${escapeHtml(
                    src.title || src.url || "source"
                  )}</a>`
              )
              .join("") +
            `</div>`;
        }
        return (
          `<div class="msg ${role}">` +
          `<div class="msg-avatar">${av}</div>` +
          `<div class="msg-col">` +
          `<div class="msg-role">${label}</div>` +
          `<div class="msg-body">${formatBody(m.content)}${sources}</div>` +
          `</div></div>`
        );
      })
      .join("");
    els.thread.scrollTop = els.thread.scrollHeight;
  }

  function formatBody(text) {
    // lightweight: escape then allow simple newlines; wrap `code`
    let t = escapeHtml(String(text || ""));
    t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
    return t;
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

  function autoGrow() {
    const ta = els.input;
    ta.style.height = "auto";
    ta.style.height = Math.min(200, ta.scrollHeight) + "px";
    els.btnSend.disabled = busy || !ta.value.trim();
  }

  els.input.addEventListener("input", autoGrow);
  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!els.btnSend.disabled) els.composer.requestSubmit();
    }
  });

  function openSidebarMobile() {
    els.sidebar.classList.add("open");
    els.overlay.hidden = false;
  }
  function closeSidebarMobile() {
    els.sidebar.classList.remove("open");
    els.overlay.hidden = true;
  }
  els.btnMenu.onclick = openSidebarMobile;
  els.overlay.onclick = closeSidebarMobile;

  els.btnNew.onclick = () => {
    const s = { id: uid(), title: "New chat", messages: [] };
    sessions.unshift(s);
    activeId = s.id;
    saveSessions();
    renderSidebar();
    renderThread();
    closeSidebarMobile();
    els.input.focus();
  };

  document.querySelectorAll(".sug").forEach((b) => {
    b.onclick = () => {
      els.input.value = b.dataset.q || b.textContent;
      autoGrow();
      els.composer.requestSubmit();
    };
  });

  async function jget(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }
  async function jpost(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  function isUrl(s) {
    return /^https?:\/\//i.test(s.trim());
  }

  async function chatApi(message, edge) {
    try {
      const data = await jpost(HW + "/v1/hardware/chat", { message, edge: !!edge });
      const reply =
        data.reply ||
        data.result?.reply ||
        (typeof data.result === "string" ? data.result : null) ||
        data.error ||
        JSON.stringify(data);
      return { reply: String(reply), sources: [] };
    } catch (e1) {
      const key = localStorage.getItem("sophyane_api_key");
      if (CLOUD && key) {
        const res = await fetch(CLOUD.replace(/\/$/, "") + "/api/v1/chat", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: "Bearer " + key,
          },
          body: JSON.stringify({ message, edge: !!edge }),
        });
        const data = await res.json();
        return {
          reply: String(data.reply || data.error || JSON.stringify(data)),
          sources: [],
        };
      }
      throw e1;
    }
  }

  async function maybeFetchSource(message) {
    const m = message.trim().match(/https?:\/\/[^\s]+/i);
    if (!m) return null;
    const url = m[0];
    try {
      const data = await jpost(HW + "/v1/hardware/rpc", {
        method: "web_fetch",
        params: { url },
      });
      const r = data.result || data;
      return {
        url,
        title: r.title || url,
        text: String(r.text || r.content || "").slice(0, 3500),
      };
    } catch {
      return { url, title: url, text: "" };
    }
  }

  els.composer.onsubmit = async (e) => {
    e.preventDefault();
    const text = els.input.value.trim();
    if (!text || busy) return;

    const s = ensureSession();
    if (s.messages.length === 0) {
      s.title = text.slice(0, 48) + (text.length > 48 ? "…" : "");
    }
    s.messages.push({ role: "user", content: text });
    els.input.value = "";
    autoGrow();
    saveSessions();
    renderSidebar();
    renderThread();

    // typing indicator
    s.messages.push({ role: "assistant", content: "…" });
    const typingIdx = s.messages.length - 1;
    renderThread();
    const typingEl = els.threadInner.querySelectorAll(".msg.assistant .msg-body");
    if (typingEl.length) {
      typingEl[typingEl.length - 1].classList.add("typing");
      typingEl[typingEl.length - 1].textContent = "Thinking…";
    }

    busy = true;
    els.btnSend.disabled = true;
    const edge = !!els.edgeMode.checked;

    try {
      let prompt = text;
      let sources = [];
      const page = await maybeFetchSource(text);
      if (page && page.text) {
        sources.push({ url: page.url, title: page.title });
        prompt =
          `Use this page content when answering.\nURL: ${page.url}\nTitle: ${page.title}\n\n` +
          `${page.text}\n\nUser: ${text}`;
      }
      const { reply } = await chatApi(prompt, edge);
      s.messages[typingIdx] = {
        role: "assistant",
        content: reply || "(empty reply)",
        sources,
      };
    } catch (err) {
      s.messages[typingIdx] = {
        role: "assistant",
        content:
          "Could not reach Sophyane APIs.\n\n" +
          "• Start: `sophyane-browser` or `sophyane --hardware-api`\n" +
          "• Or set localStorage sophyane_api_key + sophyane_cloud for portal chat\n\n" +
          String(err),
      };
    }

    busy = false;
    saveSessions();
    renderSidebar();
    renderThread();
    autoGrow();
    els.input.focus();
  };

  // Tools drawer
  function openDrawer() {
    els.drawer.hidden = false;
  }
  function closeDrawer() {
    els.drawer.hidden = true;
  }
  els.btnTools.onclick = openDrawer;
  els.btnCloseDrawer.onclick = closeDrawer;

  document.querySelectorAll(".tool").forEach((btn) => {
    btn.onclick = async () => {
      const t = btn.dataset.tool;
      els.toolOut.textContent = "Loading…";
      try {
        if (t === "platform") {
          els.toolOut.textContent = JSON.stringify(await jget(HW + "/v1/hardware/platform"), null, 2);
        } else if (t === "hardware") {
          els.toolOut.textContent = JSON.stringify(await jget(HW + "/v1/hardware/compat"), null, 2);
        } else if (t === "mesh") {
          els.toolOut.textContent = JSON.stringify(await jget(MESH + "/v1/mesh/hello"), null, 2);
        } else if (t === "train") {
          els.toolOut.textContent = JSON.stringify(await jget(HW + "/v1/train/status"), null, 2);
        }
      } catch (e) {
        els.toolOut.textContent = String(e);
      }
    };
  });

  els.btnShare.onclick = async () => {
    const s = active();
    if (!s || !s.messages.length) return;
    const text = s.messages.map((m) => `${m.role === "user" ? "You" : "Sophyane"}: ${m.content}`).join("\n\n");
    try {
      await navigator.clipboard.writeText(text);
      els.btnShare.textContent = "✓";
      setTimeout(() => {
        els.btnShare.textContent = "⤴";
      }, 1200);
    } catch {
      /* ignore */
    }
  };

  // PWA: register nothing heavy; just ready for add-to-home-screen
  if ("serviceWorker" in navigator) {
    // optional no-op — keep offline simple
  }

  // Init
  if (!sessions.length) {
    sessions = [];
    activeId = null;
  }
  renderSidebar();
  renderThread();
  autoGrow();
  els.input.focus();
})();
