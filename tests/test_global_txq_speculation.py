from __future__ import annotations

import threading
import time

from sophyane.global_txq_speculation import (
    SpeculativeEvidence,
    evidence_matches_instruction,
    matching_speculative_context,
    start_readonly_speculation,
)


class FastProvider:
    primary = "local_gguf"

    def __init__(self):
        self.calls = 0
        self.last_provider = ""

    def generate(
        self,
        prompt,
        system_prompt,
    ):
        self.calls += 1
        self.last_provider = "local_gguf"

        assert (
            "read-only"
            in system_prompt.casefold()
        )

        return (
            "Relevant evidence: "
            "tests/test_recursive_evolution_controller.py "
            "already contains RSI authority tests."
        )


def test_speculation_runs_multiple_readonly_loops():
    provider = FastProvider()

    worker = start_readonly_speculation(
        provider=provider,
        prompt=(
            "MODE3_READ_ONLY_SPECULATIVE_PREPARATION\n"
            "Inspect tests/test_recursive_evolution_controller.py."
        ),
        max_loops=3,
        context_budget_chars=4000,
    )

    assert worker.drain(
        timeout_sec=2.0
    )

    evidence = worker.evidence()

    assert (
        len(evidence)
        >= 1
    )

    assert provider.calls <= 3


def test_mode4_cancellation_prevents_new_speculative_loops():
    entered = threading.Event()
    release = threading.Event()

    class BlockingProvider:
        primary = "local_gguf"

        def __init__(self):
            self.calls = 0
            self.last_provider = ""

        def generate(
            self,
            prompt,
            system_prompt,
        ):
            self.calls += 1
            self.last_provider = "local_gguf"

            entered.set()

            release.wait(
                timeout=2
            )

            return (
                "tests/test_recursive_evolution_controller.py"
            )

    provider = BlockingProvider()

    worker = start_readonly_speculation(
        provider=provider,
        prompt="read only",
        max_loops=4,
        context_budget_chars=2000,
    )

    assert entered.wait(
        timeout=1
    )

    worker.cancel()

    release.set()

    assert worker.drain(
        timeout_sec=1
    )

    # GLOBAL TXQ V3:
    #
    # Read-only speculation owns a private provider clone.
    # The authoritative provider must remain completely untouched.
    assert worker.provider is not provider
    assert worker.provider.calls == 1
    assert provider.calls == 0


def test_matching_speculation_requires_mode4_selected_path():
    evidence = (
        SpeculativeEvidence(
            loop=1,
            elapsed_sec=0.1,
            text=(
                "tests/test_recursive_evolution_controller.py "
                "contains the relevant regression tests"
            ),
        ),
        SpeculativeEvidence(
            loop=2,
            elapsed_sec=0.1,
            text=(
                "src/sophyane/providers/local_gguf.py "
                "contains unrelated provider logic"
            ),
        ),
    )

    instruction = (
        "Add one regression test in "
        "tests/test_recursive_evolution_controller.py only."
    )

    rendered = matching_speculative_context(
        evidence=evidence,
        instruction=instruction,
        maximum_chars=5000,
    )

    assert (
        "test_recursive_evolution_controller.py"
        in rendered
    )

    assert (
        "local_gguf.py"
        not in rendered
    )


def test_evidence_without_explicit_mode4_path_is_rejected():
    assert not evidence_matches_instruction(
        evidence=(
            "tests/test_recursive_evolution_controller.py "
            "contains useful evidence"
        ),
        instruction=(
            "Improve one suitable RSI test."
        ),
    )


def test_speculation_uses_private_bounded_provider_clone():
    from sophyane.global_txq_speculation import (
        ReadOnlySpeculation,
    )

    class Child:
        def __init__(self):
            self.timeout = 600
            self.max_tokens = 4096
            self.model = "local"

        def generate(
            self,
            prompt,
            system_prompt,
        ):
            return "FILE=tests/probe.py"

    class Wrapper:
        primary = "local_gguf"

        def __init__(self):
            self.timeout = 600
            self.max_tokens = 4096
            self._providers = [
                (
                    "local_gguf",
                    Child(),
                ),
            ]

        def generate(
            self,
            prompt,
            system_prompt,
        ):
            return self._providers[
                0
            ][1].generate(
                prompt,
                system_prompt,
            )

    original = Wrapper()

    original_child = (
        original._providers[
            0
        ][1]
    )

    worker = ReadOnlySpeculation(
        provider=original,
        prompt="read only",
        system_prompt="read only",
        max_loops=1,
        context_budget_chars=2000,
    )

    speculative = worker.provider

    speculative_child = (
        speculative._providers[
            0
        ][1]
    )

    assert speculative is not original

    assert (
        speculative_child
        is not original_child
    )

    assert speculative.timeout == 3
    assert speculative.max_tokens == 256

    assert speculative_child.timeout == 3
    assert speculative_child.max_tokens == 256

    #
    # Authoritative provider remains untouched.
    #
    assert original.timeout == 600
    assert original.max_tokens == 4096

    assert original_child.timeout == 600
    assert original_child.max_tokens == 4096


def test_bounded_speculation_provider_does_not_mutate_direct_provider():
    from sophyane.global_txq_speculation import (
        bounded_speculation_provider,
    )

    class Provider:
        def __init__(self):
            self.timeout = 600
            self.max_tokens = 4096

    original = Provider()

    bounded = bounded_speculation_provider(
        original
    )

    assert bounded is not original

    assert bounded.timeout == 3
    assert bounded.max_tokens == 256

    assert original.timeout == 600
    assert original.max_tokens == 4096


