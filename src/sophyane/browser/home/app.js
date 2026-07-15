/* Sophyane Browser — ChatGPT UI + email OTP auth + logged-in user display */
(function () {
  "use strict";

  const AUTH_KEY = "sophyane_auth_v1";
  const STORAGE_KEY = "sophyane_chatgpt_sessions_v1";

  function detectCloud() {
    const stored = localStorage.getItem("sophyane_cloud");
    if (stored) return stored.replace(/\/$/, "");
    // Same origin when served from portal /browser-home/
    if (location.port === "8780" || location.pathname.includes("browser-home") || location.pathname.includes("browser")) {
      return location.origin;
    }
    // Common local portal
    return "http://127.0.0.1:8780";
  }

  const HW = localStorage.getItem("sophyane_hw") || "http://127.0.0.1:8770";
  const MESH = localStorage.getItem("sophyane_mesh") || "http://127.0.0.1:8777";
  let CLOUD = detectCloud();

  /** @type {{email:string,name:string,plan:string,api_key:string,user_id?:string}|null} */
  let auth = loadAuth();
  let authPurpose = "login";
  let sessions = loadSessions();
  let activeId = sessions[0]?.id || null;
  let busy = false;

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
    btnTools: $("btnTools"),
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
    // migrate old key-only storage
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

  // —— Chat (requires auth) ——
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

  async function chatApi(message, edge) {
    if (!auth?.api_key) throw new Error("Not signed in");
    // Prefer cloud portal with user key (authenticated)
    try {
      const res = await fetch(CLOUD + "/api/v1/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: "Bearer " + auth.api_key,
        },
        body: JSON.stringify({ message, edge: !!edge }),
      });
      const data = await res.json();
      if (!res.ok || data.ok === false) {
        throw new Error(data.error || "chat failed");
      }
      return {
        reply: String(data.reply || data.error || JSON.stringify(data)),
        sources: [],
      };
    } catch (cloudErr) {
      // Fallback local hardware API (still show user as logged in)
      try {
        const data = await jpost(HW + "/v1/hardware/chat", { message, edge: !!edge });
        const reply =
          data.reply ||
          data.result?.reply ||
          (typeof data.result === "string" ? data.result : null) ||
          data.error ||
          JSON.stringify(data);
        return { reply: String(reply), sources: [] };
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

    try {
      let prompt = text;
      let sources = [];
      const page = await maybeFetchSource(text);
      if (page && page.text) {
        sources.push({ url: page.url, title: page.title });
        prompt =
          `Use this page content when answering.\nURL: ${page.url}\nTitle: ${page.title}\n\n` +
          `${page.text}\n\nUser (${auth.email}): ${text}`;
      } else {
        prompt = `User (${auth.email}): ${text}`;
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

  function openDrawer() {
    els.drawer.hidden = false;
    renderUser();
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

  // Boot
  updateAuthTabs();
  if (auth && auth.api_key && auth.email) {
    showApp();
  } else {
    showAuth();
  }
})();
