import crypto from "node:crypto";

export function anonymizeEmail(email) {
  if (!email) return null;
  const hash = crypto.createHash("sha256").update(String(email).toLowerCase()).digest("hex").slice(0, 8);
  return `party-${hash}`;
}

export function stripEmails(text = "") {
  return String(text).replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[hidden-email]");
}

export function publicParty(party) {
  return {
    id: anonymizeEmail(party.email || party.from),
    role: party.role,
    source: party.source,
    subject: stripEmails(party.subject),
    text: stripEmails(party.text)
  };
}
