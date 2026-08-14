from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sophyane.race_execution import (
    VerificationResult,
    run_race_apply_verify,
)
from sophyane.race_orchestrator import make_sli_producer


REQUEST = (
    "Create a file named integration-proof.txt containing exactly: "
    "Sophyane deterministic integration proof"
)

EXPECTED = b"Sophyane deterministic integration proof"


def test_real_sli_deterministic_exact_write_promotes_once_and_bypasses_unrelated_pytest(
    tmp_path: Path,
):
    race_calls = []
    verifier_calls = []
    proposals = []

    shadow_registry = {}

    def race_runner(
        request,
        *,
        workspace,
        config,
        progress,
        timeout,
    ):
        race_calls.append(request)

        if len(race_calls) != 1:
            raise AssertionError(
                "trusted deterministic exact write entered "
                "an unexpected repair round"
            )

        producer = make_sli_producer(
            request=request,
            workspace=workspace,
            shadow_registry=shadow_registry,
            progress=progress,
        )

        proposal = producer()
        proposals.append(proposal)

        payload = proposal.payload

        assert payload["route"] == "deterministic_capability"
        assert payload["success"] is True
        assert (
            payload["capability"]
            == "filesystem.write_exact_verified"
        )

        changed = payload["changed_files"]

        assert changed == ("integration-proof.txt",)

        # Producer is speculative. Authoritative workspace must
        # still be untouched at this point.
        assert not (
            workspace
            / "integration-proof.txt"
        ).exists()

        return SimpleNamespace(
            winner=SimpleNamespace(
                worker="sli",
                value=proposal,
            )
        )

    def unrelated_failing_verifier(_workspace):
        verifier_calls.append(True)

        return [
            VerificationResult(
                ok=False,
                command=(
                    "pytest",
                    "-q",
                    "--disable-warnings",
                    "--maxfail=1",
                ),
                returncode=1,
                output=(
                    "FAILED unrelated_test.py::"
                    "test_unrelated_failure"
                ),
            )
        ]

    result = run_race_apply_verify(
        REQUEST,
        workspace=tmp_path,
        config={},
        race_runner=race_runner,
        verifier=unrelated_failing_verifier,
        max_rounds=3,
    )

    target = (
        tmp_path
        / "integration-proof.txt"
    )

    assert result.ok is True

    # Exactly one race execution.
    assert race_calls == [REQUEST]

    # Trusted exact-write capability bypasses unrelated
    # repository-wide verifier entirely.
    assert verifier_calls == []

    assert len(proposals) == 1

    # Authoritative promotion produced exact bytes.
    assert target.exists()
    assert target.read_bytes() == EXPECTED

    # Shadow provenance was retained.
    payload = proposals[0].payload

    assert payload["route"] == "deterministic_capability"
    assert payload["success"] is True
    assert (
        payload["capability"]
        == "filesystem.write_exact_verified"
    )

    assert payload["changed_files"] == (
        "integration-proof.txt",
    )
