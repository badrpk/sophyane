import { stripEmails } from "./privacy.js";

const BUY_WORDS = ["buy", "buyer", "need", "looking for", "rfq", "request", "wanted", "require", "purchase"];
const SELL_WORDS = ["sell", "seller", "available", "stock", "offer", "supply", "supplier", "inventory", "for sale"];

export function extractIntent({ from, subject = "", text = "", date, source = "gmail" }) {
  const cleanText = stripEmails(`${subject}\n${text}`).slice(0, 5000);
  const lower = cleanText.toLowerCase();
  if (!isTradeIntent(lower)) return null;
  const role = score(lower, BUY_WORDS) >= score(lower, SELL_WORDS) ? "buyer" : "seller";
  const quantity = extractQuantity(lower);
  const price = extractPrice(cleanText);
  const product = extractProduct(subject, text);

  return {
    source,
    role,
    email: from?.address || from?.text || String(from || ""),
    subject: stripEmails(subject),
    date,
    product,
    quantity,
    unitPrice: price,
    currency: price ? price.currency : "USD",
    text: cleanText
  };
}

export function splitIntents(intents) {
  const valid = intents.filter(Boolean);
  return {
    buyers: valid.filter((i) => i.role === "buyer"),
    sellers: valid.filter((i) => i.role === "seller")
  };
}

function isTradeIntent(text) {
  const noise = ["github", "workflow run", "job alert", "unsubscribe", "newsletter", "password reset"];
  if (noise.some((word) => text.includes(word))) return false;
  const hasBuy = score(text, BUY_WORDS) > 0;
  const hasSell = score(text, SELL_WORDS) > 0;
  const hasCommercialClue = /\b(qty|quantity|units|pcs|pieces|stock|price|quote|quotation|delivery|logistics|payment|escrow|bulk|wholesale)\b/i.test(text);
  return (hasBuy || hasSell) && hasCommercialClue;
}

function score(text, words) {
  return words.reduce((sum, word) => sum + (text.includes(word) ? 1 : 0), 0);
}

function extractQuantity(text) {
  const patterns = [
    /(?:qty|quantity|need|available|stock|supply|wanted|order)\D{0,20}(\d{1,7})/i,
    /(\d{1,7})\s*(?:pcs|pieces|units|laptops|phones|cars|items)/i
  ];
  for (const p of patterns) {
    const match = text.match(p);
    if (match) return Number(match[1]);
  }
  return 1;
}

function extractPrice(text) {
  const match = text.match(/(?:USD|US\$|\$|EUR|€|GBP|£|AED|د\.إ)\s*([0-9][0-9,]*(?:\.\d+)?)/i);
  if (!match) return null;
  const rawCurrency = match[0].replace(match[1], "").trim().toUpperCase();
  const currency = rawCurrency.includes("EUR") || rawCurrency.includes("€") ? "EUR"
    : rawCurrency.includes("GBP") || rawCurrency.includes("£") ? "GBP"
    : rawCurrency.includes("AED") || rawCurrency.includes("د") ? "AED"
    : "USD";
  return { amount: Number(match[1].replace(/,/g, "")), currency };
}

function extractProduct(subject = "", text = "") {
  const combined = `${subject} ${text}`.replace(/\s+/g, " ").trim();
  const afterFor = combined.match(/(?:for|need|looking for|available|sell|buy)\s+(.{3,80})/i);
  const value = afterFor ? afterFor[1] : combined.slice(0, 80);
  return value.replace(/[.,;].*$/, "").trim() || "Unknown product/service";
}
