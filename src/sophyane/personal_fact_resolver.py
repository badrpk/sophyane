"""Resolve personal factual questions through learned private source policies."""

from __future__ import annotations

import html
import re
import sys
from typing import Any

from sophyane.personal_semantic_memory import (
    confirmed_fact,
    learn_source_policy,
    save_confirmed_fact,
    source_policy,
)
from sophyane.semantic_intent_router import (
    SemanticDomain,
    classify_semantic_domain,
)


def _normalise(message: str) -> str:
    return " ".join(
        str(message or "")
        .casefold()
        .split()
    )


def _learn_policy_instruction(
    message: str,
) -> str | None:
    decision = classify_semantic_domain(
        message
    )

    if (
        decision.domain
        != SemanticDomain.POLICY_INSTRUCTION
    ):
        return None

    learn_source_policy(
        "personal_facts",
        ["email"],
        instruction=message,
    )

    return "\n".join(
        [
            "Sophyane semantic policy learner",
            (
                "Learned rule: personal factual questions "
                "should search the active private email account first."
            ),
            "Instruction interpreted as policy: True",
            "Email searched for this instruction: False",
            "Public internet fallback: blocked",
            "Raw private content stored: False",
            "Success: True",
        ]
    )


def _fact_key(
    message: str,
) -> str:
    text = _normalise(message)

    company_terms = (
        "usa company",
        "us company",
        "american company",
        "company in usa",
        "company in the usa",
        "company in united states",
    )

    if any(
        term in text
        for term in company_terms
    ):
        return "usa_company_owned"

    if (
        "company" in text
        and any(
            country in text
            for country in (
                "usa",
                "u.s.",
                "united states",
                "america",
                "american",
            )
        )
    ):
        return "usa_company_owned"

    return ""


def _semantic_email_query(
    message: str,
    fact_key: str,
) -> str:
    if fact_key == "usa_company_owned":
        return (
            "USA United States company business LLC Inc "
            "incorporation formation certificate registered agent "
            "EIN owner member Delaware Wyoming company name"
        )

    words = re.findall(
        r"[A-Za-z0-9][A-Za-z0-9_-]{2,}",
        _normalise(message),
    )

    stop = {
        "what",
        "which",
        "where",
        "when",
        "name",
        "does",
        "have",
        "mine",
        "that",
        "this",
        "about",
    }

    return " ".join(
        word
        for word in words
        if word not in stop
    )[:300]


