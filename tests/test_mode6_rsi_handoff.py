from __future__ import annotations

from types import SimpleNamespace

import pytest

import sophyane.human_conversation as hc


def observation(**changes):
    values = {
        "problem": "Mode 6 needed the same clarification twice.",
        "evidence": (
            "The user repeated the same correction.",
            "The first answer did not preserve the intended context.",
        ),
        "component": "human_conversation",
        "suggested_direction": (
            "Improve bounded conversational grounding."
        ),
        "source_mutation_required": True,
    }
    values.update(changes)

    return hc.ImprovementObservation(**values)


def test_valid_observation_is_recorded_as_nonexecuting_code_hint(
    monkeypatch,
):
    import sophyane.mode6_rsi_handoff as handoff

    calls = []

    monkeypatch.setattr(
        handoff.ledger,
        "propose_improvement",
        lambda *args, **kwargs: (
            calls.append((args, kwargs))
            or {
                "ok": True,
                "block": {
                    "index": 1,
                },
            }
        ),
    )

    result = handoff.record_mode6_improvement_observation(
        observation()
    )

    assert result["ok"] is True
    assert len(calls) == 1

    args, kwargs = calls[0]

    assert args[0] == "code_hint"
    assert "human_conversation" in args[1]
    assert "Mode 6 needed" in args[2]
    assert "Improve bounded" in args[2]

    evidence = kwargs["evidence"]

    assert evidence["source"] == "mode6_conversation"
    assert evidence["component"] == "human_conversation"
    assert evidence["source_mutation_required"] is True
    assert evidence["trusted"] is False
    assert evidence["instruction_authority"] is False
    assert evidence["mutation_authority"] is False
    assert evidence["requires_grounded_weakness"] is True
    assert evidence["observation_evidence"] == [
        "The user repeated the same correction.",
        "The first answer did not preserve the intended context.",
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"trusted": True},
        {"instruction_authority": True},
        {"mutation_authority": True},
    ],
)
def test_authority_bearing_observation_fails_closed(
    monkeypatch,
    changes,
):
    import sophyane.mode6_rsi_handoff as handoff

    monkeypatch.setattr(
        handoff.ledger,
        "propose_improvement",
        lambda *_args, **_kwargs: pytest.fail(
            "authority-bearing observation reached ledger"
        ),
    )

    result = handoff.record_mode6_improvement_observation(
        observation(**changes)
    )

    assert result["ok"] is False
    assert result["recorded"] is False
    assert result["reason"] == (
        "observation_has_authority"
    )


def test_none_observation_is_noop(
    monkeypatch,
):
    import sophyane.mode6_rsi_handoff as handoff

    monkeypatch.setattr(
        handoff.ledger,
        "propose_improvement",
        lambda *_args, **_kwargs: pytest.fail(
            "None observation reached ledger"
        ),
    )

    result = handoff.record_mode6_improvement_observation(
        None
    )

    assert result == {
        "ok": True,
        "recorded": False,
        "reason": "no_observation",
    }


def test_ledger_failure_does_not_become_execution_authority(
    monkeypatch,
):
    import sophyane.mode6_rsi_handoff as handoff

    monkeypatch.setattr(
        handoff.ledger,
        "propose_improvement",
        lambda *_args, **_kwargs: (
            (_ for _ in ()).throw(
                OSError("state unavailable")
            )
        ),
    )

    result = handoff.record_mode6_improvement_observation(
        observation()
    )

    assert result["ok"] is False
    assert result["recorded"] is False
    assert result["reason"] == "ledger_error"
    assert "OSError" in result["error"]


def test_handoff_module_has_no_executable_rsi_surface():
    import inspect
    import sophyane.mode6_rsi_handoff as handoff

    source = inspect.getsource(handoff)

    assert "Controller(" not in source
    assert ".run_once(" not in source
    assert "WeaknessRecord(" not in source
    assert "promote(" not in source
    assert "Candidate.create(" not in source


def test_cli_turn_handoff_records_only_result_observation(
    monkeypatch,
):
    import sophyane.human_conversation_cli as cli

    seen = []

    monkeypatch.setattr(
        cli,
        "record_mode6_improvement_observation",
        lambda value: seen.append(value) or {
            "ok": True,
            "recorded": True,
        },
    )

    obs = observation()

    result = SimpleNamespace(
        reply="Normal conversational reply.",
        improvement_observation=obs,
    )

    returned = cli._handoff_turn_improvement(
        result
    )

    assert seen == [obs]
    assert returned == {
        "ok": True,
        "recorded": True,
    }


def test_cli_turn_handoff_is_noop_without_observation(
    monkeypatch,
):
    import sophyane.human_conversation_cli as cli

    seen = []

    monkeypatch.setattr(
        cli,
        "record_mode6_improvement_observation",
        lambda value: seen.append(value) or {
            "ok": True,
        },
    )

    result = SimpleNamespace(
        reply="Hello.",
        improvement_observation=None,
    )

    returned = cli._handoff_turn_improvement(
        result
    )

    assert seen == []
    assert returned == {
        "ok": True,
        "recorded": False,
        "reason": "no_observation",
    }


def test_cli_successful_conversation_paths_call_handoff():
    from pathlib import Path

    source = Path(
        "src/sophyane/human_conversation_cli.py"
    ).read_text()

    # --once, visual conversation and ordinary conversation.
    assert source.count(
        "_handoff_turn_improvement("
    ) >= 4
