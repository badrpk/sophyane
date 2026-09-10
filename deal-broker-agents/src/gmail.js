#!/usr/bin/env node
import "dotenv/config";
import readline from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import { ImapFlow } from "imapflow";
import { simpleParser } from "mailparser";
import { extractIntent, splitIntents } from "./intentExtractor.js";
import { rankDeals } from "./matcher.js";
import { publicParty } from "./privacy.js";

const GMAIL_USER = process.env.GMAIL_USER || "badrpk@gmail.com";
const limit = Number(process.argv[2] || process.env.GMAIL_SCAN_LIMIT || 500);
const mailboxName = process.env.GMAIL_MAILBOX || "INBOX";

const password = process.env.GMAIL_APP_PASSWORD || await promptPassword(`Gmail app password for ${GMAIL_USER}: `);
if (!password) {
  console.error("No Gmail app password received. Run this in your terminal and enter the password when prompted, or set GMAIL_APP_PASSWORD.");
  process.exit(1);
}

const client = new ImapFlow({
  host: "imap.gmail.com",
  port: 993,
  secure: true,
  auth: { user: GMAIL_USER, pass: password },
  logger: false
});

await client.connect();
const lock = await client.getMailboxLock(mailboxName);
try {
  const mailbox = client.mailbox;
  const start = Math.max(1, mailbox.exists - limit + 1);
  const intents = [];

  for await (const msg of client.fetch(`${start}:*`, { envelope: true, source: true })) {
    const parsed = await simpleParser(msg.source);
    intents.push(extractIntent({
      from: parsed.from?.value?.[0],
      subject: parsed.subject || msg.envelope?.subject || "",
      text: parsed.text || parsed.html || "",
      date: parsed.date?.toISOString(),
      source: "gmail-inbox"
    }));
  }

  const { buyers, sellers } = splitIntents(intents);
  const topDeals = rankDeals(buyers, sellers, { limit: 5, brokerageRate: 0.01 });

  console.log(JSON.stringify({
    account: GMAIL_USER,
    mailbox: mailboxName,
    scannedMessages: intents.length,
    buyersFound: buyers.length,
    sellersFound: sellers.length,
    privacy: "Buyer and seller email addresses are hidden in outputs; only anonymized party IDs are shown.",
    brokerageDisclosure: "A 1% brokerage fee is charged to the seller on closed deals.",
    logistics: "Matches use available quantity and estimate logistics cost when seller price is known.",
    escrow: "Broker can offer escrow for safety of buyer and seller.",
    sampleIntents: intents.filter(Boolean).slice(0, 5).map(publicParty),
    topDeals
  }, null, 2));
} finally {
  lock.release();
  await client.logout();
}

async function promptPassword(prompt) {
  if (!process.stdin.isTTY) return "";
  output.write(prompt);
  await setEcho(false);
  const rl = readline.createInterface({ input, output, terminal: true });
  const value = await rl.question("");
  rl.close();
  await setEcho(true);
  output.write("\n");
  return value.trim();
}

function setEcho(enabled) {
  return new Promise((resolve) => {
    const mode = enabled ? "echo" : "-echo";
    import("node:child_process").then(({ exec }) => {
      exec(`stty ${mode}`, () => resolve());
    });
  });
}
