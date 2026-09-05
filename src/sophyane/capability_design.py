"""Provider-independent systematic capability-design prompting.

This layer detects when the user is asking Sophyane to acquire,
match, extend, integrate, or explain a substantial capability.

It does not choose a provider.
It does not create the implementation.
It does not create a graph.

Its only job is to make the first reasoning turn sufficiently
systematic and machine-retainable for later execution and
visualization.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


# SOPHYANE_SYSTEMATIC_CAPABILITY_DESIGN_V6


@dataclass(frozen=True)
class CapabilityDesignIntent:
    requested: bool
    reason: str


_DIRECT_CAPABILITY_PATTERNS = (
    r"\bsophyane\s+should\s+(?:have|support|include|provide|gain)\b",
    r"\bsophyane\s+should\s+be\s+able\s+to\b",
    r"\bi\s+want\s+sophyane\s+to\b",
    r"\bmake\s+sophyane\s+(?:able|capable)\b",
    r"\badd\s+(?:a|an|the)?\s*[\w -]{1,100}\s+capabilit(?:y|ies)\b",
    r"\badd\s+support\s+for\b",
    r"\bgive\s+sophyane\s+(?:the\s+)?ability\s+to\b",
    r"\bsophyane\s+needs?\s+to\s+(?:support|handle|process|understand|import|export|generate)\b",
    r"\bimplement\s+support\s+for\b",
)


_PARITY_PATTERNS = (
    r"\ball\s+(?:the\s+)?features\s+(?:of|as|from)\b",
    r"\bsame\s+(?:features|capabilities)\s+as\b",
    r"\bfeature\s+parity\s+with\b",
    r"\bcapability\s+parity\s+with\b",
    r"\bwork\s+like\b",
    r"\bbehave\s+like\b",
    r"\bequivalent\s+to\b",
)


_NON_DESIGN_PATTERNS = (
    r"\bwhat\s+does\s+.+\s+mean\b",
    r"\bdefine\b",
    r"\bwho\s+is\b",
    r"\bwhat\s+is\b",
)


def detect_capability_design_intent(
    request: str,
) -> CapabilityDesignIntent:
    text = " ".join(
        str(
            request
            or ""
        ).strip().lower().split()
    )

    if not text:
        return CapabilityDesignIntent(
            requested=False,
            reason="empty request",
        )

    if any(
        re.search(
            pattern,
            text,
        )
        for pattern in _NON_DESIGN_PATTERNS
    ):
        return CapabilityDesignIntent(
            requested=False,
            reason="informational question",
        )

    direct = any(
        re.search(
            pattern,
            text,
        )
        for pattern in _DIRECT_CAPABILITY_PATTERNS
    )

    parity = any(
        re.search(
            pattern,
            text,
        )
        for pattern in _PARITY_PATTERNS
    )

    if not (
        direct
        or parity
    ):
        return CapabilityDesignIntent(
            requested=False,
            reason="no capability-design intent",
        )

    return CapabilityDesignIntent(
        requested=True,
        reason=(
            "capability parity request"
            if parity
            else "capability expansion request"
        ),
    )


def systematic_capability_prompt(
    *,
    request: str,
    conversational_context: str,
) -> str:
    """
    Build a provider-independent first-turn architecture prompt.

    The explicit PROCESS_FLOW line is intentionally required because
    Sophyane's existing conversational graph layer can retain and
    visualize an arrow-delimited grounded process without inventing
    topology later.
    """

    original = str(
        request
        or ""
    ).strip()

    context = str(
        conversational_context
        or ""
    ).strip()

    return f"""You are Sophyane's capability architect.

Answer the ORIGINAL USER REQUEST directly and comprehensively.

The user is asking about Sophyane's capabilities or capability parity.
Do not answer with a shallow yes/no statement or a short feature list.

Produce a systematic engineering description of what Sophyane would
need, how the capabilities relate, what data enters and leaves each
stage, and how success would be verified.

Stay grounded in the user's requested capability. Do not claim that
unverified features already exist.

Required response structure:

1. Capability goal
   Explain precisely what the requested capability means.

2. User-facing abilities
   Describe the major things the user should be able to do.

3. Functional capability groups
   Group the requested behavior into coherent subsystems.

4. Input and ingestion
   Explain supported input classes and how they enter the system.

5. Processing architecture
   Explain the major processing stages and their responsibilities.

6. Intelligence and transformation
   Explain reasoning, understanding, transformation, generation,
   retrieval, or other intelligence required by the request.

7. Output capabilities
   Explain the useful outputs or artifacts the system should produce.

8. Storage, memory and reuse
   Explain what state should persist and what should remain ephemeral.

9. Safety, permissions and provenance
   Explain boundaries, validation and evidence requirements.

10. Verification
    Explain deterministic checks proving the capability actually works.

11. Integration with existing Sophyane capabilities
    Prefer reuse of existing runtime, graph, memory, provider,
    filesystem, browser, media and execution facilities where relevant.
    Do not create duplicate engines merely because the requested
    capability is new.

12. Incremental implementation path
    Break implementation into bounded, independently verifiable stages.

At the end, include exactly one concise machine-retainable line:

PROCESS_FLOW: step one -> step two -> step three -> ... -> verification

Rules for PROCESS_FLOW:
- Include only stages supported by your preceding explanation.
- Use meaningful generic stage names.
- Preserve actual dependency order.
- Do not insert speculative stages merely to make the flow longer.
- Use ` -> ` between stages.
- End in a verification or validated-output stage.
- Do not output a graph or Mermaid unless the user explicitly asks
  for a graph in this same turn.

ORIGINAL USER REQUEST:
{original}

CURRENT CONVERSATIONAL CONTEXT:
{context}
"""


def prepare_capability_design_request(
    *,
    request: str,
    conversational_context: str,
) -> str | None:
    intent = detect_capability_design_intent(
        request
    )

    if not intent.requested:
        return None

    return systematic_capability_prompt(
        request=request,
        conversational_context=(
            conversational_context
        ),
    )


__all__ = [
    "CapabilityDesignIntent",
    "detect_capability_design_intent",
    "prepare_capability_design_request",
    "systematic_capability_prompt",
]
