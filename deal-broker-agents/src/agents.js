export class BuyerAgent {
  constructor(profile) {
    this.profile = profile;
  }

  evaluate({ seller, currency, quantity }) {
    const max = Number(this.profile.maxUnitPrice);
    const target = Number(this.profile.targetUnitPrice ?? max * 0.9);
    const asking = Number(seller.askingUnitPrice);
    const sellerMin = Number(seller.minUnitPrice ?? asking * 0.9);
    const overlap = sellerMin <= max;
    const opening = clamp(Math.round((target + sellerMin) / 2), target, max);
    const walkAway = max;

    return {
      agent: "buyer",
      goal: "Get required goods/services at best price and safe terms.",
      acceptsCurrentOffer: asking <= max,
      openingUnitPrice: opening,
      walkAwayUnitPrice: walkAway,
      requestedTerms: this.profile.mustHave ?? [],
      paymentPosition: this.profile.preferredPayment,
      message: overlap
        ? `Buyer can negotiate. Opens at ${money(opening, currency)} x ${quantity}, but can go up to ${money(walkAway, currency)} if key terms are met.`
        : `Buyer cannot meet seller minimum. Max is ${money(walkAway, currency)}.`
    };
  }
}

export class SellerAgent {
  constructor(profile) {
    this.profile = profile;
  }

  evaluate({ buyer, currency, quantity }) {
    const asking = Number(this.profile.askingUnitPrice);
    const min = Number(this.profile.minUnitPrice ?? asking * 0.85);
    const buyerMax = Number(buyer.maxUnitPrice);
    const overlap = min <= buyerMax;
    const counter = clamp(Math.round((asking + buyerMax) / 2), min, asking);

    return {
      agent: "seller",
      goal: "Maximize price while protecting payment and delivery terms.",
      acceptsBuyerBudget: buyerMax >= min,
      counterUnitPrice: counter,
      floorUnitPrice: min,
      offeredTerms: this.profile.canOffer ?? [],
      paymentPosition: this.profile.preferredPayment,
      message: overlap
        ? `Seller can negotiate. Counters at ${money(counter, currency)} x ${quantity}, floor is ${money(min, currency)}.`
        : `Seller cannot meet buyer max. Floor is ${money(min, currency)}.`
    };
  }
}

export class BrokerAgent {
  broker(enquiry, buyerView, sellerView) {
    const currency = enquiry.currency ?? "USD";
    const quantity = Number(enquiry.quantity ?? 1);
    const low = Number(enquiry.seller.minUnitPrice);
    const high = Number(enquiry.buyer.maxUnitPrice);
    const overlap = low <= high;
    const proposedUnitPrice = overlap ? Math.round((low + high) / 2) : null;
    const buyerTerms = enquiry.buyer.mustHave ?? [];
    const sellerTerms = enquiry.seller.canOffer ?? [];
    const matchedTerms = buyerTerms.filter((term) =>
      sellerTerms.some((offer) => similar(term, offer))
    );
    const missingTerms = buyerTerms.filter((term) => !matchedTerms.includes(term));

    return {
      dealId: enquiry.dealId,
      status: overlap ? "possible_deal" : "no_price_overlap",
      product: enquiry.product,
      quantity,
      buyerView,
      sellerView,
      proposal: overlap
        ? {
            unitPrice: proposedUnitPrice,
            totalPrice: proposedUnitPrice * quantity,
            currency,
            suggestedPayment: mergePayment(enquiry.buyer.preferredPayment, enquiry.seller.preferredPayment),
            matchedTerms,
            termsToResolve: missingTerms,
            humanApprovalRequired: true
          }
        : {
            reason: `Seller floor ${money(low, currency)} is above buyer max ${money(high, currency)}.`,
            gapPerUnit: low - high,
            humanApprovalRequired: true
          },
      nextMessageDraft: overlap
        ? `Potential agreement: ${quantity} x ${enquiry.product} at ${money(proposedUnitPrice, currency)} each (${money(proposedUnitPrice * quantity, currency)} total), subject to resolving: ${missingTerms.join(", ") || "none"}.`
        : `No deal yet: price gap is ${money(low - high, currency)} per unit. Ask buyer to increase budget or seller to reduce floor.`
    };
  }
}

function money(value, currency) {
  return `${currency} ${Number(value).toLocaleString()}`;
}

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

function similar(a, b) {
  const aw = normalize(a).split(" ");
  const bn = normalize(b);
  return aw.some((word) => word.length > 3 && bn.includes(word));
}

function normalize(text) {
  return String(text).toLowerCase().replace(/[^a-z0-9 ]/g, " ");
}

function mergePayment(buyerPayment, sellerPayment) {
  if (!buyerPayment && !sellerPayment) return "To be negotiated";
  if (!buyerPayment) return sellerPayment;
  if (!sellerPayment) return buyerPayment;
  return `Compromise suggested between buyer (${buyerPayment}) and seller (${sellerPayment})`;
}
