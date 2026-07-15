/**
 * Sophyane JavaScript / Node / browser client
 * Talks to Hardware API (default http://127.0.0.1:8770)
 *
 * Node 18+: global fetch
 * Browser: same API
 * CommonJS: const { SophyaneClient } = require('./sophyane-client.js')
 */

const DEFAULT_BASE =
  (typeof process !== "undefined" && process.env && process.env.SOPHYANE_API) ||
  "http://127.0.0.1:8770";

class SophyaneClient {
  constructor(baseUrl = DEFAULT_BASE) {
    this.baseUrl = String(baseUrl || DEFAULT_BASE).replace(/\/$/, "");
  }

  async _get(path) {
    const res = await fetch(this.baseUrl + path, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${path}`);
    return res.json();
  }

  async _post(path, body) {
    const res = await fetch(this.baseUrl + path, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${path}`);
    return res.json();
  }

  health() {
    return this._get("/v1/hardware/health");
  }
  platform() {
    return this._get("/v1/hardware/platform");
  }
  compatibility() {
    return this._get("/v1/hardware/compat");
  }
  backends() {
    return this._get("/v1/hardware/backends");
  }
  software() {
    return this._get("/v1/hardware/software");
  }
  chat(message, { edge = false } = {}) {
    return this._post("/v1/hardware/chat", { message, edge: !!edge });
  }
  rpc(method, params = {}) {
    return this._post("/v1/hardware/rpc", { method, params });
  }
}

// UMD-ish exports
if (typeof module !== "undefined" && module.exports) {
  module.exports = { SophyaneClient, DEFAULT_BASE };
}
if (typeof globalThis !== "undefined") {
  globalThis.SophyaneClient = SophyaneClient;
}

export { SophyaneClient, DEFAULT_BASE };
