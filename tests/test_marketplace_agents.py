from decimal import Decimal

import pytest

from sophyane.marketplace_agents import (
    APPROVAL_GATE_ENABLED,
    OUTREACH_ENABLED,
    BrokerAgent,
    BuyerAgent,
    DisabledDiscoveryAdapter,
    DiscoveryUnavailable,
    SellerAgent,
    deduplicate,
    make_match,
    normalize_candidate,
    qualify_lead,
)


class Store:
    def __init__(self):
        self.heartbeats = []

    def heartbeat(self, agent_id):
        self.heartbeats.append(agent_id)


class Discovery:
    def __init__(self, rows):
        self.rows = rows

    def discover(self, *, role, query, limit):
        return self.rows[:limit]


def buyer(**extra):
    row = {
        "product": "steel scrap",
        "specification": "HMS 1 2",
        "quantity": 100,
        "target_price": 155000,
        "currency": "PKR",
        "location": "Islamabad Pakistan",
        "delivery_terms": "delivered",
        "contact": "buyer-1",
        "source_url": "https://example.invalid/buyer/1",
        "confidence": 0.90,
    }
    row.update(extra)
    return row


def seller(**extra):
    row = {
        "product": "steel scrap",
        "specification": "HMS 1 2",
        "quantity": 150,
        "asking_price": 145000,
        "currency": "PKR",
        "location": "Islamabad Pakistan",
        "delivery_terms": "delivered",
        "contact": "seller-1",
        "source_url": "https://example.invalid/seller/1",
        "confidence": 0.85,
    }
    row.update(extra)
    return row


def test_authority_gate():
    assert APPROVAL_GATE_ENABLED is True
    assert OUTREACH_ENABLED is False


def test_buyer_normalization():
    lead = normalize_candidate(
        "buyer",
        buyer(),
    )
    assert lead.kind == "buyer"
    assert lead.price == Decimal("155000")


def test_seller_normalization():
    lead = normalize_candidate(
        "seller",
        seller(),
    )
    assert lead.kind == "seller"
    assert lead.price == Decimal("145000")


def test_qualification():
    lead = qualify_lead(
        normalize_candidate(
            "buyer",
            buyer(),
        )
    )
    assert lead.state == "qualified"


def test_low_confidence_rejected():
    lead = qualify_lead(
        normalize_candidate(
            "buyer",
            buyer(confidence=0.2),
        )
    )
    assert lead.state == "rejected"


def test_deduplication():
    first = normalize_candidate(
        "buyer",
        buyer(),
    )
    second = normalize_candidate(
        "buyer",
        buyer(),
    )

    unique, duplicates = deduplicate(
        [first, second]
    )

    assert len(unique) == 1
    assert duplicates == 1


def test_match_stops_at_approval():
    b = qualify_lead(
        normalize_candidate(
            "buyer",
            buyer(),
        )
    )
    s = qualify_lead(
        normalize_candidate(
            "seller",
            seller(),
        )
    )

    match = make_match(b, s)

    assert match is not None
    assert match.state == (
        "awaiting_user_approval"
    )
    assert (
        match.gross_spread_per_unit
        == Decimal("10000")
    )
    assert (
        match.gross_spread_total
        == Decimal("1000000")
    )


def test_no_match_for_product_mismatch():
    b = qualify_lead(
        normalize_candidate(
            "buyer",
            buyer(),
        )
    )
    s = qualify_lead(
        normalize_candidate(
            "seller",
            seller(product="wheat"),
        )
    )

    assert make_match(b, s) is None


def test_buyer_agent_real_progress_counters():
    agent = BuyerAgent(
        agent_id="buyer-01",
        worker_instance="worker-b1",
        store=Store(),
        discovery=Discovery(
            [
                buyer(),
                buyer(
                    contact="buyer-2",
                    source_url=(
                        "https://example.invalid/"
                        "buyer/2"
                    ),
                ),
            ]
        ),
    )

    leads = agent.discover(
        query="steel scrap",
        limit=10,
    )

    assert len(leads) == 2
    assert agent.counters.discovered == 2
    assert agent.counters.qualified == 2


def test_seller_agent_real_progress_counters():
    agent = SellerAgent(
        agent_id="seller-01",
        worker_instance="worker-s1",
        store=Store(),
        discovery=Discovery(
            [
                seller(),
            ]
        ),
    )

    agent.discover(
        query="steel scrap",
    )

    status = agent.status(
        current_task="supplier discovery",
        expected_units=1,
    )

    assert status["qualified"] == 1
    assert status["progress_percent"] == 100.0


def test_broker_agent():
    store = Store()

    b = qualify_lead(
        normalize_candidate(
            "buyer",
            buyer(),
        )
    )
    s = qualify_lead(
        normalize_candidate(
            "seller",
            seller(),
        )
    )

    broker = BrokerAgent(
        agent_id="broker-01",
        worker_instance="worker-br1",
        store=store,
    )

    matches = broker.match(
        [b],
        [s],
    )

    assert len(matches) == 1
    assert (
        broker.counters.awaiting_approval
        == 1
    )


def test_heartbeat():
    store = Store()

    agent = BuyerAgent(
        agent_id="buyer-01",
        worker_instance="worker-b1",
        store=store,
    )

    agent.heartbeat()

    assert store.heartbeats == [
        "buyer-01"
    ]


def test_discovery_fails_closed():
    agent = BuyerAgent(
        agent_id="buyer-01",
        worker_instance="worker-b1",
        store=Store(),
        discovery=DisabledDiscoveryAdapter(),
    )

    with pytest.raises(
        DiscoveryUnavailable
    ):
        agent.discover(
            query="steel scrap buyers"
        )
