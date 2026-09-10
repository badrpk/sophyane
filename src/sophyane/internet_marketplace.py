"""Internet discovery and approved Gmail outreach for marketplace agents.

Architecture
------------

BuyerAgent
    -> NifduInternetDiscovery
    -> public web research
    -> structured buyer candidates
    -> qualification / deduplication

SellerAgent
    -> NifduInternetDiscovery
    -> public web research
    -> structured seller candidates
    -> qualification / deduplication

BrokerAgent
    -> matches qualified leads
    -> awaiting_user_approval
    -> ApprovedGmailOutreach
    -> Gmail SMTP only after explicit per-message approval

Security
--------

The Gmail app password is never stored by this module.

It is requested with getpass.getpass() only when sending an explicitly
approved message.

No automatic negotiation, payment, purchase, sale, contract acceptance,
or commitment is permitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from getpass import getpass
from typing import Any, Iterable, Mapping
import json
import re
import smtplib
import ssl
import uuid

from sophyane.marketplace_agents import (
    DiscoveryAdapter,
    LeadKind,
)
from sophyane.providers.nifdu_browser import (
    NifduBrowserProvider,
)


DEFAULT_GMAIL_ACCOUNT = "badrpk@gmail.com"


class InternetDiscoveryError(RuntimeError):
    pass


class OutreachApprovalError(RuntimeError):
    pass


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    """Extract one JSON array from a provider response."""

    raw = text.strip()

    if raw.startswith("```"):
        raw = re.sub(
            r"^```(?:json)?\s*",
            "",
            raw,
            flags=re.IGNORECASE,
        )
        raw = re.sub(
            r"\s*```$",
            "",
            raw,
        )

    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]")

        if start < 0 or end <= start:
            raise InternetDiscoveryError(
                "browser provider did not return a JSON array"
            )

        try:
            value = json.loads(
                raw[start : end + 1]
            )
        except json.JSONDecodeError as exc:
            raise InternetDiscoveryError(
                "browser provider returned invalid JSON"
            ) from exc

    if not isinstance(value, list):
        raise InternetDiscoveryError(
            "browser discovery response is not a list"
        )

    rows: list[dict[str, Any]] = []

    for item in value:
        if isinstance(item, dict):
            rows.append(item)

    return rows


def _buyer_prompt(
    query: str,
    limit: int,
) -> str:
    return f"""
Use live public internet research.

Find genuine CURRENT buyer demand related to:

{query}

Return at most {limit} leads.

Search public sources such as:
- company procurement pages
- tender/procurement notices
- marketplace wanted listings
- public business directories
- trading platforms
- company websites
- public social/business listings where permitted

A buyer lead means somebody publicly indicating demand to BUY,
PROCURE, SOURCE or REQUEST the item/service.

DO NOT invent buyers.
DO NOT infer a company is buying merely because it exists.
Every lead must have a real public source URL supporting the demand.

Return ONLY a JSON array.

Each object must contain:

{{
  "product": "...",
  "specification": "...",
  "quantity": number_or_null,
  "target_price": number_or_null,
  "currency": "...",
  "location": "...",
  "delivery_terms": "...",
  "contact": "...",
  "source_url": "https://...",
  "source_evidence": "short factual evidence from the public source",
  "confidence": 0.0_to_1.0
}}

If no genuine buyer demand can be verified, return [].
""".strip()


def _seller_prompt(
    query: str,
    limit: int,
) -> str:
    return f"""
Use live public internet research.

Find genuine CURRENT sellers, manufacturers, suppliers or stockists
related to:

{query}

Return at most {limit} leads.

Search public sources such as:
- manufacturer websites
- supplier catalogs
- trading platforms
- public marketplace listings
- distributor websites
- company websites
- public business directories

A seller lead must provide evidence that the party actually OFFERS,
SELLS, MANUFACTURES or SUPPLIES the requested item/service.

DO NOT invent sellers.
Every lead must have a real public source URL supporting the offer.

Return ONLY a JSON array.

Each object must contain:

{{
  "product": "...",
  "specification": "...",
  "quantity": number_or_null,
  "asking_price": number_or_null,
  "currency": "...",
  "location": "...",
  "delivery_terms": "...",
  "contact": "...",
  "source_url": "https://...",
  "source_evidence": "short factual evidence from the public source",
  "confidence": 0.0_to_1.0
}}

If no genuine seller can be verified, return [].
""".strip()


class NifduInternetDiscovery(DiscoveryAdapter):
    """Live public-web discovery through Sophyane's NIFDU browser."""

    def __init__(
        self,
        *,
        provider: NifduBrowserProvider | None = None,
        timeout: int = 240,
    ) -> None:
        self.provider = (
            provider
            if provider is not None
            else NifduBrowserProvider(
                model="chatgpt-browser",
                timeout=timeout,
            )
        )

    def discover(
        self,
        *,
        role: LeadKind,
        query: str,
        limit: int,
    ) -> Iterable[Mapping[str, Any]]:
        if role == "buyer":
            prompt = _buyer_prompt(
                query,
                limit,
            )
        elif role == "seller":
            prompt = _seller_prompt(
                query,
                limit,
            )
        else:
            raise ValueError(
                f"unsupported marketplace role: {role}"
            )

        response = self.provider.generate(
            prompt,
            system_prompt=(
                "Act as a careful marketplace research agent. "
                "Use current public web evidence. "
                "Never fabricate leads or URLs. "
                "Return machine-readable JSON only."
            ),
        )

        rows = _extract_json_array(
            response
        )

        accepted: list[dict[str, Any]] = []

        for row in rows:
            source_url = str(
                row.get(
                    "source_url",
                    "",
                )
            ).strip()

            evidence = str(
                row.get(
                    "source_evidence",
                    "",
                )
            ).strip()

            # Fail closed on evidence-free provider output.
            if not source_url.startswith(
                ("http://", "https://")
            ):
                continue

            if not evidence:
                continue

            accepted.append(row)

        return accepted[:limit]


