import { SophyaneClient } from "./sophyane-client.js";

const client = new SophyaneClient(process.env.SOPHYANE_API || "http://127.0.0.1:8770");
const health = await client.health();
console.log("health", JSON.stringify(health, null, 2));
const backends = await client.backends();
console.log("backends", backends);
try {
  const chat = await client.chat("Say hi in three words", { edge: true });
  console.log("chat", chat);
} catch (err) {
  console.error("chat failed (is sophyane --hardware-api running?)", err.message);
}
