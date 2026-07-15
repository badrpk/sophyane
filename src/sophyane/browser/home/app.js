/* Sophyane Browser — ChatGPT UI + OTP auth + plan upgrade + sidebar */
(function () {
  "use strict";

  const AUTH_KEY = "sophyane_auth_v1";
  const STORAGE_KEY = "sophyane_chatgpt_sessions_v1";

  function detectCloud() {
    const stored = localStorage.getItem("sophyane_cloud");
    if (stored) return stored.replace(/\/$/, "");
    if (
      location.port === "8780" ||
      location.pathname.includes("browser-home") ||
      location.pathname.includes("browser")
    ) {
      return location.origin;
    }
    return "http://127.0.0.1:8780";
  }

  let HW = localStorage.getItem("sophyane_hw") || "http://127.0.0.1:8770";
  let MESH = localStorage.getItem("sophyane_mesh") || "http://127.0.0.1:8777";
  let CLOUD = detectCloud();

  /** @type {{email:string,name:string,plan:string,api_key:string,user_id?:string}|null} */
  let auth = loadAuth();
  let authPurpose = "login";
  let sessions = loadSessions();
  let activeId = sessions[0]?.id || null;
  let busy = false;
  /** @type {any[]} */
  let planCatalog = [];
  /** @type {any|null} */
  let llmStatus = null;

  const $ = (id) => document.getElementById(id);
  const els = {
    authGate: $("authGate"),
    appShell: $("appShell"),
    authEmail: $("authEmail"),
    authName: $("authName"),
    authPlan: $("authPlan"),
    authOtp: $("authOtp"),
    authMsg: $("authMsg"),
    authNameWrap: $("authNameWrap"),
    authPlanWrap: $("authPlanWrap"),
    btnSendOtp: $("btnSendOtp"),
    btnVerifyOtp: $("btnVerifyOtp"),
    sidebar: $("sidebar"),
    overlay: $("overlay"),
    btnMenu: $("btnMenu"),
    btnNew: $("btnNewChat"),
    chatList: $("chatList"),
    empty: $("emptyState"),
    thread: $("thread"),
    threadInner: $("threadInner"),
    composer: $("composer"),
    input: $("input"),
    btnSend: $("btnSend"),
    edgeMode: $("edgeMode"),
    drawer: $("drawer"),
    drawerTitle: $("drawerTitle"),
    drawerTools: $("drawerTools"),
    drawerUpgrade: $("drawerUpgrade"),
    drawerSettings: $("drawerSettings"),
    drawerModels: $("drawerModels"),
    drawerHelp: $("drawerHelp"),
    planCards: $("planCards"),
    upgradeMsg: $("upgradeMsg"),
    setCloud: $("setCloud"),
    setHw: $("setHw"),
    btnSaveSettings: $("btnSaveSettings"),
    settingsMsg: $("settingsMsg"),
    btnUpgrade: $("btnUpgrade"),
    btnSettings: $("btnSettings"),
    btnModels: $("btnModels"),
    btnModelSelect: $("btnModelSelect"),
    modelSelectLabel: $("modelSelectLabel"),
    activeModelBox: $("activeModelBox"),
    llmProvider: $("llmProvider"),
    llmModel: $("llmModel"),
    llmApiKey: $("llmApiKey"),
    llmKeyWrap: $("llmKeyWrap"),
    llmKeyHint: $("llmKeyHint"),
    llmMsg: $("llmMsg"),
    llmProviderList: $("llmProviderList"),
    btnSaveLlm: $("btnSaveLlm"),
    btnSaveKeyOnly: $("btnSaveKeyOnly"),
    btnClearChats: $("btnClearChats"),
    btnTools: $("btnTools"),
    btnHelp: $("btnHelp"),
    btnCloseDrawer: $("btnCloseDrawer"),
    toolOut: $("toolOut"),
    btnShare: $("btnShare"),
    btnLogout: $("btnLogout"),
    userAvatar: $("userAvatar"),
    userName: $("userName"),
    userEmail: $("userEmail"),
    userPlan: $("userPlan"),
    headerAvatar: $("headerAvatar"),
    headerEmail: $("headerEmail"),
    emptySignedAs: $("emptySignedAs"),
    accountBox: $("accountBox"),
  };

  function loadAuth() {
    try {
      const a = JSON.parse(localStorage.getItem(AUTH_KEY) || "null");
      if (a && a.email && a.api_key) return a;
    } catch (_) {}
    const key = localStorage.getItem("sophyane_api_key");
    const email = localStorage.getItem("sophyane_user_email");
    if (key && email) {
      return { email, name: email.split("@")[0], plan: "hybrid", api_key: key };
    }
    return null;
  }

  function saveAuth(a) {
    auth = a;
    if (a) {
      localStorage.setItem(AUTH_KEY, JSON.stringify(a));
      localStorage.setItem("sophyane_api_key", a.api_key);
      localStorage.setItem("sophyane_user_email", a.email);
      if (CLOUD) localStorage.setItem("sophyane_cloud", CLOUD);
    } else {
      localStorage.removeItem(AUTH_KEY);
      localStorage.removeItem("sophyane_api_key");
      localStorage.removeItem("sophyane_user_email");
    }
  }

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

  function initial(email, name) {
    const s = (name || email || "?").trim();
    return (s[0] || "?").toUpperCase();
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

  function setAuthMsg(text, isErr) {
    els.authMsg.textContent = text || "";
    els.authMsg.classList.toggle("err", !!isErr);
  }

  function updateAuthTabs() {
    document.querySelectorAll(".auth-tab").forEach((t) => {
      t.classList.toggle("active", t.dataset.purpose === authPurpose);
    });
    const signup = authPurpose === "signup";
    els.authNameWrap.hidden = !signup;
    els.authPlanWrap.hidden = !signup;
  }

  document.querySelectorAll(".auth-tab").forEach((t) => {
    t.onclick = () => {
      authPurpose = t.dataset.purpose || "login";
      updateAuthTabs();
      setAuthMsg("");
    };
  });

  function renderUser() {
    if (!auth) {
      els.userAvatar.textContent = "?";
      els.userName.textContent = "Not signed in";
      els.userEmail.textContent = "—";
      els.userPlan.textContent = "";
      els.headerAvatar.textContent = "?";
      els.headerEmail.textContent = "Sign in required";
      els.emptySignedAs.textContent = "";
      els.accountBox.innerHTML = "Not signed in.";
      return;
    }
    const av = initial(auth.email, auth.name);
    els.userAvatar.textContent = av;
    els.userName.textContent = auth.name || auth.email.split("@")[0];
    els.userEmail.textContent = auth.email;
    els.userPlan.textContent = auth.plan ? "plan · " + auth.plan : "";
    els.headerAvatar.textContent = av;
    els.headerEmail.textContent = auth.email;
    els.emptySignedAs.textContent = "Signed in as " + auth.email;
    els.accountBox.innerHTML =
      `<strong>Logged in</strong><br/>` +
      `Name: ${escapeHtml(auth.name || "—")}<br/>` +
      `Email: ${escapeHtml(auth.email)}<br/>` +
      `Plan: ${escapeHtml(auth.plan || "—")}<br/>` +
      `Key: ${escapeHtml((auth.api_key || "").slice(0, 12))}…`;
  }

  function showApp() {
    els.authGate.hidden = true;
    els.appShell.hidden = false;
    renderUser();
    renderSidebar();
    renderThread();
    autoGrow();
    refreshAccount().catch(() => {});
    els.input.focus();
  }

  function showAuth() {
    els.authGate.hidden = false;
    els.appShell.hidden = true;
    updateAuthTabs();
    renderUser();
  }

  async function requestOtp() {
    const email = els.authEmail.value.trim().toLowerCase();
    if (!email) {
      setAuthMsg("Enter your email.", true);
      return;
    }
    els.btnSendOtp.disabled = true;
    setAuthMsg("Sending OTP…");
    try {
      const res = await fetch(CLOUD + "/api/v1/auth/request-otp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          purpose: authPurpose,
          name: els.authName.value.trim(),
          plan: els.authPlan.value,
        }),
      });
      const data = await res.json();
      if (!data.ok) {
        setAuthMsg(data.error || "Could not send OTP", true);
      } else {
        setAuthMsg("OTP sent to " + email + " from badrpk@gmail.com. Check inbox/spam.");
        els.authOtp.focus();
      }
    } catch (e) {
      setAuthMsg(
        "Cannot reach auth server at " + CLOUD + "\nStart: sophyane --cloud-serve\n" + e,
        true
      );
    }
    els.btnSendOtp.disabled = false;
  }

  async function verifyOtp() {
    const email = els.authEmail.value.trim().toLowerCase();
    const otp = els.authOtp.value.trim();
    if (!email || !otp) {
      setAuthMsg("Email and OTP required.", true);
      return;
    }
    els.btnVerifyOtp.disabled = true;
    setAuthMsg("Verifying…");
    try {
      const res = await fetch(CLOUD + "/api/v1/auth/verify-otp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          otp,
          purpose: authPurpose,
          name: els.authName.value.trim(),
          plan: els.authPlan.value,
        }),
      });
      const data = await res.json();
      if (!data.ok || !data.api_key) {
        setAuthMsg(data.error || "Verification failed", true);
        els.btnVerifyOtp.disabled = false;
        return;
      }
      saveAuth({
        email: data.user?.email || email,
        name: data.user?.name || els.authName.value.trim() || email.split("@")[0],
        plan: data.user?.plan || els.authPlan.value || "hybrid",
        api_key: data.api_key,
        user_id: data.user?.id,
      });
      setAuthMsg("Signed in as " + email);
      showApp();
    } catch (e) {
      setAuthMsg("Verify failed: " + e, true);
    }
    els.btnVerifyOtp.disabled = false;
  }

  els.btnSendOtp.onclick = requestOtp;
  els.btnVerifyOtp.onclick = verifyOtp;
  els.authOtp.addEventListener("keydown", (e) => {
    if (e.key === "Enter") verifyOtp();
  });

  els.btnLogout.onclick = () => {
    if (!confirm("Log out of " + (auth?.email || "Sophyane") + "?")) return;
    saveAuth(null);
    showAuth();
    setAuthMsg("Logged out. Sign in again with email OTP.");
  };

  // —— Chat ——
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
        const av = role === "user" ? initial(auth?.email, auth?.name) : "S";
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
          `<div class="msg-avatar">${escapeHtml(av)}</div>` +
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
    let t = escapeHtml(String(text || ""));
    t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
    return t;
  }

  function autoGrow() {
    const ta = els.input;
    ta.style.height = "auto";
    ta.style.height = Math.min(200, ta.scrollHeight) + "px";
    els.btnSend.disabled = busy || !ta.value.trim() || !auth;
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
  els.overlay.onclick = () => {
    closeSidebarMobile();
    closeDrawer();
  };

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

  if (els.btnClearChats) {
    els.btnClearChats.onclick = () => {
      if (!confirm("Clear all local chats on this device?")) return;
      sessions = [];
      activeId = null;
      saveSessions();
      renderSidebar();
      renderThread();
      closeSidebarMobile();
    };
  }

  document.querySelectorAll(".sug").forEach((b) => {
    b.onclick = () => {
      els.input.value = b.dataset.q || b.textContent;
      autoGrow();
      els.composer.requestSubmit();
    };
  });

  async function jget(url, headers) {
    const res = await fetch(url, { headers: headers || {} });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }
  async function jpost(url, body, headers) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(headers || {}) },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) {
      let err = "HTTP " + res.status;
      try {
        const d = await res.json();
        if (d.error) err = d.error;
      } catch (_) {}
      throw new Error(err);
    }
    return res.json();
  }

  function authHeaders() {
    if (!auth?.api_key) return {};
    return { Authorization: "Bearer " + auth.api_key };
  }

  /** Build prior turns for the model (exclude the current user message already being sent). */
  function historyPayload(session, excludeLastUser) {
    const msgs = (session?.messages || []).filter((m) => m && m.content && m.content !== "…");
    let list = msgs;
    if (excludeLastUser && list.length && list[list.length - 1].role === "user") {
      list = list.slice(0, -1);
    }
    return list.slice(-8).map((m) => ({
      role: m.role === "assistant" ? "assistant" : "user",
      content: String(m.content).slice(0, 1500),
    }));
  }

  async function chatApi(message, edge, history) {
    if (!auth?.api_key) throw new Error("Not signed in");
    try {
      const res = await fetch(CLOUD + "/api/v1/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(),
        },
        body: JSON.stringify({
          message,
          edge: !!edge,
          history: Array.isArray(history) ? history : [],
          // Let portal decide via needs_web_research; never force off
          web_search: edge ? false : null,
        }),
      });
      const data = await res.json();
      if (!res.ok || data.ok === false) {
        throw new Error(data.error || "chat failed");
      }
      const sources = Array.isArray(data.sources)
        ? data.sources.map((s) => ({
            title: s.title || s.url || "source",
            url: s.url || "#",
          }))
        : [];
      return {
        reply: String(data.reply || data.error || JSON.stringify(data)),
        model: data.model || "",
        sources,
      };
    } catch (cloudErr) {
      try {
        const data = await jpost(HW + "/v1/hardware/chat", { message, edge: !!edge });
        const reply =
          data.reply ||
          data.result?.reply ||
          (typeof data.result === "string" ? data.result : null) ||
          data.error ||
          JSON.stringify(data);
        return { reply: String(reply), model: "hardware", sources: [] };
      } catch (e2) {
        throw new Error(String(cloudErr) + " · " + String(e2));
      }
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
    if (!auth) {
      showAuth();
      return;
    }
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
    // Prior turns only (current user message is `message` field)
    const history = historyPayload(s, true);

    try {
      let prompt = text;
      let sources = [];
      const page = await maybeFetchSource(text);
      if (page && page.text) {
        sources.push({ url: page.url, title: page.title });
        prompt =
          `Use this page content when answering.\nURL: ${page.url}\nTitle: ${page.title}\n\n` +
          `${page.text}\n\nQuestion: ${text}`;
      }
      const out = await chatApi(prompt, edge, history);
      const reply = out.reply;
      const webSources = Array.isArray(out.sources) ? out.sources : [];
      // Merge URL-fetch chips + web research sources
      const allSources = [...sources, ...webSources].filter((x, i, arr) => {
        if (!x || !x.url) return false;
        return arr.findIndex((y) => y.url === x.url) === i;
      });
      s.messages[typingIdx] = {
        role: "assistant",
        content: reply || "(empty reply)",
        sources: allSources,
      };
    } catch (err) {
      s.messages[typingIdx] = {
        role: "assistant",
        content:
          "Could not complete request while signed in as " +
          auth.email +
          ".\n\n" +
          "• Ensure cloud portal: sophyane --cloud-serve (:8780)\n" +
          "• Or hardware API: sophyane --hardware-api / sophyane-browser\n\n" +
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

  // —— Drawers (ChatGPT-style sidebar options) ——
  function hideAllDrawerPanels() {
    if (els.drawerTools) els.drawerTools.hidden = true;
    if (els.drawerUpgrade) els.drawerUpgrade.hidden = true;
    if (els.drawerSettings) els.drawerSettings.hidden = true;
    if (els.drawerModels) els.drawerModels.hidden = true;
    if (els.drawerHelp) els.drawerHelp.hidden = true;
  }

  function openDrawer(mode) {
    els.drawer.hidden = false;
    hideAllDrawerPanels();
    renderUser();
    if (mode === "upgrade") {
      if (els.drawerTitle) els.drawerTitle.textContent = "Upgrade plan";
      if (els.drawerUpgrade) els.drawerUpgrade.hidden = false;
      loadPlanCards();
    } else if (mode === "settings") {
      if (els.drawerTitle) els.drawerTitle.textContent = "Settings";
      if (els.drawerSettings) els.drawerSettings.hidden = false;
      if (els.setCloud) els.setCloud.value = CLOUD;
      if (els.setHw) els.setHw.value = HW;
      if (els.settingsMsg) els.settingsMsg.textContent = "";
    } else if (mode === "models") {
      if (els.drawerTitle) els.drawerTitle.textContent = "Models & API keys";
      if (els.drawerModels) els.drawerModels.hidden = false;
      loadLlmCatalog();
    } else if (mode === "help") {
      if (els.drawerTitle) els.drawerTitle.textContent = "Help & FAQ";
      if (els.drawerHelp) els.drawerHelp.hidden = false;
    } else {
      if (els.drawerTitle) els.drawerTitle.textContent = "Tools & status";
      if (els.drawerTools) els.drawerTools.hidden = false;
    }
    closeSidebarMobile();
  }

  function closeDrawer() {
    els.drawer.hidden = true;
  }

  if (els.btnTools) els.btnTools.onclick = () => openDrawer("tools");
  if (els.btnUpgrade) els.btnUpgrade.onclick = () => openDrawer("upgrade");
  if (els.btnSettings) els.btnSettings.onclick = () => openDrawer("settings");
  if (els.btnModels) els.btnModels.onclick = () => openDrawer("models");
  if (els.btnModelSelect) els.btnModelSelect.onclick = () => openDrawer("models");
  if (els.btnHelp) els.btnHelp.onclick = () => openDrawer("help");
  if (els.btnCloseDrawer) els.btnCloseDrawer.onclick = closeDrawer;

  function setLlmMsg(text, isErr) {
    if (!els.llmMsg) return;
    els.llmMsg.textContent = text || "";
    els.llmMsg.classList.toggle("err", !!isErr);
  }

  function updateModelLabel() {
    if (!els.modelSelectLabel) return;
    if (llmStatus && llmStatus.active) {
      const a = llmStatus.active;
      els.modelSelectLabel.textContent =
        (a.provider || "local") + " · " + (a.model || "model");
    } else {
      els.modelSelectLabel.textContent = "Sophyane Chat";
    }
  }

  function fillModelSelect(providerId) {
    if (!els.llmModel || !llmStatus) return;
    const p = (llmStatus.providers || []).find((x) => x.id === providerId);
    const models = (p && p.models) || [];
    els.llmModel.innerHTML = models
      .map(
        (m) =>
          `<option value="${escapeAttr(m.id)}">${escapeHtml(m.label || m.id)}</option>`
      )
      .join("");
    if (p && p.configured_model) {
      els.llmModel.value = p.configured_model;
    }
    const needsKey = !!(p && p.requires_api_key);
    if (els.llmKeyWrap) els.llmKeyWrap.hidden = !needsKey;
    if (els.llmKeyHint) {
      if (!needsKey) {
        els.llmKeyHint.textContent =
          "Free local model — no API key. Best for offline / no credits. Limited vs cloud frontier models.";
      } else {
        els.llmKeyHint.innerHTML =
          (p.has_api_key
            ? "Key on file: <code>" + escapeHtml(p.api_key_preview || "••••") + "</code>. Leave blank to keep it. "
            : "No key saved yet. ") +
          (p.docs
            ? `<a href="${escapeAttr(p.docs)}" target="_blank" rel="noopener">Get API key</a>`
            : "");
      }
    }
  }

  function renderLlmForm() {
    if (!llmStatus || !els.llmProvider) return;
    const providers = llmStatus.providers || [];
    els.llmProvider.innerHTML = providers
      .map((p) => {
        const mark = p.has_api_key || !p.requires_api_key ? "✓" : "○";
        const tier = p.tier === "local_free" ? "free" : "cloud";
        return `<option value="${escapeAttr(p.id)}">${mark} ${escapeHtml(p.name)} (${tier})</option>`;
      })
      .join("");
    const selected =
      providers.find((p) => p.selected) ||
      providers.find((p) => p.id === "local_gguf") ||
      providers[0];
    if (selected) {
      els.llmProvider.value = selected.id;
      fillModelSelect(selected.id);
    }
    if (els.activeModelBox && llmStatus.active) {
      const a = llmStatus.active;
      els.activeModelBox.innerHTML =
        `<strong>Active for chat &amp; agent harness</strong><br/>` +
        `Provider: ${escapeHtml(a.provider || "—")}<br/>` +
        `Model: ${escapeHtml(a.model || "—")}<br/>` +
        `Tier: ${escapeHtml(a.tier || "—")}<br/>` +
        `<span style="font-size:0.8rem">Cloud keys = top agentic performance. Local = free fallback.</span>`;
    }
    if (els.llmProviderList) {
      els.llmProviderList.innerHTML = providers
        .map((p) => {
          const status = !p.requires_api_key
            ? "free local"
            : p.has_api_key
              ? "key saved " + (p.api_key_preview || "")
              : "needs API key";
          const cls = p.selected ? " plan-card current" : " plan-card";
          return (
            `<button type="button" class="${cls.trim()}" data-pid="${escapeAttr(p.id)}">` +
            `<h4>${escapeHtml(p.name)}${p.selected ? " · active" : ""}</h4>` +
            `<div class="price">${escapeHtml(status)}</div>` +
            `<p>${escapeHtml(p.note || p.models?.[0]?.label || "")}</p>` +
            `</button>`
          );
        })
        .join("");
      els.llmProviderList.querySelectorAll("[data-pid]").forEach((btn) => {
        btn.onclick = () => {
          els.llmProvider.value = btn.dataset.pid;
          fillModelSelect(btn.dataset.pid);
        };
      });
    }
    updateModelLabel();
  }

  async function loadLlmCatalog() {
    setLlmMsg("Loading providers…");
    try {
      const data = await jget(CLOUD + "/api/v1/llm/catalog");
      llmStatus = data;
      renderLlmForm();
      setLlmMsg("");
    } catch (e) {
      setLlmMsg("Could not load LLM catalog: " + e, true);
    }
  }

  if (els.llmProvider) {
    els.llmProvider.onchange = () => fillModelSelect(els.llmProvider.value);
  }

  async function saveLlm(activate) {
    if (!els.llmProvider) return;
    const provider = els.llmProvider.value;
    const model = els.llmModel ? els.llmModel.value : "";
    const api_key = els.llmApiKey ? els.llmApiKey.value.trim() : "";
    setLlmMsg(activate ? "Activating…" : "Saving key…");
    try {
      if (activate) {
        const data = await jpost(CLOUD + "/api/v1/llm/select", {
          provider,
          model,
          api_key,
        });
        if (!data.ok) throw new Error(data.error || "select failed");
        llmStatus = data.status || data;
        if (els.llmApiKey) els.llmApiKey.value = "";
        renderLlmForm();
        setLlmMsg(data.message || "Model activated.");
      } else {
        if (!api_key) throw new Error("Enter an API key to save");
        const data = await jpost(CLOUD + "/api/v1/llm/key", { provider, api_key });
        if (!data.ok) throw new Error(data.error || "key save failed");
        llmStatus = data.status || data;
        if (els.llmApiKey) els.llmApiKey.value = "";
        renderLlmForm();
        setLlmMsg(data.message || "Key saved.");
      }
    } catch (e) {
      setLlmMsg(String(e.message || e), true);
    }
  }

  if (els.btnSaveLlm) els.btnSaveLlm.onclick = () => saveLlm(true);
  if (els.btnSaveKeyOnly) els.btnSaveKeyOnly.onclick = () => saveLlm(false);

  async function refreshAccount() {
    if (!auth?.api_key) return;
    try {
      const data = await jget(CLOUD + "/api/v1/account/me", authHeaders());
      if (data.ok && data.user) {
        auth.plan = data.user.plan || auth.plan;
        auth.name = data.user.name || auth.name;
        auth.email = data.user.email || auth.email;
        auth.user_id = data.user.id || auth.user_id;
        saveAuth(auth);
        if (Array.isArray(data.plans)) planCatalog = data.plans;
        renderUser();
      }
    } catch (_) {
      // Older portal without /account/me — ignore
    }
  }

  function defaultPlans() {
    return [
      {
        id: "free",
        name: "Free Explorer",
        price_usd_month: 0,
        included_tokens: 500000,
        description: "Start free. Perfect for demos and personal agents.",
      },
      {
        id: "hybrid",
        name: "Hybrid Edge",
        price_usd_month: 0,
        included_tokens: 2000000,
        description: "Cloud orchestration + free heavy compute on your hardware.",
      },
      {
        id: "builder",
        name: "Builder",
        price_usd_month: 1,
        included_tokens: 10000000,
        description: "Indie builders — almost free at scale.",
      },
      {
        id: "scale",
        name: "Scale",
        price_usd_month: 9,
        included_tokens: 200000000,
        description: "Production agents at a fraction of frontier rates.",
      },
    ];
  }

  async function loadPlanCards() {
    if (!els.planCards) return;
    els.planCards.innerHTML = "Loading plans…";
    if (els.upgradeMsg) {
      els.upgradeMsg.textContent = "";
      els.upgradeMsg.classList.remove("err");
    }
    try {
      await refreshAccount();
      if (!planCatalog.length) {
        const pricing = await jget(CLOUD + "/api/v1/pricing");
        if (Array.isArray(pricing.plans)) planCatalog = pricing.plans;
      }
    } catch (_) {}
    const plans = planCatalog.length ? planCatalog : defaultPlans();
    const current = (auth && auth.plan) || "free";
    els.planCards.innerHTML = plans
      .map((p) => {
        const id = p.id || p.plan;
        const isCurrent = id === current;
        const price =
          p.price_usd_month === 0 || p.price_usd_month === "0"
            ? "Free"
            : "$" + p.price_usd_month + "/mo";
        const tokens = p.included_tokens
          ? (Number(p.included_tokens) / 1e6).toFixed(Number(p.included_tokens) >= 1e6 ? 0 : 1) + "M tokens incl."
          : "";
        return (
          `<button type="button" class="plan-card${isCurrent ? " current" : ""}" data-plan="${escapeAttr(id)}">` +
          `<h4>${escapeHtml(p.name || id)}${isCurrent ? " · current" : ""}</h4>` +
          `<div class="price">${escapeHtml(price)}${tokens ? " · " + escapeHtml(tokens) : ""}</div>` +
          `<p>${escapeHtml(p.description || "")}</p>` +
          `</button>`
        );
      })
      .join("");
    els.planCards.querySelectorAll(".plan-card").forEach((card) => {
      card.onclick = () => upgradePlan(card.dataset.plan);
    });
  }

  async function upgradePlan(planId) {
    if (!auth?.api_key) {
      if (els.upgradeMsg) {
        els.upgradeMsg.textContent = "Sign in required.";
        els.upgradeMsg.classList.add("err");
      }
      return;
    }
    if (!planId) return;
    if (planId === auth.plan) {
      if (els.upgradeMsg) {
        els.upgradeMsg.textContent = "Already on " + planId + ".";
        els.upgradeMsg.classList.remove("err");
      }
      return;
    }
    if (els.upgradeMsg) {
      els.upgradeMsg.textContent = "Updating to " + planId + "…";
      els.upgradeMsg.classList.remove("err");
    }
    try {
      const data = await jpost(
        CLOUD + "/api/v1/account/upgrade",
        { plan: planId },
        authHeaders()
      );
      if (!data.ok) throw new Error(data.error || "upgrade failed");
      auth.plan = planId;
      saveAuth(auth);
      renderUser();
      if (Array.isArray(data.plans)) planCatalog = data.plans;
      if (els.upgradeMsg) {
        els.upgradeMsg.textContent = data.message || "Plan updated to " + planId + ".";
        els.upgradeMsg.classList.remove("err");
      }
      loadPlanCards();
    } catch (e) {
      if (els.upgradeMsg) {
        els.upgradeMsg.textContent = String(e);
        els.upgradeMsg.classList.add("err");
      }
    }
  }

  if (els.btnSaveSettings) {
    els.btnSaveSettings.onclick = () => {
      const cloud = (els.setCloud?.value || "").trim().replace(/\/$/, "");
      const hw = (els.setHw?.value || "").trim().replace(/\/$/, "");
      if (cloud) {
        CLOUD = cloud;
        localStorage.setItem("sophyane_cloud", CLOUD);
      }
      if (hw) {
        HW = hw;
        localStorage.setItem("sophyane_hw", HW);
      }
      if (els.settingsMsg) {
        els.settingsMsg.textContent = "Saved. Chat will use " + CLOUD;
        els.settingsMsg.classList.remove("err");
      }
    };
  }

  /** Prefer same-origin portal tools (avoids Failed to fetch when :8770 drops connections). */
  async function fetchTool(name) {
    const portalUrl = CLOUD + "/api/v1/tools/" + name;
    try {
      const data = await jget(portalUrl, name === "usage" ? authHeaders() : {});
      return data;
    } catch (portalErr) {
      // Fall back to local hardware / mesh APIs
      if (name === "platform") return jget(HW + "/v1/hardware/platform");
      if (name === "hardware") return jget(HW + "/v1/hardware/compat");
      if (name === "mesh") return jget(MESH + "/v1/mesh/hello");
      if (name === "train") return jget(HW + "/v1/train/status");
      if (name === "usage") {
        if (!auth?.api_key) throw new Error("Sign in required");
        return jget(CLOUD + "/api/v1/usage", authHeaders());
      }
      throw portalErr;
    }
  }

  document.querySelectorAll(".tool").forEach((btn) => {
    btn.onclick = async () => {
      const t = btn.dataset.tool;
      if (!els.toolOut) return;
      els.toolOut.textContent = "Loading…";
      try {
        const data = await fetchTool(t);
        els.toolOut.textContent = JSON.stringify(data, null, 2);
      } catch (e) {
        const msg = String(e && e.message ? e.message : e);
        els.toolOut.textContent =
          "Could not load " +
          t +
          ".\n\n" +
          msg +
          "\n\nTips:\n" +
          "• Use Tools while signed in on the portal (same tab origin)\n" +
          "• Ensure cloud: sophyane --cloud-serve (:8780)\n" +
          "• Optional hardware: sophyane --hardware-api (:8770)\n" +
          "• Optional mesh: sophyane --mesh-serve (:8777)";
      }
    };
  });

  els.btnShare.onclick = async () => {
    const s = active();
    if (!s || !s.messages.length) return;
    const header = auth ? `Chat as ${auth.email}\n\n` : "";
    const text =
      header + s.messages.map((m) => `${m.role === "user" ? "You" : "Sophyane"}: ${m.content}`).join("\n\n");
    try {
      await navigator.clipboard.writeText(text);
      els.btnShare.textContent = "✓";
      setTimeout(() => {
        els.btnShare.textContent = "⤴";
      }, 1200);
    } catch (_) {}
  };

  // Default Edge off so general chat always hits the live model (user can re-enable).
  if (els.edgeMode && localStorage.getItem("sophyane_edge_pref") == null) {
    els.edgeMode.checked = false;
  } else if (els.edgeMode) {
    els.edgeMode.checked = localStorage.getItem("sophyane_edge_pref") === "1";
  }
  if (els.edgeMode) {
    els.edgeMode.addEventListener("change", () => {
      localStorage.setItem("sophyane_edge_pref", els.edgeMode.checked ? "1" : "0");
    });
  }

  // Boot
  updateAuthTabs();
  if (auth && auth.api_key && auth.email) {
    showApp();
    loadLlmCatalog().catch(() => {});
  } else {
    showAuth();
  }
})();
