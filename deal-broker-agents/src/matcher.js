import { anonymizeEmail, stripEmails } from "./privacy.js";

export function rankDeals(buyers, sellers, options = {}) {
  const brokerageRate = options.brokerageRate ?? 0.01;
  const logisticsRate = options.logisticsRate ?? 0.03;
  const deals = [];

  for (const buyer of buyers) {
    for (const seller of sellers) {
      const productScore = similarity(buyer.product, seller.product);
      if (productScore < 0.15) continue;

      const matchedQuantity = Math.min(Number(buyer.quantity || 1), Number(seller.quantity || 1));
      const buyerPrice = buyer.unitPrice?.amount ?? null;
      const sellerPrice = seller.unitPrice?.amount ?? null;
      const currency = buyer.unitPrice?.currency || seller.unitPrice?.currency || "USD";
      const estimatedLogisticsPerUnit = sellerPrice ? Math.round(sellerPrice * logisticsRate * 100) / 100 : null;
      const sellerNetWithLogistics = sellerPrice && estimatedLogisticsPerUnit ? sellerPrice + estimatedLogisticsPerUnit : sellerPrice;
      const priceOverlap = buyerPrice && sellerNetWithLogistics ? buyerPrice >= sellerNetWithLogistics : null;
      const unitBrokerage = sellerPrice ? Math.round(sellerPrice * brokerageRate * 100) / 100 : null;
      const totalBrokerage = unitBrokerage ? Math.round(unitBrokerage * matchedQuantity * 100) / 100 : null;
      const score = Math.round((productScore * 50) + quantityScore(buyer.quantity, seller.quantity) + (priceOverlap ? 25 : 0));

      deals.push({
        score,
        product: stripEmails(bestProductName(buyer.product, seller.product)),
        currency,
        quantity: {
          buyerNeeds: buyer.quantity,
          sellerCanSupply: seller.quantity,
          matched: matchedQuantity,
          partialFulfillment: Number(seller.quantity || 1) < Number(buyer.quantity || 1)
        },
        price: {
          buyerIndicatedMax: buyerPrice,
          sellerIndicatedAsk: sellerPrice,
          estimatedLogisticsPerUnit,
          estimatedSellerPriceWithLogistics: sellerNetWithLogistics,
          priceOverlap
        },
        brokerage: {
          chargedTo: "seller",
          rate: brokerageRate,
          estimatedAmount: totalBrokerage,
          clearDisclosure: "A 1% brokerage fee is charged to the seller on closed deals."
        },
        safety: {
          escrowOffered: true,
          note: "Broker can offer an escrow account so buyer funds and seller goods are protected until agreed release conditions are met."
        },
        parties: {
          buyerId: anonymizeEmail(buyer.email),
          sellerId: anonymizeEmail(seller.email),
          emailsHidden: true
        },
        draftToSeller: buildSellerDraft({ buyer, seller, matchedQuantity, currency, brokerageRate }),
        draftToBuyer: buildBuyerDraft({ buyer, seller, matchedQuantity, currency })
      });
    }
  }

  return deals.sort((a, b) => b.score - a.score).slice(0, options.limit ?? 5);
}

function buildSellerDraft({ buyer, seller, matchedQuantity, currency, brokerageRate }) {
  return stripEmails(`We have a verified buyer intent for ${matchedQuantity} units of ${bestProductName(buyer.product, seller.product)}. Buyer identity/email is kept private until both sides approve. Please confirm final stock, delivery/logistics cost, and whether you accept escrow. Brokerage disclosure: ${brokerageRate * 100}% brokerage fee is charged to the seller only if the deal closes.`);
}

function buildBuyerDraft({ buyer, seller, matchedQuantity, currency }) {
  return stripEmails(`We found a seller that may supply ${matchedQuantity} units of ${bestProductName(buyer.product, seller.product)}. Seller identity/email is kept private until both sides approve. Escrow can be offered for safety of both parties. Please confirm target price, destination, inspection terms, and payment readiness.`);
}

function bestProductName(a, b) {
  return String(a || "").length >= String(b || "").length ? a : b;
}

function quantityScore(buyerQty = 1, sellerQty = 1) {
  const b = Number(buyerQty || 1);
  const s = Number(sellerQty || 1);
  return Math.round((Math.min(b, s) / Math.max(b, s)) * 25);
}

function similarity(a = "", b = "") {
  const aw = tokens(a);
  const bw = tokens(b);
  if (!aw.size || !bw.size) return 0;
  const intersection = [...aw].filter((w) => bw.has(w)).length;
  const union = new Set([...aw, ...bw]).size;
  return intersection / union;
}

function tokens(text) {
  return new Set(String(text).toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter((w) => w.length > 2));
}
