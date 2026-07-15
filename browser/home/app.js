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
  /** @type {any|null} */
  let hwFit = null;
  let hwPollTimer = null;

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

  function webSearchEnabled() {
    const el = $("webSearchMode");
    if (el) return !!el.checked;
    return true; // default on
  }

  function updateRailStatus() {
    const el = $("railStatus");
    if (!el) return;
    const search = webSearchEnabled() ? "Search on" : "Search off";
    const model =
      llmStatus && llmStatus.active
        ? (llmStatus.active.provider || "") + "/" + (llmStatus.active.model || "")
        : "local fallback";
    el.textContent = search + " · " + model;
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
          // true = force web, false = off, null = auto heuristic
          web_search: webSearchEnabled() ? true : false,
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

  // —— Voice: speech → editable text → send; hands-free talk mode; YouTube ——
  let talkMode = localStorage.getItem("sophyane_talk_mode") === "1";
  let recognition = null;
  let listening = false;
  let voiceFinal = "";
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  function setVoiceStatus(msg) {
    const el = $("voiceStatus");
    if (el) el.textContent = msg || "";
  }

  function ttsEnabled() {
    const el = $("ttsMode");
    return el ? !!el.checked : true;
  }

  function speakText(text, onDone) {
    try {
      window.speechSynthesis.cancel();
    } catch (_) {}
    if (!ttsEnabled() || !window.speechSynthesis) {
      if (onDone) onDone();
      return;
    }
    const clean = String(text || "")
      .replace(/\*\*/g, "")
      .replace(/`+/g, "")
      .replace(/https?:\/\/\S+/g, "link")
      .replace(/\n+/g, ". ")
      .slice(0, 1200);
    if (!clean.trim()) {
      if (onDone) onDone();
      return;
    }
    const u = new SpeechSynthesisUtterance(clean);
    u.rate = 1.02;
    u.pitch = 1;
    u.onend = () => {
      if (onDone) onDone();
    };
    u.onerror = () => {
      if (onDone) onDone();
    };
    window.speechSynthesis.speak(u);
  }

  function stopSpeaking() {
    try {
      window.speechSynthesis.cancel();
    } catch (_) {}
    setVoiceStatus(talkMode ? "Talk mode on — tap Speak or wait" : "Voice ready");
  }

  function playYouTube(play, title) {
    const box = $("ytPlayer");
    const frame = $("ytFrame");
    const titleEl = $("ytTitle");
    if (!box || !frame) {
      if (play && play.url) window.open(play.url, "_blank", "noopener");
      return;
    }
    const embed = (play && (play.embed_url || play.url)) || "";
    if (!embed) return;
    box.hidden = false;
    if (titleEl) titleEl.textContent = title || play.title || "YouTube";
    // Use embed with autoplay when possible
    let src = embed;
    if (play.video_id) {
      src = "https://www.youtube.com/embed/" + play.video_id + "?autoplay=1&rel=0";
    } else if (play.url && play.url.includes("watch")) {
      const m = play.url.match(/v=([A-Za-z0-9_-]+)/);
      if (m) src = "https://www.youtube.com/embed/" + m[1] + "?autoplay=1&rel=0";
    }
    frame.src = src;
    // Also open full YouTube for mobile / autoplay policies
    try {
      window.open(play.url || src, "_blank", "noopener");
    } catch (_) {}
  }

  function closeYouTube() {
    const box = $("ytPlayer");
    const frame = $("ytFrame");
    if (frame) frame.src = "";
    if (box) box.hidden = true;
  }
  if ($("ytClose")) $("ytClose").onclick = closeYouTube;

  async function handleVoiceIntent(text) {
    try {
      const data = await jpost(CLOUD + "/api/v1/voice/intent", { text }, authHeaders());
      if (!data || !data.ok) return null;
      if (data.intent === "youtube_play") {
        const yt = data.youtube || {};
        const play = yt.play || (yt.results && yt.results[0]);
        const speak =
          data.speak ||
          (play
            ? "Playing " + (play.title || data.query) + " on YouTube."
            : "Opening YouTube search for " + data.query);
        if (play) playYouTube(play, play.title);
        else if (yt.search_page) window.open(yt.search_page, "_blank", "noopener");
        return { handled: true, reply: speak, speak };
      }
      if (data.intent === "web_search") {
        // Force search path through chat with web_search true
        return {
          handled: false,
          forceSearch: true,
          message: data.query || text,
          speak: data.speak || "Searching.",
        };
      }
    } catch (_) {}
    // Client-side fallback intents
    const low = text.toLowerCase().trim();
    const playM = low.match(
      /^(?:play|watch|put on|youtube)\s+(?:the\s+)?(?:song\s+|music\s+|video\s+)?(.+?)(?:\s+on\s+youtube)?$/i
    );
    if (playM) {
      const q = playM[1].trim();
      try {
        const yt = await jpost(CLOUD + "/api/v1/media/youtube", { query: q }, authHeaders());
        const play = yt.play || (yt.results && yt.results[0]);
        if (play) playYouTube(play, play.title);
        else if (yt.search_page) window.open(yt.search_page, "_blank", "noopener");
        return {
          handled: true,
          reply: play
            ? "Playing " + (play.title || q) + " on YouTube."
            : "Opened YouTube search for " + q,
        };
      } catch (e) {
        window.open(
          "https://www.youtube.com/results?search_query=" + encodeURIComponent(q),
          "_blank",
          "noopener"
        );
        return { handled: true, reply: "Opened YouTube for " + q };
      }
    }
    return null;
  }

  function updateTalkUi() {
    const b1 = $("btnTalkToggle");
    const b2 = $("btnTalkMode");
    const label = talkMode ? "Talk mode: On" : "Talk mode: Off";
    if (b1) {
      b1.textContent = label;
      b1.classList.toggle("active-talk", talkMode);
    }
    if (b2) {
      b2.textContent = talkMode ? "🎙 Talk ON" : "🎙 Talk mode";
      b2.classList.toggle("active-talk", talkMode);
    }
  }

  function setListeningUi(on) {
    listening = on;
    ["btnMic", "btnMicInline"].forEach((id) => {
      const b = $(id);
      if (b) b.classList.toggle("listening", on);
    });
  }

  function ensureRecognition() {
    if (!SpeechRecognition) {
      setVoiceStatus("Speech not supported in this browser — try Chrome/Edge");
      return null;
    }
    if (recognition) return recognition;
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = navigator.language || "en-US";
    recognition.onstart = () => {
      setListeningUi(true);
      setVoiceStatus("Listening… speak now (text will appear for edit)");
    };
    recognition.onerror = (ev) => {
      setListeningUi(false);
      setVoiceStatus("Mic: " + (ev.error || "error") + " — allow microphone permission");
    };
    recognition.onend = () => {
      setListeningUi(false);
      if (voiceFinal.trim()) {
        els.input.value = voiceFinal.trim();
        autoGrow();
        setVoiceStatus("Review text, edit if needed, then Send — or wait in Talk mode");
        if (talkMode && !busy) {
          // Auto-send after short pause so user can correct (1.2s)
          setTimeout(() => {
            if (talkMode && els.input.value.trim() && !busy) {
              els.composer.requestSubmit();
            }
          }, 1200);
        }
      } else {
        setVoiceStatus(talkMode ? "Didn't catch that — listening again…" : "No speech captured");
        if (talkMode) setTimeout(() => startListening(), 600);
      }
    };
    recognition.onresult = (event) => {
      let interim = "";
      let final = "";
      for (let i = 0; i < event.results.length; i++) {
        const r = event.results[i];
        if (r.isFinal) final += r[0].transcript;
        else interim += r[0].transcript;
      }
      if (final) voiceFinal = (voiceFinal + " " + final).trim();
      const show = (voiceFinal + (interim ? " " + interim : "")).trim();
      els.input.value = show;
      autoGrow();
    };
    return recognition;
  }

  function startListening() {
    if (!auth) {
      showAuth();
      setVoiceStatus("Sign in first, then use voice");
      return;
    }
    stopSpeaking();
    const rec = ensureRecognition();
    if (!rec) return;
    voiceFinal = "";
    try {
      rec.start();
    } catch (_) {
      try {
        rec.stop();
        setTimeout(() => {
          try {
            rec.start();
          } catch (e2) {
            setVoiceStatus("Could not start mic: " + e2);
          }
        }, 250);
      } catch (e) {
        setVoiceStatus("Mic busy: " + e);
      }
    }
  }

  function stopListening() {
    try {
      if (recognition) recognition.stop();
    } catch (_) {}
    setListeningUi(false);
  }

  function toggleTalkMode() {
    talkMode = !talkMode;
    localStorage.setItem("sophyane_talk_mode", talkMode ? "1" : "0");
    updateTalkUi();
    if (talkMode) {
      setVoiceStatus("Talk mode on — hands-free listen → type → send → speak");
      speakText("Talk mode on. I'm listening.", () => startListening());
    } else {
      stopListening();
      stopSpeaking();
      setVoiceStatus("Talk mode off");
    }
  }

  if ($("btnMic")) $("btnMic").onclick = () => (listening ? stopListening() : startListening());
  if ($("btnMicInline")) $("btnMicInline").onclick = () => (listening ? stopListening() : startListening());
  if ($("btnTalkToggle")) $("btnTalkToggle").onclick = toggleTalkMode;
  if ($("btnTalkMode")) $("btnTalkMode").onclick = toggleTalkMode;
  if ($("btnStopSpeak")) $("btnStopSpeak").onclick = () => {
    stopSpeaking();
    stopListening();
  };
  if ($("ttsMode")) {
    const pref = localStorage.getItem("sophyane_tts");
    if (pref === "0") $("ttsMode").checked = false;
    $("ttsMode").addEventListener("change", () => {
      localStorage.setItem("sophyane_tts", $("ttsMode").checked ? "1" : "0");
      if (!$("ttsMode").checked) stopSpeaking();
    });
  }
  updateTalkUi();
  if (!SpeechRecognition) setVoiceStatus("Use Chrome/Edge for voice on this device");

  els.composer.onsubmit = async (e) => {
    e.preventDefault();
    if (!auth) {
      showAuth();
      return;
    }
    const text = els.input.value.trim();
    if (!text || busy) return;

    stopListening();
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
    const history = historyPayload(s, true);
    let replyText = "";

    try {
      // Voice intents: YouTube play / search before normal chat
      const intent = await handleVoiceIntent(text);
      if (intent && intent.handled) {
        replyText = intent.reply || "Done.";
        s.messages[typingIdx] = { role: "assistant", content: replyText };
      } else {
        let prompt = (intent && intent.message) || text;
        let sources = [];
        if (intent && intent.speak) setVoiceStatus(intent.speak);
        const page = await maybeFetchSource(prompt);
        if (page && page.text) {
          sources.push({ url: page.url, title: page.title });
          prompt =
            `Use this page content when answering.\nURL: ${page.url}\nTitle: ${page.title}\n\n` +
            `${page.text}\n\nQuestion: ${prompt}`;
        }
        // If user said "search …", force web search on for this turn
        if (intent && intent.forceSearch) {
          const ws = $("webSearchMode");
          if (ws) ws.checked = true;
        }
        const out = await chatApi(prompt, edge, history);
        const reply = out.reply;
        replyText = reply || "(empty reply)";
        const webSources = Array.isArray(out.sources) ? out.sources : [];
        const allSources = [...sources, ...webSources].filter((x, i, arr) => {
          if (!x || !x.url) return false;
          return arr.findIndex((y) => y.url === x.url) === i;
        });
        s.messages[typingIdx] = {
          role: "assistant",
          content: replyText,
          sources: allSources,
        };
      }
    } catch (err) {
      replyText =
        "Could not complete request while signed in as " +
        auth.email +
        ".\n\n" +
        String(err);
      s.messages[typingIdx] = {
        role: "assistant",
        content: replyText,
      };
    }

    busy = false;
    saveSessions();
    renderSidebar();
    renderThread();
    autoGrow();

    // Speak reply then continue listening in talk mode (hands-free loop)
    speakText(replyText, () => {
      if (talkMode) {
        setVoiceStatus("Your turn — listening…");
        startListening();
      } else {
        els.input.focus();
      }
    });
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

  // Main-surface action rail (always visible)
  const railModels = $("railModels");
  const railLocal = $("railLocal");
  const emptyModels = $("emptyModels");
  const btnLocalLlm = $("btnLocalLlm");
  const btnSearchMode = $("btnSearchMode");
  const webSearchMode = $("webSearchMode");

  if (railModels) railModels.onclick = () => openDrawer("models");
  if (emptyModels) emptyModels.onclick = () => openDrawer("models");
  if (btnSearchMode) {
    btnSearchMode.onclick = () => {
      if (webSearchMode) {
        webSearchMode.checked = !webSearchMode.checked;
        updateRailStatus();
      }
      setLlmMsg(
        webSearchEnabled()
          ? "Web search ON — factual questions use live internet research."
          : "Web search OFF — answers use the selected LLM only.",
        false
      );
    };
  }
  if (webSearchMode) {
    webSearchMode.addEventListener("change", updateRailStatus);
    // persist
    const pref = localStorage.getItem("sophyane_web_search");
    if (pref === "0") webSearchMode.checked = false;
    if (pref === "1") webSearchMode.checked = true;
    webSearchMode.addEventListener("change", () => {
      localStorage.setItem("sophyane_web_search", webSearchMode.checked ? "1" : "0");
      updateRailStatus();
    });
  }

  async function activateLocalFree() {
    openDrawer("models");
    await setLocalMode(false);
    await loadHardwareFit();
    setLlmMsg(
      "Local mode on. Review the hardware-fit offer and click Approve to download a model sized for this machine."
    );
  }
  if (railLocal) railLocal.onclick = activateLocalFree;
  if (btnLocalLlm) btnLocalLlm.onclick = activateLocalFree;

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
        (a.provider || "local") + " · " + (a.model || "model") + " ▾";
    } else {
      els.modelSelectLabel.textContent = "Pick model ▾";
    }
    updateRailStatus();
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
      await loadHardwareFit();
    } catch (e) {
      setLlmMsg("Could not load LLM catalog: " + e, true);
    }
  }

  function renderHardwareFit() {
    const box = $("hwFitBox");
    const offer = $("hwOfferBox");
    const offerText = $("hwOfferText");
    const list = $("hwModelList");
    const dlBox = $("hwDownloadBox");
    if (!box || !hwFit) return;

    const hw = hwFit.hardware || {};
    const prefs = hwFit.prefs || {};
    const cur = hwFit.current || {};
    box.innerHTML =
      `<strong>Hardware-fit local LLM</strong><br/>` +
      `Tier: <b>${escapeHtml(hw.tier || "?")}</b> — ${escapeHtml(hw.tier_meaning || "")}<br/>` +
      `RAM ${escapeHtml(String(hw.ram_mb || "?"))}MB · disk free ${escapeHtml(String(hw.disk_free_mb || "?"))}MB · CPUs ${escapeHtml(String(hw.cpus || "?"))}<br/>` +
      `Mode: ${prefs.prefer_api_only ? "<b>API only</b> (no local)" : prefs.local_enabled ? "<b>Local enabled</b>" : "local off"}<br/>` +
      `Active: ${escapeHtml(String(cur.active_provider || "—"))} / ${escapeHtml(String(cur.active_model || "—"))}` +
      (cur.llama_server_up ? " · llama-server up" : "");

    if (offer && offerText) {
      if (hwFit.upgrade_offer && !prefs.prefer_api_only) {
        offer.hidden = false;
        offerText.textContent = hwFit.upgrade_offer.message || "";
        offer.dataset.key = hwFit.upgrade_offer.key || "";
      } else {
        offer.hidden = true;
      }
    }

    if (list) {
      const models = hwFit.models || [];
      list.innerHTML = models
        .slice(0, 8)
        .map((m) => {
          const badge = m.installed
            ? "installed"
            : m.recommended
              ? "recommended for your hardware"
              : m.fits_ram && m.fits_disk
                ? "fits — needs approval"
                : !m.fits_ram
                  ? "needs more RAM"
                  : "needs more disk";
          const cls = m.recommended ? "plan-card current" : "plan-card";
          return (
            `<button type="button" class="${cls}" data-gguf="${escapeAttr(m.key)}">` +
            `<h4>${escapeHtml(m.key)}${m.recommended ? " · best fit" : ""}</h4>` +
            `<div class="price">~${escapeHtml(String(m.size_mb))}MB · min RAM ${escapeHtml(String(m.min_ram_mb))}MB · ${escapeHtml(badge)}</div>` +
            `<p>${escapeHtml(m.notes || "")}</p>` +
            `</button>`
          );
        })
        .join("");
      list.querySelectorAll("[data-gguf]").forEach((btn) => {
        btn.onclick = () => approveLocalModel(btn.dataset.gguf);
      });
    }

    if (dlBox) {
      const d = hwFit.download || {};
      if (d.status && d.status !== "idle") {
        dlBox.textContent =
          "Download: " +
          (d.status || "") +
          (d.model_key ? " · " + d.model_key : "") +
          (d.message ? " — " + d.message : "");
      } else {
        dlBox.textContent = "";
      }
    }
  }

  async function loadHardwareFit() {
    try {
      hwFit = await jget(CLOUD + "/api/v1/local/status");
      renderHardwareFit();
      // Poll while download running
      const d = hwFit.download || {};
      if (d.active || d.status === "running") {
        if (hwPollTimer) clearTimeout(hwPollTimer);
        hwPollTimer = setTimeout(loadHardwareFit, 2500);
      }
    } catch (e) {
      const box = $("hwFitBox");
      if (box) box.textContent = "Hardware-fit status unavailable: " + e;
    }
  }

  async function approveLocalModel(key) {
    if (!key) return;
    if (
      !confirm(
        "Download open local model \"" +
          key +
          "\" to this machine?\n\n" +
          "Only starts after you approve. Larger hardware gets stronger models. " +
          "You can stay API-only instead."
      )
    ) {
      return;
    }
    setLlmMsg("Starting approved download of " + key + "…");
    try {
      const data = await jpost(CLOUD + "/api/v1/local/approve", {
        model_key: key,
        background: true,
      });
      if (!data.ok) throw new Error(data.error || "approve failed");
      setLlmMsg(data.message || "Download started.");
      await loadHardwareFit();
      if (hwPollTimer) clearTimeout(hwPollTimer);
      hwPollTimer = setTimeout(loadHardwareFit, 2000);
    } catch (e) {
      setLlmMsg(String(e.message || e), true);
    }
  }

  async function setLocalMode(apiOnly) {
    try {
      const data = await jpost(CLOUD + "/api/v1/local/mode", {
        prefer_api_only: !!apiOnly,
        local_enabled: !apiOnly,
      });
      if (!data.ok) throw new Error(data.error || "mode failed");
      hwFit = data.status || hwFit;
      renderHardwareFit();
      setLlmMsg(
        apiOnly
          ? "API-only mode: frontier cloud models only (no local GGUF downloads)."
          : "Local LLMs enabled: hardware-fit open models can be offered with your approval."
      );
      await loadLlmCatalog();
    } catch (e) {
      setLlmMsg(String(e.message || e), true);
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

  const btnApiOnly = $("btnApiOnly");
  const btnEnableLocal = $("btnEnableLocal");
  const btnApproveLocal = $("btnApproveLocal");
  const btnDeclineLocal = $("btnDeclineLocal");
  if (btnApiOnly) btnApiOnly.onclick = () => setLocalMode(true);
  if (btnEnableLocal) btnEnableLocal.onclick = () => setLocalMode(false);
  if (btnApproveLocal) {
    btnApproveLocal.onclick = () => {
      const key = ($("hwOfferBox") && $("hwOfferBox").dataset.key) || (hwFit && hwFit.upgrade_offer && hwFit.upgrade_offer.key);
      if (key) approveLocalModel(key);
    };
  }
  if (btnDeclineLocal) {
    btnDeclineLocal.onclick = async () => {
      const key =
        ($("hwOfferBox") && $("hwOfferBox").dataset.key) ||
        (hwFit && hwFit.upgrade_offer && hwFit.upgrade_offer.key) ||
        "";
      try {
        await jpost(CLOUD + "/api/v1/local/decline", { model_key: key });
        await loadHardwareFit();
        setLlmMsg("Offer dismissed. You can install later from the list.");
      } catch (e) {
        setLlmMsg(String(e.message || e), true);
      }
    };
  }

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
      const bill = await jget(CLOUD + "/api/v1/billing/config");
      window.__sophyaneStripe = bill;
      if (bill && bill.enabled && els.upgradeMsg) {
        els.upgradeMsg.textContent =
          "Stripe " +
          (bill.mode || "") +
          " payments ready (" +
          (bill.currency || "gbp").toUpperCase() +
          "). Paid plans open secure Checkout.";
        els.upgradeMsg.classList.remove("err");
      }
    } catch (_) {}
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
      els.upgradeMsg.textContent = "Starting upgrade…";
      els.upgradeMsg.classList.remove("err");
    }
    try {
      const data = await jpost(
        CLOUD + "/api/v1/account/upgrade",
        { plan: planId },
        authHeaders()
      );
      if (!data.ok) throw new Error(data.error || "upgrade failed");
      // Paid plan → Stripe Checkout (Monzo-linked live Stripe)
      if (data.checkout && data.url) {
        if (els.upgradeMsg) {
          els.upgradeMsg.textContent = "Redirecting to secure Stripe Checkout…";
        }
        window.location.href = data.url;
        return;
      }
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
        els.upgradeMsg.textContent = String(e.message || e);
        els.upgradeMsg.classList.add("err");
      }
    }
  }

  async function confirmStripePaymentIfNeeded() {
    const params = new URLSearchParams(location.search);
    const paid = params.get("paid");
    const sessionId = params.get("session_id");
    if (paid !== "1" || !sessionId || !auth?.api_key) return;
    try {
      const data = await jpost(
        CLOUD + "/api/v1/billing/confirm",
        { session_id: sessionId },
        authHeaders()
      );
      if (data.ok && data.plan) {
        auth.plan = data.plan;
        saveAuth(auth);
        renderUser();
        openDrawer("upgrade");
        if (els.upgradeMsg) {
          els.upgradeMsg.textContent =
            data.message || "Payment received — plan " + data.plan + " active.";
          els.upgradeMsg.classList.remove("err");
        }
      } else if (els.upgradeMsg) {
        openDrawer("upgrade");
        els.upgradeMsg.textContent = data.error || "Payment confirm failed";
        els.upgradeMsg.classList.add("err");
      }
    } catch (e) {
      openDrawer("upgrade");
      if (els.upgradeMsg) {
        els.upgradeMsg.textContent = String(e.message || e);
        els.upgradeMsg.classList.add("err");
      }
    }
    // Clean URL
    try {
      history.replaceState({}, "", location.pathname);
    } catch (_) {}
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
    confirmStripePaymentIfNeeded().catch(() => {});
    // Show Stripe billing badge on upgrade drawer when available
    jget(CLOUD + "/api/v1/billing/config")
      .then((c) => {
        if (c && c.enabled && els.upgradeMsg) {
          /* leave quiet until open */
          window.__sophyaneStripe = c;
        }
      })
      .catch(() => {});
  } else {
    showAuth();
  }
})();
