/* Sophyane Agent Harness — Grok CLI-style agent window */
(function () {
  "use strict";

  const AUTH_KEY = "sophyane_auth_v1";

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

  const CLOUD = detectCloud();
  let auth = null;
  try {
    auth = JSON.parse(localStorage.getItem(AUTH_KEY) || "null");
  } catch (_) {
    auth = null;
  }
  if (!auth || !auth.api_key) {
    const key = localStorage.getItem("sophyane_api_key");
    const email = localStorage.getItem("sophyane_user_email");
    if (key) auth = { api_key: key, email: email || "" };
  }

  const term = document.getElementById("term");
  const form = document.getElementById("cliForm");
  const input = document.getElementById("cliInput");
  const send = document.getElementById("cliSend");
  const userEl = document.getElementById("cliUser");

  const history = [];
  let histIdx = -1;
  let busy = false;

  userEl.textContent = auth?.email
    ? auth.email + (auth.plan ? " · " + auth.plan : "")
    : "not signed in — open Chat UI and log in with OTP first";

  const modelEl = document.getElementById("cliModel");
  async function refreshModelLabel() {
    try {
      const res = await fetch(CLOUD + "/api/v1/llm/catalog");
      const data = await res.json();
      if (data.active && modelEl) {
        modelEl.textContent =
          "model: " + (data.active.provider || "?") + " / " + (data.active.model || "?");
      }
    } catch (_) {
      if (modelEl) modelEl.textContent = "model: (catalog offline)";
    }
  }
  refreshModelLabel();

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function linkify(text) {
    return escapeHtml(text).replace(
      /(https?:\/\/[^\s<]+)/g,
      '<a href="$1" target="_blank" rel="noopener">$1</a>'
    );
  }

  function append(kind, text) {
    const div = document.createElement("div");
    div.className = "line " + kind;
    div.innerHTML = linkify(text);
    term.appendChild(div);
    term.scrollTop = term.scrollHeight;
  }

  function helpText() {
    return [
      "Sophyane Agent Harness commands",
      "  /help              this help",
      "  /tools             list local tools",
      "  /clear             clear terminal",
      "  /status            account + portal",
      "  /search <query>    live web search only",
      "  /system /cpu /ram /disk /network /git /files",
      "",
      "Natural agent tasks (plan → web/tools → answer):",
      "  who is Imran Khan",
      "  check my system configuration",
      "  explain hybrid edge compute",
      "",
      "Auth is shared with the Chat UI (email OTP).",
    ].join("\n");
  }

  append("sys", "session ready · portal " + CLOUD);
  if (!auth?.api_key) {
    append("err", "No API key in this browser. Open Chat UI, sign in with email OTP, then reopen Harness.");
  } else {
    append("sys", "authenticated · type a task or /help");
  }

  async function runAgent(message) {
    const res = await fetch(CLOUD + "/api/v1/agent", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + auth.api_key,
      },
      body: JSON.stringify({ message }),
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || "agent failed HTTP " + res.status);
    }
    return data;
  }

  async function runSearch(query) {
    const res = await fetch(CLOUD + "/api/v1/search", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + auth.api_key,
      },
      body: JSON.stringify({ query }),
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || "search failed");
    }
    return data;
  }

  form.onsubmit = async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;

    history.push(text);
    histIdx = history.length;
    input.value = "";
    append("user", "sophyane> " + text);

    if (text === "/help" || text === "help") {
      append("agent", helpText());
      return;
    }
    if (text === "/clear") {
      term.innerHTML = "";
      append("sys", "cleared");
      return;
    }
    if (text === "/status") {
      append(
        "agent",
        "portal: " +
          CLOUD +
          "\nuser: " +
          (auth?.email || "—") +
          "\nplan: " +
          (auth?.plan || "—") +
          "\nkey: " +
          (auth?.api_key ? auth.api_key.slice(0, 12) + "…" : "missing")
      );
      return;
    }
    if (!auth?.api_key) {
      append("err", "Sign in via Chat UI first (email OTP), then reload this window.");
      return;
    }

    busy = true;
    send.disabled = true;
    append("sys", "… running agent loop");

    try {
      if (text.startsWith("/search ")) {
        const q = text.slice(8).trim();
        const data = await runSearch(q);
        const lines = (data.results || [])
          .map(
            (r, i) =>
              `[${i + 1}] ${r.title || "source"}\n${r.snippet || ""}\n${r.url || ""}`
          )
          .join("\n\n");
        append("agent", lines || "(no results)");
      } else {
        const data = await runAgent(text);
        if (Array.isArray(data.steps) && data.steps.length) {
          const stepLine = data.steps
            .map((s) => (s.ok === false ? "✗" : "✓") + " " + (s.step || "?"))
            .join(" · ");
          append("step", "trace: " + stepLine + (data.model ? " · " + data.model : ""));
        }
        append("agent", data.reply || "(empty)");
      }
    } catch (err) {
      append("err", String(err.message || err));
    }

    busy = false;
    send.disabled = false;
    input.focus();
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!history.length) return;
      histIdx = Math.max(0, histIdx - 1);
      input.value = history[histIdx] || "";
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      histIdx = Math.min(history.length, histIdx + 1);
      input.value = history[histIdx] || "";
    }
  });

  input.focus();
})();
