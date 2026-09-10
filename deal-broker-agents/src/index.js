#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { BuyerAgent, SellerAgent, BrokerAgent } from "./agents.js";

const inputPath = process.argv[2];

if (!inputPath) {
  console.log("Usage: node src/index.js <enquiry.json>");
  console.log("Example: npm run demo");
  process.exit(1);
}

const fullPath = path.resolve(inputPath);
const enquiry = JSON.parse(fs.readFileSync(fullPath, "utf8"));
validate(enquiry);

const buyerAgent = new BuyerAgent(enquiry.buyer);
const sellerAgent = new SellerAgent(enquiry.seller);
const brokerAgent = new BrokerAgent();

const context = {
  buyer: enquiry.buyer,
  seller: enquiry.seller,
  currency: enquiry.currency ?? "USD",
  quantity: enquiry.quantity ?? 1
};

const buyerView = buyerAgent.evaluate(context);
const sellerView = sellerAgent.evaluate(context);
const result = brokerAgent.broker(enquiry, buyerView, sellerView);

console.log(JSON.stringify(result, null, 2));

function validate(enquiry) {
  const required = ["buyer", "seller"];
  for (const key of required) {
    if (!enquiry[key]) throw new Error(`Missing ${key}`);
  }
  if (enquiry.buyer.maxUnitPrice == null) throw new Error("Missing buyer.maxUnitPrice");
  if (enquiry.seller.askingUnitPrice == null) throw new Error("Missing seller.askingUnitPrice");
  if (enquiry.seller.minUnitPrice == null) throw new Error("Missing seller.minUnitPrice");
}
