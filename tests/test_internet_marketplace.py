import pytest

from sophyane.internet_marketplace import (
    APPROVAL_GATE_ENABLED,
    AUTOMATIC_OUTREACH_ENABLED,
    ApprovalRegistry,
    ApprovedGmailOutreach,
    NifduInternetDiscovery,
    OutreachApprovalError,
)


class Provider:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def generate(
        self,
        prompt,
        system_prompt="",
    ):
        self.prompts.append(
            (prompt, system_prompt)
        )
        return self.response


def test_authority_boundary():
    assert APPROVAL_GATE_ENABLED is True
    assert (
        AUTOMATIC_OUTREACH_ENABLED
        is False
    )


def test_live_buyer_discovery_parsing():
    provider = Provider(
        """
        [
          {
            "product": "steel scrap",
            "specification": "HMS",
            "quantity": 100,
            "target_price": 150000,
            "currency": "PKR",
            "location": "Islamabad",
            "delivery_terms": "delivered",
            "contact": "buyer@example.com",
            "source_url": "https://example.com/buyer",
            "source_evidence": "Public request to purchase HMS scrap",
            "confidence": 0.91
          }
        ]
        """
    )

    adapter = NifduInternetDiscovery(
        provider=provider
    )

    rows = list(
        adapter.discover(
            role="buyer",
            query="HMS scrap Pakistan",
            limit=10,
        )
    )

    assert len(rows) == 1
    assert (
        rows[0]["contact"]
        == "buyer@example.com"
    )
    assert provider.prompts


def test_live_seller_discovery_parsing():
    provider = Provider(
        """
        [
          {
            "product": "steel scrap",
            "specification": "HMS",
            "quantity": 500,
            "asking_price": 140000,
            "currency": "PKR",
            "location": "Rawalpindi",
            "delivery_terms": "ex yard",
            "contact": "seller@example.com",
            "source_url": "https://example.com/seller",
            "source_evidence": "Supplier lists HMS scrap for sale",
            "confidence": 0.88
          }
        ]
        """
    )

    adapter = NifduInternetDiscovery(
        provider=provider
    )

    rows = list(
        adapter.discover(
            role="seller",
            query="HMS scrap Pakistan",
            limit=10,
        )
    )

    assert len(rows) == 1


def test_evidence_free_rows_are_rejected():
    provider = Provider(
        """
        [
          {
            "product": "steel",
            "source_url": "https://example.com/x",
            "source_evidence": "",
            "confidence": 0.9
          }
        ]
        """
    )

    adapter = NifduInternetDiscovery(
        provider=provider
    )

    assert list(
        adapter.discover(
            role="buyer",
            query="steel",
            limit=10,
        )
    ) == []


def test_outreach_cannot_send_unapproved(
    monkeypatch,
):
    outreach = ApprovedGmailOutreach()

    item = outreach.prepare(
        match_id="match-1",
        recipient="buyer@example.com",
        subject="Supply opportunity",
        body="Hello",
    )

    with pytest.raises(
        OutreachApprovalError
    ):
        outreach.send_approved(
            item.approval_id,
            app_password="not-used",
        )


def test_approval_is_specific_to_message():
    registry = ApprovalRegistry()

    first = registry.prepare(
        match_id="m1",
        recipient="a@example.com",
        subject="A",
        body="A body",
    )

    second = registry.prepare(
        match_id="m2",
        recipient="b@example.com",
        subject="B",
        body="B body",
    )

    approved = registry.approve(
        first.approval_id
    )

    assert approved.approved is True

    assert (
        registry.get(
            second.approval_id
        ).approved
        is False
    )


def test_gmail_password_not_stored():
    outreach = ApprovedGmailOutreach()

    assert not hasattr(
        outreach,
        "password",
    )
    assert not hasattr(
        outreach,
        "app_password",
    )