def _strip_markup(value: str) -> str:
    text = html.unescape(
        str(value or "")
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    return " ".join(
        text.split()
    )


_LEGAL_SUFFIX = (
    r"(?:"
    r"LLC|L\.L\.C\.|"
    r"Inc\.?|Incorporated|"
    r"Corporation|Corp\.?|"
    r"Ltd\.?|Limited"
    r")"
)

_COMPANY_RE = re.compile(
    r"\b("
    r"[A-Z][A-Za-z0-9&,'’.\- ]{1,90}?"
    + _LEGAL_SUFFIX
    + r")(?=\s|[,;:)\]]|$)",
)

_LEADING_LEGAL_CONTEXT = re.compile(
    r"^(?:"
    r"certificate\s+of\s+"
    r"(?:formation|incorporation|organization)"
    r"|articles\s+of\s+"
    r"(?:formation|incorporation|organization)"
    r"|company\s+name"
    r"|business\s+name"
    r"|entity\s+name"
    r"|registered\s+(?:entity|company|business)"
    r")"
    r"\s*(?:for|of|issued\s+to|:|-)?\s*",
    re.I,
)


def _clean_company_name(
    value: str,
) -> str:
    candidate = " ".join(
        str(value or "").split()
    ).strip(" -:;,")

    previous = ""

    while (
        candidate
        and candidate != previous
    ):
        previous = candidate
        candidate = _LEADING_LEGAL_CONTEXT.sub(
            "",
            candidate,
            count=1,
        ).strip(" -:;,")

    # Remove a remaining bounded prefix before “for”.
    candidate = re.sub(
        r"^.{1,80}?\bfor\s+"
        r"(?=[A-Z][A-Za-z0-9&,'’.\- ]+"
        + _LEGAL_SUFFIX
        + r"(?=\s|[,;:)\]]|$))",
        "",
        candidate,
        count=1,
        flags=re.I,
    ).strip(" -:;,")

    return candidate


def extract_company_candidates(
    material: str,
) -> list[str]:
    cleaned = _strip_markup(
        material
    )

    candidates: list[str] = []
    seen: set[str] = set()

    for match in _COMPANY_RE.finditer(
        cleaned
    ):
        candidate = _clean_company_name(
            match.group(1)
        )

        if not candidate:
            continue

        key = candidate.casefold()

        if key in seen:
            continue

        seen.add(key)
        candidates.append(candidate)

    return candidates[:12]


def _choose_candidate(
    candidates: list[str],
) -> str:
    if not candidates:
        return ""

    if len(candidates) == 1:
        if not sys.stdin.isatty():
            return candidates[0]

        try:
            answer = input(
                f'I found “{candidates[0]}”. '
                "Is this the correct company? [Y/n]: "
            ).strip().casefold()
        except (
            EOFError,
            KeyboardInterrupt,
        ):
            print()
            return ""

        if answer in {
            "",
            "y",
            "yes",
        }:
            return candidates[0]

        return ""

    if not sys.stdin.isatty():
        return ""

    print()
    print(
        "I found several possible company names "
        "in your private email evidence:"
    )
    print()

    for number, candidate in enumerate(
        candidates,
        start=1,
    ):
        print(
            f"  {number}. {candidate}"
        )

    print("  0. None of these")
    print()

    try:
        answer = input(
            f"Select the correct company [0-{len(candidates)}]: "
        ).strip()
    except (
        EOFError,
        KeyboardInterrupt,
    ):
        print()
        return ""

    try:
        selection = int(answer)
    except ValueError:
        return ""

    if 1 <= selection <= len(candidates):
        return candidates[
            selection - 1
        ]

    return ""


def _search_active_email(
    query: str,
) -> dict[str, Any]:
    from sophyane.connectors.email_imap.handler import (
        execute,
    )
    from sophyane.email_account_registry import (
        active_profile,
    )

    return execute(
        op="search",
        args={
            "query": query,
            "limit": 80,
        },
        profile=active_profile(),
        manifest={},
    )


def _resolve_personal_question(
    message: str,
) -> str | None:
    decision = classify_semantic_domain(
        message
    )

    if (
        decision.domain
        != SemanticDomain.PERSONAL_KNOWLEDGE
    ):
        return None

    fact_key = _fact_key(
        message
    )

    if fact_key:
        known = confirmed_fact(
            fact_key
        )

        if known:
            return "\n".join(
                [
                    "Sophyane personal semantic memory",
                    f"Question: {message}",
                    f"Answer: {known['value']}",
                    "Source: confirmed personal fact",
                    (
                        "Provenance: "
                        + known["provenance"]
                    ),
                    (
                        "Evidence source: "
                        + known["evidence_source"]
                    ),
                    "Public internet fallback: blocked",
                    "Success: True",
                ]
            )

    sources = source_policy(
        "personal_facts"
    )

    if not sources:
        return "\n".join(
            [
                "Sophyane personal semantic router",
                (
                    "This is a personal factual question, "
                    "so public internet acquisition was blocked."
                ),
                (
                    "I have not learned which private source "
                    "you want searched first."
                ),
                (
                    "Teach me by saying: "
                    "when I ask personal information, search my email."
                ),
                "Success: False",
            ]
        )

    if "email" not in sources:
        return "\n".join(
            [
                "Sophyane personal semantic router",
                (
                    "The learned source policy does not currently "
                    "permit email for this question."
                ),
                "Public internet fallback: blocked",
                "Success: False",
            ]
        )

    query = _semantic_email_query(
        message,
        fact_key,
    )

    try:
        result = _search_active_email(
            query
        )
    except Exception as error:
        return "\n".join(
            [
                "Sophyane personal semantic resolver",
                "Private source attempted: active email account",
                (
                    "Connector failure: "
                    f"{type(error).__name__}: {error}"
                ),
                "Public internet fallback: blocked",
                "Success: False",
            ]
        )

    if not result.get("ok"):
        return "\n".join(
            [
                "Sophyane personal semantic resolver",
                "Private source attempted: active email account",
                (
                    "Connector result: "
                    + str(
                        result.get("message")
                        or result.get("error")
                        or "search failed"
                    )
                ),
                "Public internet fallback: blocked",
                "Success: False",
            ]
        )

    evidence = str(
        result.get("formatted")
        or result.get("message")
        or ""
    )

    candidates = (
        extract_company_candidates(
            evidence
        )
        if fact_key == "usa_company_owned"
        else []
    )

    selected = _choose_candidate(
        candidates
    )

    if selected and fact_key:
        save_confirmed_fact(
            fact_key,
            selected,
            provenance=(
                "Confirmed by the user after semantic "
                "search of private email evidence."
            ),
            evidence_source="active private email",
        )

        return "\n".join(
            [
                "Sophyane personal semantic resolver",
                f"Question: {message}",
                "Semantic domain: personal_knowledge",
                "Private source searched: active email",
                f"Semantic concepts: {query}",
                f"Answer: {selected}",
                (
                    "Learning: confirmed fact stored with provenance"
                ),
                "Raw email promoted to memory: False",
                "Public internet fallback: blocked",
                "Success: True",
            ]
        )

    lines = [
        "Sophyane personal semantic resolver",
        f"Question: {message}",
        "Semantic domain: personal_knowledge",
        "Private source searched: active email",
        f"Semantic concepts: {query}",
        (
            "Matches: "
            + str(
                result.get("matches")
                or 0
            )
        ),
    ]

    if candidates:
        lines.extend(
            [
                "",
                "Possible answers:",
                *[
                    f"  {number}. {candidate}"
                    for number, candidate
                    in enumerate(
                        candidates,
                        start=1,
                    )
                ],
            ]
        )
    else:
        lines.append(
            (
                "No exact answer could be established "
                "safely from the returned evidence."
            )
        )

    if evidence:
        lines.extend(
            [
                "",
                "Relevant private email evidence:",
                evidence[:5000],
            ]
        )

    lines.extend(
        [
            "",
            (
                "You can confirm the final fact by saying: "
                "My USA company is <company name>."
            ),
            "Raw email promoted to memory: False",
            "Public internet fallback: blocked",
            "Success: False",
        ]
    )

    return "\n".join(lines)


_DIRECT_FACT_RE = re.compile(
    r"\bmy\s+(?:usa|us|american)\s+"
    r"company\s+(?:is|name\s+is)\s+"
    r"(.+?)(?:[.!?]|$)",
    re.I,
)


def _learn_direct_fact(
    message: str,
) -> str | None:
    match = _DIRECT_FACT_RE.search(
        str(message or "")
    )

    if not match:
        return None

    value = " ".join(
        match.group(1).split()
    ).strip(" -:;,")

    if not value:
        return None

    save_confirmed_fact(
        "usa_company_owned",
        value,
        provenance=(
            "Direct statement supplied by the user."
        ),
        evidence_source="user statement",
    )

    return "\n".join(
        [
            "Sophyane personal semantic learner",
            "Learned confirmed fact: usa_company_owned",
            f"Value: {value}",
            "Source: direct user statement",
            "Raw private content stored: False",
            "Success: True",
        ]
    )


def try_personal_semantic_reply(
    message: str,
) -> str | None:
    """Top-level personal semantic preflight."""
    return (
        _learn_policy_instruction(message)
        or _learn_direct_fact(message)
        or _resolve_personal_question(message)
    )


__all__ = [
    "extract_company_candidates",
    "try_personal_semantic_reply",
]