@dataclass(frozen=True)
class PreparedOutreach:
    approval_id: str
    match_id: str
    recipient: str
    subject: str
    body: str
    approved: bool = False


class ApprovalRegistry:
    """In-process per-message approval registry.

    Durable Postgres approval records can replace this registry when the
    supervisor wiring phase is complete.
    """

    def __init__(self) -> None:
        self._messages: dict[
            str,
            PreparedOutreach,
        ] = {}

    def prepare(
        self,
        *,
        match_id: str,
        recipient: str,
        subject: str,
        body: str,
    ) -> PreparedOutreach:
        approval_id = (
            "approval-"
            + uuid.uuid4().hex[:16]
        )

        item = PreparedOutreach(
            approval_id=approval_id,
            match_id=match_id,
            recipient=recipient,
            subject=subject,
            body=body,
            approved=False,
        )

        self._messages[
            approval_id
        ] = item

        return item

    def approve(
        self,
        approval_id: str,
    ) -> PreparedOutreach:
        current = self._messages.get(
            approval_id
        )

        if current is None:
            raise OutreachApprovalError(
                "unknown approval ID"
            )

        approved = PreparedOutreach(
            approval_id=current.approval_id,
            match_id=current.match_id,
            recipient=current.recipient,
            subject=current.subject,
            body=current.body,
            approved=True,
        )

        self._messages[
            approval_id
        ] = approved

        return approved

    def get(
        self,
        approval_id: str,
    ) -> PreparedOutreach:
        try:
            return self._messages[
                approval_id
            ]
        except KeyError as exc:
            raise OutreachApprovalError(
                "unknown approval ID"
            ) from exc


class ApprovedGmailOutreach:
    """Send only explicitly approved messages through Gmail SMTP."""

    def __init__(
        self,
        *,
        account: str = DEFAULT_GMAIL_ACCOUNT,
        approvals: ApprovalRegistry | None = None,
    ) -> None:
        self.account = account
        self.approvals = (
            approvals
            if approvals is not None
            else ApprovalRegistry()
        )

    def prepare(
        self,
        *,
        match_id: str,
        recipient: str,
        subject: str,
        body: str,
    ) -> PreparedOutreach:
        return self.approvals.prepare(
            match_id=match_id,
            recipient=recipient,
            subject=subject,
            body=body,
        )

    def approve(
        self,
        approval_id: str,
    ) -> PreparedOutreach:
        return self.approvals.approve(
            approval_id
        )

    def send_approved(
        self,
        approval_id: str,
        *,
        app_password: str | None = None,
    ) -> str:
        item = self.approvals.get(
            approval_id
        )

        if not item.approved:
            raise OutreachApprovalError(
                "message has not been explicitly approved"
            )

        recipient = (
            item.recipient.strip()
        )

        if (
            not recipient
            or "@" not in recipient
        ):
            raise OutreachApprovalError(
                "approved message has no valid email recipient"
            )

        password = (
            app_password
            if app_password is not None
            else getpass(
                f"Gmail app password for {self.account}: "
            )
        )

        if not password:
            raise OutreachApprovalError(
                "Gmail app password was not supplied"
            )

        message = EmailMessage()

        message["From"] = self.account
        message["To"] = recipient
        message["Subject"] = (
            item.subject
        )

        message.set_content(
            item.body
        )

        context = ssl.create_default_context()

        # SMTP object exists only for the send operation.
        with smtplib.SMTP_SSL(
            "smtp.gmail.com",
            465,
            context=context,
            timeout=30,
        ) as smtp:
            smtp.login(
                self.account,
                password,
            )

            smtp.send_message(
                message
            )

        return item.approval_id


def render_outreach_for_approval(
    item: PreparedOutreach,
) -> str:
    return "\n".join(
        (
            "============================================================",
            "OUTREACH_APPROVAL_REQUIRED",
            f"APPROVAL_ID={item.approval_id}",
            f"MATCH_ID={item.match_id}",
            f"TO={item.recipient}",
            f"SUBJECT={item.subject}",
            "",
            item.body,
            "",
            "No email has been sent.",
            "Approve this exact message before send_approved().",
            "============================================================",
        )
    )


APPROVAL_GATE_ENABLED = True
AUTOMATIC_OUTREACH_ENABLED = False


__all__ = [
    "APPROVAL_GATE_ENABLED",
    "AUTOMATIC_OUTREACH_ENABLED",
    "ApprovalRegistry",
    "ApprovedGmailOutreach",
    "DEFAULT_GMAIL_ACCOUNT",
    "InternetDiscoveryError",
    "NifduInternetDiscovery",
    "OutreachApprovalError",
    "PreparedOutreach",
    "render_outreach_for_approval",
]
