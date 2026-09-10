"""Buyer, seller and broker agents for Sophyane.

This module provides the domain execution layer on top of the durable
PostgreSQL multi-agent coordination store.

Important authority boundary:

- public discovery/read operations may be performed by an attached
  discovery adapter;
- internal qualification, deduplication and matching are allowed;
- external contact, negotiation, commitment, payment or acceptance is
  never performed here;
- matches requiring external action stop at awaiting_user_approval.

A worker is RUNNING only when the process supervisor has assigned a real
worker identity and heartbeat is being maintained.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Literal, Mapping, Protocol
import hashlib
import json


LeadKind = Literal["buyer", "seller"]

LeadState = Literal[
    "discovered",
    "qualified",
    "rejected",
]

MatchState = Literal[
    "matched",
    "awaiting_user_approval",
    "contacted",
    "negotiating",
    "closed",
    "rejected",
]


@dataclass(frozen=True)
class Lead:
    kind: LeadKind
    product: str
    specification: str
    quantity: float | None
    price: Decimal | None
    currency: str
    location: str
    delivery_terms: str
    contact: str
    source_url: str
    discovered_at: datetime
    confidence: float
    state: LeadState = "discovered"
    rejection_reason: str = ""

    @property
    def fingerprint(self) -> str:
        material = "|".join(
            (
                self.kind.strip().lower(),
                self.product.strip().lower(),
                self.specification.strip().lower(),
                self.location.strip().lower(),
                self.contact.strip().lower(),
                self.source_url.strip().lower(),
            )
        )
        return hashlib.sha256(
            material.encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class Match:
    buyer: Lead
    seller: Lead
    compatibility_score: float
    gross_spread_per_unit: Decimal | None
    gross_spread_total: Decimal | None
    state: MatchState
    rationale: str


@dataclass
class AgentCounters:
    tasks_claimed: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    sources_processed: int = 0
    discovered: int = 0
    qualified: int = 0
    rejected: int = 0
    duplicates: int = 0
    matches_found: int = 0
    awaiting_approval: int = 0

    def progress_percent(
        self,
        *,
        expected_units: int | None = None,
    ) -> float:
        if expected_units is None or expected_units <= 0:
            if self.tasks_claimed == 0:
                return 0.0

            if self.tasks_completed >= self.tasks_claimed:
                return 100.0

            completed = self.tasks_completed
            failed = self.tasks_failed

            return min(
                99.0,
                100.0
                * (completed + failed)
                / max(self.tasks_claimed, 1),
            )

        processed = (
            self.qualified
            + self.rejected
            + self.duplicates
        )

        return min(
            100.0,
            100.0 * processed / expected_units,
        )


class DiscoveryAdapter(Protocol):
    """Public information discovery interface.

    Implementations may use NIFDU/browser/search systems. They must return
    structured public-source candidates and must not contact any party.
    """

    def discover(
        self,
        *,
        role: LeadKind,
        query: str,
        limit: int,
    ) -> Iterable[Mapping[str, Any]]:
        ...


class DiscoveryUnavailable(RuntimeError):
    pass


class DisabledDiscoveryAdapter:
    """Fail-closed adapter used until a search provider is explicitly wired."""

    def discover(
        self,
        *,
        role: LeadKind,
        query: str,
        limit: int,
    ) -> Iterable[Mapping[str, Any]]:
        raise DiscoveryUnavailable(
            "public discovery adapter is not enabled"
        )


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(
    value: Any,
) -> float | None:
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(
    value: Any,
) -> Decimal | None:
    if value is None or value == "":
        return None

    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def normalize_candidate(
    kind: LeadKind,
    candidate: Mapping[str, Any],
) -> Lead:
    timestamp = candidate.get("discovered_at")

    if isinstance(timestamp, datetime):
        discovered_at = timestamp
    else:
        discovered_at = datetime.now(timezone.utc)

    confidence = _number(
        candidate.get("confidence")
    )

    return Lead(
        kind=kind,
        product=_text(candidate.get("product")),
        specification=_text(
            candidate.get("specification")
        ),
        quantity=_number(candidate.get("quantity")),
        price=_money(
            candidate.get(
                "target_price"
                if kind == "buyer"
                else "asking_price"
            )
        ),
        currency=(
            _text(candidate.get("currency"))
            or "PKR"
        ).upper(),
        location=_text(candidate.get("location")),
        delivery_terms=_text(
            candidate.get("delivery_terms")
        ),
        contact=_text(candidate.get("contact")),
        source_url=_text(
            candidate.get("source_url")
        ),
        discovered_at=discovered_at,
        confidence=max(
            0.0,
            min(
                1.0,
                confidence
                if confidence is not None
                else 0.0,
            ),
        ),
    )


def qualify_lead(
    lead: Lead,
    *,
    minimum_confidence: float = 0.60,
) -> Lead:
    reasons: list[str] = []

    if not lead.product:
        reasons.append("missing product")

    if not lead.source_url:
        reasons.append("missing source URL")

    if not lead.location:
        reasons.append("missing location")

    if lead.quantity is not None and lead.quantity <= 0:
        reasons.append("invalid quantity")

    if lead.price is not None and lead.price <= 0:
        reasons.append("invalid price")

    if lead.confidence < minimum_confidence:
        reasons.append("low confidence")

    if reasons:
        return Lead(
            **{
                **asdict(lead),
                "state": "rejected",
                "rejection_reason": "; ".join(reasons),
            }
        )

    return Lead(
        **{
            **asdict(lead),
            "state": "qualified",
            "rejection_reason": "",
        }
    )


def deduplicate(
    leads: Iterable[Lead],
) -> tuple[list[Lead], int]:
    seen: set[str] = set()
    unique: list[Lead] = []
    duplicates = 0

    for lead in leads:
        key = lead.fingerprint

        if key in seen:
            duplicates += 1
            continue

        seen.add(key)
        unique.append(lead)

    return unique, duplicates


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in value.lower().replace(
            "/", " "
        ).replace(
            "-", " "
        ).split()
        if token
    }


def compatibility(
    buyer: Lead,
    seller: Lead,
) -> tuple[float, str]:
    if buyer.kind != "buyer":
        return 0.0, "first lead is not a buyer"

    if seller.kind != "seller":
        return 0.0, "second lead is not a seller"

    if (
        buyer.state != "qualified"
        or seller.state != "qualified"
    ):
        return 0.0, "both leads must be qualified"

    score = 0.0
    reasons: list[str] = []

    buyer_product = _tokens(buyer.product)
    seller_product = _tokens(seller.product)

    if (
        buyer_product
        and seller_product
        and buyer_product & seller_product
    ):
        score += 0.45
        reasons.append("product overlap")
    else:
        return 0.0, "product mismatch"

    buyer_spec = _tokens(buyer.specification)
    seller_spec = _tokens(seller.specification)

    if (
        not buyer_spec
        or not seller_spec
        or buyer_spec & seller_spec
    ):
        score += 0.20
        reasons.append("specification compatible")

    buyer_location = _tokens(buyer.location)
    seller_location = _tokens(seller.location)

    if buyer_location & seller_location:
        score += 0.15
        reasons.append("location overlap")

    quantity_ok = (
        buyer.quantity is None
        or seller.quantity is None
        or seller.quantity >= buyer.quantity
    )

    if quantity_ok:
        score += 0.10
        reasons.append("quantity compatible")

    price_ok = (
        buyer.price is None
        or seller.price is None
        or (
            buyer.currency == seller.currency
            and seller.price <= buyer.price
        )
    )

    if price_ok:
        score += 0.10
        reasons.append("price compatible")

    return min(score, 1.0), ", ".join(reasons)


def make_match(
    buyer: Lead,
    seller: Lead,
    *,
    minimum_score: float = 0.60,
) -> Match | None:
    score, rationale = compatibility(
        buyer,
        seller,
    )

    if score < minimum_score:
        return None

    spread_per_unit: Decimal | None = None
    spread_total: Decimal | None = None

    if (
        buyer.price is not None
        and seller.price is not None
        and buyer.currency == seller.currency
    ):
        spread_per_unit = (
            buyer.price - seller.price
        )

        if (
            buyer.quantity is not None
            and spread_per_unit is not None
        ):
            spread_total = (
                spread_per_unit
                * Decimal(str(buyer.quantity))
            )

    return Match(
        buyer=buyer,
        seller=seller,
        compatibility_score=score,
        gross_spread_per_unit=spread_per_unit,
        gross_spread_total=spread_total,
        state="awaiting_user_approval",
        rationale=rationale,
    )


class MarketAgent:
    role: LeadKind

    def __init__(
        self,
        *,
        agent_id: str,
        worker_instance: str,
        store: Any,
        discovery: DiscoveryAdapter | None = None,
        minimum_confidence: float = 0.60,
    ) -> None:
        self.agent_id = agent_id
        self.worker_instance = worker_instance
        self.store = store
        self.discovery = (
            discovery
            if discovery is not None
            else DisabledDiscoveryAdapter()
        )
        self.minimum_confidence = minimum_confidence
        self.counters = AgentCounters()

    def heartbeat(self) -> None:
        self.store.heartbeat(
            self.agent_id
        )

    def discover(
        self,
        *,
        query: str,
        limit: int = 20,
    ) -> list[Lead]:
        candidates = list(
            self.discovery.discover(
                role=self.role,
                query=query,
                limit=limit,
            )
        )

        self.counters.sources_processed += len(
            candidates
        )
        self.counters.discovered += len(
            candidates
        )

        normalized = [
            normalize_candidate(
                self.role,
                candidate,
            )
            for candidate in candidates
        ]

        unique, duplicate_count = deduplicate(
            normalized
        )

        self.counters.duplicates += duplicate_count

        qualified: list[Lead] = []

        for lead in unique:
            result = qualify_lead(
                lead,
                minimum_confidence=(
                    self.minimum_confidence
                ),
            )

            if result.state == "qualified":
                self.counters.qualified += 1
            else:
                self.counters.rejected += 1

            qualified.append(result)

        return qualified

    def status(
        self,
        *,
        current_task: str = "",
        expected_units: int | None = None,
    ) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "worker_instance": self.worker_instance,
            "current_task": current_task,
            "progress_percent": (
                self.counters.progress_percent(
                    expected_units=expected_units,
                )
            ),
            **asdict(self.counters),
        }


class BuyerAgent(MarketAgent):
    role: LeadKind = "buyer"


class SellerAgent(MarketAgent):
    role: LeadKind = "seller"


class BrokerAgent:
    """Pure internal matcher.

    It has no external outreach capability.
    """

    def __init__(
        self,
        *,
        agent_id: str,
        worker_instance: str,
        store: Any,
    ) -> None:
        self.agent_id = agent_id
        self.worker_instance = worker_instance
        self.store = store
        self.counters = AgentCounters()

    def heartbeat(self) -> None:
        self.store.heartbeat(
            self.agent_id
        )

    def match(
        self,
        buyers: Iterable[Lead],
        sellers: Iterable[Lead],
    ) -> list[Match]:
        matches: list[Match] = []

        buyer_list = list(buyers)
        seller_list = list(sellers)

        for buyer in buyer_list:
            for seller in seller_list:
                result = make_match(
                    buyer,
                    seller,
                )

                if result is not None:
                    matches.append(result)

        matches.sort(
            key=lambda item: (
                item.compatibility_score,
                (
                    item.gross_spread_total
                    if item.gross_spread_total
                    is not None
                    else Decimal("-Infinity")
                ),
            ),
            reverse=True,
        )

        self.counters.matches_found += len(
            matches
        )
        self.counters.awaiting_approval += len(
            matches
        )

        return matches


def serialize_lead(
    lead: Lead,
) -> dict[str, Any]:
    result = asdict(lead)

    if lead.price is not None:
        result["price"] = str(lead.price)

    result["discovered_at"] = (
        lead.discovered_at.isoformat()
    )
    result["fingerprint"] = (
        lead.fingerprint
    )

    return result


def serialize_match(
    match: Match,
) -> dict[str, Any]:
    return {
        "buyer": serialize_lead(match.buyer),
        "seller": serialize_lead(match.seller),
        "compatibility_score": (
            match.compatibility_score
        ),
        "gross_spread_per_unit": (
            str(match.gross_spread_per_unit)
            if match.gross_spread_per_unit
            is not None
            else None
        ),
        "gross_spread_total": (
            str(match.gross_spread_total)
            if match.gross_spread_total
            is not None
            else None
        ),
        "state": match.state,
        "rationale": match.rationale,
    }


APPROVAL_GATE_ENABLED = True
OUTREACH_ENABLED = False


__all__ = [
    "APPROVAL_GATE_ENABLED",
    "AgentCounters",
    "BrokerAgent",
    "BuyerAgent",
    "DisabledDiscoveryAdapter",
    "DiscoveryAdapter",
    "DiscoveryUnavailable",
    "Lead",
    "Match",
    "OUTREACH_ENABLED",
    "SellerAgent",
    "compatibility",
    "deduplicate",
    "make_match",
    "normalize_candidate",
    "qualify_lead",
    "serialize_lead",
    "serialize_match",
]
