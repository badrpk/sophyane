"""Highest-priority semantic domain classifier for Sophyane.

This layer decides the knowledge boundary before execution. In particular,
personal questions are never sent to public acquisition merely because they
contain broadly searchable words such as "company", "name", or "USA".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class SemanticDomain(str, Enum):
    POLICY_INSTRUCTION = "policy_instruction"
    PRIVATE_CONNECTOR = "private_connector"
    PERSONAL_KNOWLEDGE = "personal_knowledge"
    WORKSPACE = "workspace"
    ARTIFACT_CREATION = "artifact_creation"
    PUBLIC_KNOWLEDGE = "public_knowledge"
    GENERAL = "general"


@dataclass(frozen=True)
class SemanticDecision:
    domain: SemanticDomain
    confidence: float
    reason: str
    personal: bool = False
    public_fallback_allowed: bool = True


def _normalise(message: str) -> str:
    return " ".join(
        str(message or "")
        .casefold()
        .split()
    )


_POLICY_PATTERNS = (
    re.compile(
        r"\bwhen\s+i\s+ask\b.*"
        r"\bpersonal\b.*"
        r"\b(?:search|check|use|look)\b.*"
        r"\b(?:email|mail|inbox)\b",
        re.I,
    ),
    re.compile(
        r"\bfor\s+my\s+personal\s+"
        r"(?:facts?|information)\b.*"
        r"\b(?:email|mail|inbox)\b",
        re.I,
    ),
    re.compile(
        r"\buse\s+my\s+(?:email|mail|inbox)\b.*"
        r"\bpersonal\b",
        re.I,
    ),
    re.compile(
        r"\bmy\s+(?:email|mail|inbox)\s+has\b.*"
        r"\b(?:my|personal)\b",
        re.I,
    ),
)

_PRIVATE_SOURCE_RE = re.compile(
    r"\b(?:"
    r"email|e-mail|mail|inbox|"
    r"whatsapp|whats\s*app|"
    r"sms|text\s+message|"
    r"snapchat|snap\s*chat|"
    r"wechat|we\s*chat"
    r")\b",
    re.I,
)

_PERSONAL_REFERENCE_RE = re.compile(
    r"\b(?:"
    r"my|mine|"
    r"i\s+own|i\s+owned|"
    r"i\s+have|i\s+had|"
    r"i\s+registered|"
    r"did\s+i\s+register|"
    r"have\s+i\s+registered|"
    r"i\s+formed|"
    r"did\s+i\s+form|"
    r"have\s+i\s+formed|"
    r"i\s+incorporated|"
    r"did\s+i\s+incorporate|"
    r"have\s+i\s+incorporated|"
    r"i\s+booked|"
    r"i\s+applied|"
    r"i\s+bought|"
    r"i\s+paid"
    r")\b",
    re.I,
)

_PERSONAL_FACT_TOPICS = (
    "company",
    "business",
    "llc",
    "corporation",
    "ein",
    "tax id",
    "registration",
    "registered agent",
    "visa",
    "flight",
    "booking",
    "reservation",
    "order",
    "invoice",
    "subscription",
    "membership",
    "insurance",
    "property",
    "address",
    "phone number",
    "account number",
    "application",
    "appointment",
    "university",
    "school",
    "employer",
    "job application",
)

_WORKSPACE_RE = re.compile(
    r"\b(?:"
    r"this\s+project|my\s+project|"
    r"repository|repo|workspace|"
    r"file|folder|directory|"
    r"codebase|source\s+code"
    r")\b",
    re.I,
)

_ARTIFACT_RE = re.compile(
    r"\b(?:"
    r"make|create|build|generate|design|write"
    r")\b.*"
    r"\b(?:"
    r"website|web\s*site|html|dashboard|"
    r"script|program|app|application|"
    r"file|document|report"
    r")\b",
    re.I,
)


def classify_semantic_domain(
    message: str,
) -> SemanticDecision:
    text = _normalise(message)

    if any(
        pattern.search(text)
        for pattern in _POLICY_PATTERNS
    ):
        return SemanticDecision(
            domain=SemanticDomain.POLICY_INSTRUCTION,
            confidence=0.99,
            reason=(
                "The user is teaching a future source-selection rule."
            ),
            personal=True,
            public_fallback_allowed=False,
        )

    if _PRIVATE_SOURCE_RE.search(text):
        return SemanticDecision(
            domain=SemanticDomain.PRIVATE_CONNECTOR,
            confidence=0.97,
            reason=(
                "The request explicitly names a private communication source."
            ),
            personal=True,
            public_fallback_allowed=False,
        )

    personal_reference = bool(
        _PERSONAL_REFERENCE_RE.search(text)
    )

    personal_topic = any(
        topic in text
        for topic in _PERSONAL_FACT_TOPICS
    )

    question_like = (
        text.endswith("?")
        or text.startswith(
            (
                "what ",
                "which ",
                "where ",
                "when ",
                "who ",
                "how ",
                "do i ",
                "did i ",
                "have i ",
                "name of my ",
            )
        )
    )

    if (
        personal_reference
        and personal_topic
        and question_like
    ):
        return SemanticDecision(
            domain=SemanticDomain.PERSONAL_KNOWLEDGE,
            confidence=0.96,
            reason=(
                "The request asks for a fact about the user's own life, "
                "accounts, property, business, or records."
            ),
            personal=True,
            public_fallback_allowed=False,
        )

    if _ARTIFACT_RE.search(text):
        return SemanticDecision(
            domain=SemanticDomain.ARTIFACT_CREATION,
            confidence=0.91,
            reason=(
                "The user requests creation or modification of an artifact."
            ),
        )

    if _WORKSPACE_RE.search(text):
        return SemanticDecision(
            domain=SemanticDomain.WORKSPACE,
            confidence=0.84,
            reason=(
                "The request concerns the local project or filesystem."
            ),
        )

    if text.startswith(
        (
            "what is ",
            "who is ",
            "where is ",
            "when is ",
            "explain ",
            "tell me about ",
        )
    ):
        return SemanticDecision(
            domain=SemanticDomain.PUBLIC_KNOWLEDGE,
            confidence=0.65,
            reason=(
                "The request appears to seek general knowledge "
                "and contains no personal ownership signal."
            ),
        )

    return SemanticDecision(
        domain=SemanticDomain.GENERAL,
        confidence=0.40,
        reason="No high-confidence semantic domain matched.",
    )


__all__ = [
    "SemanticDecision",
    "SemanticDomain",
    "classify_semantic_domain",
]
