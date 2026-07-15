const HW = "http://127.0.0.1:8770";
const MESH = "http://127.0.0.1:8777";

const statusEl = document.getElementById("status");
const meshEl = document.getElementById("mesh");
const outEl = document.getElementById("out");
const urlEl = document.getElementById("url");

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

function show(el, data) {
  el.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
}

async function refresh() {
  try {
    const health = await jget(HW + "/v1/hardware/health");
    show(statusEl, health);
  } catch (e) {
    show(statusEl, "Hardware API offline on :8770 — start sophyane browser/APIs\n" + e);
  }
  try {
    const mesh = await jget(MESH + "/v1/mesh/hello");
    show(meshEl, mesh);
  } catch (e) {
    show(meshEl, "Mesh offline on :8777\n" + e);
  }
}

document.getElementById("goFetch").onclick = async () => {
  const q = urlEl.value.trim();
  if (!q) return;
  show(outEl, "Fetching…");
  try {
    // Prefer local CLI bridge via hardware rpc if available later; for browser we show intent.
    const data = await jpost(HW + "/v1/hardware/rpc", {
      method: "web_fetch",
      params: { url: q },
    });
    show(outEl, data);
  } catch (e) {
    show(outEl, "Fetch via API failed. Ensure sophyane --browser or hardware-api is running with web_intel.\n" + e);
  }
};

document.getElementById("goChat").onclick = async () => {
  const q = urlEl.value.trim() || "Hello from Sophyane Browser";
  show(outEl, "Asking…");
  try {
    const data = await jpost(HW + "/v1/hardware/chat", { message: q, edge: true });
    show(outEl, data);
  } catch (e) {
    show(outEl, "Chat failed: " + e);
  }
};

document.getElementById("goImprove").onclick = async () => {
  const q = urlEl.value.trim();
  show(outEl, "Recording improvement insight…");
  try {
    const data = await jpost(HW + "/v1/hardware/rpc", {
      method: "improve_from_url",
      params: { url: q || "https://example.com" },
    });
    show(outEl, data);
  } catch (e) {
    show(outEl, "Improve failed: " + e);
  }
};

refresh();
setInterval(refresh, 15000);
