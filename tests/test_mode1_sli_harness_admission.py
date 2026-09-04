from __future__ import annotations

import sophyane.race_orchestrator as orchestrator


def test_mode1_admits_sli_for_bounded_pytest_repair(tmp_path):
    request = "Fix the pytest failure in production code and rerun tests."

    assert orchestrator._mode1_sli_applies(request) is True

    workers = orchestrator.build_real_workers(
        request=request,
        workspace=tmp_path,
        config={},
        progress=lambda _: None,
    )

    assert "sli" in workers


def test_mode1_sli_harness_admission_stays_narrow():
    assert orchestrator._mode1_sli_applies("answer hello") is False
    assert orchestrator._mode1_sli_applies("build an API from scratch") is False
    assert (
        orchestrator._mode1_sli_applies(
            "research memory and internet"
        )
        is True
    )