def test_speculation_accepts_txq_selected_short_budget():
    from sophyane.global_txq_speculation import (
        start_readonly_speculation,
    )

    class Provider:
        primary = "local_gguf"

        def __init__(self):
            self.timeout = 600
            self.max_tokens = 4096
            self.last_provider = ""
            self._providers = [
                (
                    "local_gguf",
                    self,
                ),
            ]

        def generate(
            self,
            prompt,
            system_prompt,
        ):
            self.last_provider = "local_gguf"
            return "read-only evidence"

    provider = Provider()

    worker = start_readonly_speculation(
        provider=provider,
        prompt="read only",
        max_loops=1,
        context_budget_chars=2000,
        speculative_timeout_sec=3,
        speculative_max_tokens=256,
    )

    assert worker.drain(
        timeout_sec=2.0
    )

    assert (
        worker.speculative_timeout_sec
        == 3
    )

    assert (
        worker.speculative_max_tokens
        == 256
    )

    assert (
        worker.provider
        is not provider
    )

    assert (
        provider.timeout
        == 600
    )

    assert (
        provider.max_tokens
        == 4096
    )


def test_speculation_v4_clamps_excessive_caller_budget():
    from sophyane.global_txq_speculation import (
        ReadOnlySpeculation,
    )

    class Provider:
        primary = "local_gguf"

        def __init__(self):
            self.timeout = 600
            self.max_tokens = 4096
            self._providers = [
                (
                    "local_gguf",
                    self,
                ),
            ]

        def generate(
            self,
            prompt,
            system_prompt,
        ):
            return "evidence"

    worker = ReadOnlySpeculation(
        provider=Provider(),
        prompt="read only",
        system_prompt="read only",
        max_loops=0,
        context_budget_chars=2000,
        speculative_timeout_sec=999,
        speculative_max_tokens=9999,
    )

    assert (
        worker.speculative_timeout_sec
        == 8
    )

    assert (
        worker.speculative_max_tokens
        == 256
    )


def test_v4_private_local_child_gets_exact_txq_timeout_and_marker():
    from sophyane.global_txq_speculation import (
        bounded_speculation_provider,
    )
    from sophyane.recursive_evolution_controller import (
        create_mode3_local_provider,
    )

    authoritative = (
        create_mode3_local_provider()
    )

    private = bounded_speculation_provider(
        authoritative,
        timeout_sec=3,
        max_tokens=256,
    )

    authoritative_child = (
        authoritative._providers[0][1]
    )

    private_child = (
        private._providers[0][1]
    )

    assert private is not authoritative

    assert (
        private_child
        is not authoritative_child
    )

    assert int(
        private.timeout
    ) == 3

    assert int(
        private_child.timeout
    ) == 3

    assert int(
        private_child.max_tokens
    ) == 256

    assert (
        getattr(
            private_child,
            "_sophyane_allow_short_speculative_timeout",
            False,
        )
        is True
    )

    assert int(
        authoritative_child.timeout
    ) > 8

    assert int(
        authoritative_child.max_tokens
    ) > 256

    assert (
        getattr(
            authoritative_child,
            "_sophyane_allow_short_speculative_timeout",
            False,
        )
        is False
    )


def test_v4_bounded_speculation_accepts_opaque_local_chain_child():
    from sophyane.global_txq_speculation import (
        bounded_speculation_provider,
    )

    class Provider:
        primary = "local_gguf"

        def __init__(self):
            self.timeout = 600
            self.max_tokens = 4096
            self._providers = [
                (
                    "local_gguf",
                    object(),
                ),
            ]

    authoritative = Provider()

    private = bounded_speculation_provider(
        authoritative,
        timeout_sec=3,
        max_tokens=256,
    )

    assert private is not authoritative

    assert int(
        private.timeout
    ) == 3

    assert int(
        private.max_tokens
    ) == 256

    assert len(
        private._providers
    ) == 1

    name, private_child = (
        private._providers[
            0
        ]
    )

    assert name == "local_gguf"

    assert (
        type(
            private_child
        )
        is object
    )

    assert int(
        authoritative.timeout
    ) == 600

    assert int(
        authoritative.max_tokens
    ) == 4096


def test_v5_private_clone_accepts_compact_evidence_token_budget():
    from sophyane.global_txq_speculation import (
        bounded_speculation_provider,
    )

    class Child:
        def __init__(self):
            self.timeout = 600
            self.max_tokens = 4096

    class Provider:
        primary = "local_gguf"

        def __init__(self):
            self.timeout = 600
            self.max_tokens = 4096
            self._providers = [
                (
                    "local_gguf",
                    Child(),
                ),
            ]

    authoritative = Provider()

    private = bounded_speculation_provider(
        authoritative,
        timeout_sec=3,
        max_tokens=96,
    )

    authoritative_child = (
        authoritative._providers[
            0
        ][1]
    )

    private_child = (
        private._providers[
            0
        ][1]
    )

    assert private is not authoritative

    assert (
        private_child
        is not authoritative_child
    )

    assert int(
        private.timeout
    ) == 3

    assert int(
        private.max_tokens
    ) == 96

    assert int(
        private_child.timeout
    ) == 3

    assert int(
        private_child.max_tokens
    ) == 96

    assert getattr(
        private_child,
        "_sophyane_allow_short_speculative_timeout",
        False,
    ) is True

    assert int(
        authoritative.timeout
    ) == 600

    assert int(
        authoritative.max_tokens
    ) == 4096

    assert int(
        authoritative_child.timeout
    ) == 600

    assert int(
        authoritative_child.max_tokens
    ) == 4096
