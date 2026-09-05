"""Concurrent read-only Mode-3 preparation during Mode-4 latency.

This module exploits otherwise idle local-LLM time while preserving authority.

The speculative worker:
- cannot select the source change;
- cannot materialize candidate files;
- cannot execute mutation commands;
- cannot stage/commit/push;
- produces advisory text only;
- is cancelled cooperatively when Mode 4 returns;
- must drain before the authoritative Mode-3 mutation call begins.

Python threads cannot safely kill an arbitrary in-flight provider call.
Therefore cancellation stops new speculative loops and the controller performs
a drain gate before reusing the single-flight local provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import queue
import re
import threading
import time
from typing import Any


_PATH = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"((?:src|tests|test|docs|scripts|improvements)"
    r"/[A-Za-z0-9_./-]+)"
)


@dataclass(frozen=True)
class SpeculativeEvidence:
    loop: int
    elapsed_sec: float
    text: str



# SOPHYANE_SPECULATIVE_PROVIDER_ISOLATION_V3
#
# Never modify the authoritative Mode-3 provider object or its singleton
# local_gguf child in place. Speculation receives a shallow structural clone
# with its own bounded inference envelope.
def bounded_speculation_provider(
    provider,
    *,
    timeout_sec: int = 3,
    max_tokens: int = 256,
):
    """Return an isolated provider clone for bounded read-only speculation.

    The authoritative Mode-3 provider and its local_gguf child are never
    modified.  Only the private clone receives the short Global-TXQ
    speculation envelope.
    """

    import copy

    # SOPHYANE_SPECULATIVE_PROVIDER_ISOLATION_V4
    requested_timeout = max(
        3,
        min(
            8,
            int(
                timeout_sec
            ),
        ),
    )

    requested_tokens = max(
        64,
        min(
            256,
            int(
                max_tokens
            ),
        ),
    )

    cloned = copy.copy(
        provider
    )

    chain = list(
        getattr(
            provider,
            "_providers",
            (),
        )
        or ()
    )

    if chain:
        cloned_chain = []

        for name, child in chain:
            private_child = copy.copy(
                child
            )

            if str(
                name
            ).strip().lower() == "local_gguf":
                # SOPHYANE_LOCAL_GGUF_PRIVATE_SHORT_TIMEOUT_V4
                #
                # A real LocalGgufProvider child exposes timeout/max_tokens
                # and receives the exact short Global-TXQ speculation budget.
                #
                # Some controller tests deliberately use object() merely as
                # an opaque provider-chain sentinel. Such an object has no
                # inference authority and cannot accept arbitrary attributes.
                # Preserve that sentinel instead of failing construction.
                mutable_budget_child = (
                    hasattr(
                        private_child,
                        "timeout",
                    )
                    and hasattr(
                        private_child,
                        "max_tokens",
                    )
                )

                if mutable_budget_child:
                    private_child.timeout = (
                        requested_timeout
                    )

                    private_child.max_tokens = (
                        requested_tokens
                    )

                    try:
                        private_child._sophyane_allow_short_speculative_timeout = (
                            True
                        )

                    except (
                        AttributeError,
                        TypeError,
                    ):
                        #
                        # Provider-like immutable doubles may expose budget
                        # fields but reject new marker attributes. They are not
                        # real LocalGgufProvider inference children.
                        #
                        pass

            cloned_chain.append(
                (
                    name,
                    private_child,
                )
            )

        cloned._providers = (
            cloned_chain
        )

        #
        # Keep wrapper metadata consistent with the private first child,
        # but do not rely on wrapper fields for local inference authority.
        #
        first_name, first_child = (
            cloned_chain[0]
        )

        cloned.timeout = int(
            getattr(
                first_child,
                "timeout",
                requested_timeout,
            )
        )

        cloned.max_tokens = int(
            getattr(
                first_child,
                "max_tokens",
                requested_tokens,
            )
        )

        cloned.primary = getattr(
            provider,
            "primary",
            first_name,
        )

        cloned.last_provider = ""
        cloned.last_errors = []

        return cloned

    #
    # Direct-provider fallback.
    #
    # Still clone before applying speculative resource limits.
    #
    cloned.timeout = (
        requested_timeout
    )

    cloned.max_tokens = (
        requested_tokens
    )

    cloned._sophyane_allow_short_speculative_timeout = (
        True
    )

    return cloned


class ReadOnlySpeculation:
    """One serial local-LLM speculative worker in a background thread."""

    def __init__(
        self,
        *,
        provider,
        prompt: str,
        system_prompt: str,
        max_loops: int,
        context_budget_chars: int,
        speculative_timeout_sec: int = 3,
        speculative_max_tokens: int = 256,
    ) -> None:
        # SOPHYANE_SPECULATION_PRIVATE_PROVIDER_V3
        #
        # Speculation must never borrow the full 600s / 4096-token
        # authoritative Mode-3 inference envelope.
        # SOPHYANE_SPECULATION_TXQ_BUDGET_AUTHORITY_V4
        #
        # The execution layer enforces fail-closed clamps, but the requested
        # resource envelope is selected by Global TXQ.
        requested_timeout = max(
            3,
            min(
                8,
                int(
                    speculative_timeout_sec
                ),
            ),
        )

        requested_tokens = max(
            64,
            min(
                256,
                int(
                    speculative_max_tokens
                ),
            ),
        )

        self.provider = bounded_speculation_provider(
            provider,
            timeout_sec=requested_timeout,
            max_tokens=requested_tokens,
        )

        self.speculative_timeout_sec = (
            requested_timeout
        )

        self.speculative_max_tokens = (
            requested_tokens
        )

        self.prompt = str(
            prompt
        )

        self.system_prompt = str(
            system_prompt
        )

        self.max_loops = max(
            0,
            min(
                6,
                int(max_loops),
            ),
        )

        self.context_budget_chars = max(
            1000,
            min(
                24000,
                int(context_budget_chars),
            ),
        )

        self._cancel = threading.Event()

        self._done = threading.Event()

        self._results: queue.Queue[
            SpeculativeEvidence
        ] = queue.Queue()

        self._errors: queue.Queue[
            str
        ] = queue.Queue()

        self._thread = threading.Thread(
            target=self._run,
            name="sophyane-mode3-readonly-speculation",
            daemon=True,
        )

        self.started_at = 0.0
        self.finished_at = 0.0

    @property
    def alive(self) -> bool:
        return bool(
            self._thread.is_alive()
        )

    def start(
        self,
    ) -> "ReadOnlySpeculation":
        if self.max_loops <= 0:
            self._done.set()
            return self

        self.started_at = (
            time.monotonic()
        )

        self._thread.start()

        return self

    def cancel(
        self,
    ) -> None:
        #
        # Cooperative cancellation:
        # never begin another local generation after Mode 4 returns.
        #
        self._cancel.set()

    def drain(
        self,
        *,
        timeout_sec: float,
    ) -> bool:
        """Wait for any in-flight local call to leave the single-flight lane."""

        self.cancel()

        timeout = max(
            0.0,
            float(
                timeout_sec
            ),
        )

        if not self._thread.is_alive():
            return True

        self._thread.join(
            timeout
        )

        return not self._thread.is_alive()

    def evidence(
        self,
    ) -> tuple[SpeculativeEvidence, ...]:
        items: list[
            SpeculativeEvidence
        ] = []

        while True:
            try:
                items.append(
                    self._results.get_nowait()
                )
            except queue.Empty:
                break

        return tuple(
            items
        )

    def errors(
        self,
    ) -> tuple[str, ...]:
        items: list[str] = []

        while True:
            try:
                items.append(
                    self._errors.get_nowait()
                )
            except queue.Empty:
                break

        return tuple(
            items
        )

    def _run(
        self,
    ) -> None:
        try:
            for loop in range(
                1,
                self.max_loops + 1,
            ):
                if self._cancel.is_set():
                    break

                started = (
                    time.monotonic()
                )

                loop_prompt = (
                    self.prompt
                    + "\n\n"
                    + "SPECULATIVE_LOOP="
                    + str(loop)
                    + "\n"
                    + (
                        "Do not repeat evidence already obvious from "
                        "earlier loops. Focus on one additional read-only "
                        "repository observation."
                    )
                )

                try:
                    response = (
                        self.provider.generate(
                            loop_prompt[
                                :self.context_budget_chars
                            ],
                            self.system_prompt,
                        )
                    )
                except Exception as error:
                    self._errors.put(
                        type(error).__name__
                        + ": "
                        + str(error)
                    )

                    break

                elapsed = max(
                    0.0,
                    (
                        time.monotonic()
                        - started
                    ),
                )

                text = str(
                    response
                    or ""
                ).strip()

                if text:
                    self._results.put(
                        SpeculativeEvidence(
                            loop=loop,
                            elapsed_sec=elapsed,
                            text=text[
                                :self.context_budget_chars
                            ],
                        )
                    )

                if self._cancel.is_set():
                    break

        finally:
            self.finished_at = (
                time.monotonic()
            )

            self._done.set()


def start_readonly_speculation(
    *,
    provider,
    prompt: str,
    max_loops: int,
    context_budget_chars: int,
    speculative_timeout_sec: int = 3,
    speculative_max_tokens: int = 256,
) -> ReadOnlySpeculation:
    """Start one serial read-only Mode-3 loop alongside Mode 4."""

    system_prompt = (
        "You are Sophyane Mode-3 local read-only preparation worker. "
        "Mode 4 has not selected a source change. "
        "You have no source-change authority and no mutation authority. "
        "Return repository evidence only. "
        "Do not return a candidate file contract. "
        "Do not choose an implementation. "
        "Do not claim execution."
    )

    return ReadOnlySpeculation(
        provider=provider,
        prompt=prompt,
        system_prompt=system_prompt,
        max_loops=max_loops,
        context_budget_chars=context_budget_chars,
        speculative_timeout_sec=(
            speculative_timeout_sec
        ),
        speculative_max_tokens=(
            speculative_max_tokens
        ),
    ).start()


def _normalise_path(
    value: str,
) -> str:
    path = str(
        PurePosixPath(
            str(value).strip()
        )
    )

    return path.casefold()


def extract_repository_paths(
    text: str,
) -> tuple[str, ...]:
    found = []

    seen = set()

    for match in _PATH.finditer(
        str(
            text
            or ""
        ),
    ):
        value = _normalise_path(
            match.group(1)
        )

        if value in seen:
            continue

        seen.add(
            value
        )

        found.append(
            value
        )

    return tuple(
        found
    )


def evidence_matches_instruction(
    *,
    evidence: str,
    instruction: str,
) -> bool:
    """Fail closed: reuse speculation only for explicit matching paths."""

    instruction_paths = set(
        extract_repository_paths(
            instruction
        )
    )

    evidence_paths = set(
        extract_repository_paths(
            evidence
        )
    )

    if not instruction_paths:
        return False

    if not evidence_paths:
        return False

    return bool(
        instruction_paths
        & evidence_paths
    )


def matching_speculative_context(
    *,
    evidence: tuple[
        SpeculativeEvidence,
        ...,
    ],
    instruction: str,
    maximum_chars: int,
) -> str:
    """Render only read-only evidence tied to Mode-4-selected file paths."""

    accepted = [
        item
        for item in evidence
        if evidence_matches_instruction(
            evidence=item.text,
            instruction=instruction,
        )
    ]

    if not accepted:
        return ""

    rendered = [
        "MODE3_MATCHED_READ_ONLY_SPECULATION",
        (
            "Mode 4's instruction remains authoritative. "
            "The following material is advisory read-only evidence only."
        ),
    ]

    for item in accepted:
        rendered.extend(
            (
                (
                    "SPECULATIVE_LOOP="
                    + str(item.loop)
                ),
                item.text,
            )
        )

    rendered.append(
        "END_MODE3_MATCHED_READ_ONLY_SPECULATION"
    )

    return "\n".join(
        rendered
    )[
        :max(
            1000,
            int(
                maximum_chars
            ),
        )
    ]


__all__ = [
    "ReadOnlySpeculation",
    "SpeculativeEvidence",
    "evidence_matches_instruction",
    "extract_repository_paths",
    "matching_speculative_context",
    "start_readonly_speculation",
]
