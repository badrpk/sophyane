from __future__ import annotations

from pathlib import Path

from sophyane.autonomy import AutonomyPolicy, RiskLevel
from sophyane.v13_cli import _execution_policy, build_parser


def test_safe_action_auto_continues_after_timeout(tmp_path: Path) -> None:
    policy = AutonomyPolicy(workspace=tmp_path, confirmation_timeout=0)
    decision = policy.decide(
        "write project file and run tests",
        target=tmp_path / "project" / "test_app.py",
        confirmer=lambda _action, _timeout: None,
    )
    assert decision.allowed is True
    assert decision.risk is RiskLevel.SAFE
    assert decision.source == "timeout"


def test_workspace_escape_is_blocked(tmp_path: Path) -> None:
    policy = AutonomyPolicy(workspace=tmp_path, confirmation_timeout=0)
    risk, reason = policy.classify("write file", target=tmp_path.parent / "outside.txt")
    assert risk is RiskLevel.BLOCKED
    assert "workspace" in reason


def test_human_denial_overrides_safe_timeout(tmp_path: Path) -> None:
    policy = AutonomyPolicy(workspace=tmp_path, confirmation_timeout=0)
    decision = policy.decide(
        "run tests",
        target=tmp_path,
        confirmer=lambda _action, _timeout: False,
    )
    assert decision.allowed is False
    assert decision.source == "human"


def test_cli_defaults_to_ten_second_safe_auto_continue() -> None:
    parser = build_parser()
    args = parser.parse_args(["hello"])
    assert args.approval_timeout == 10.0
    assert args.no_auto_continue is False
    policy = _execution_policy(args.approval_timeout, True)
    assert "10 seconds" in policy
    assert "safe" in policy.lower()


def test_cli_can_disable_auto_continue() -> None:
    parser = build_parser()
    args = parser.parse_args(["--no-auto-continue", "hello"])
    assert args.no_auto_continue is True
    assert "disabled" in _execution_policy(10, False)
