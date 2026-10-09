
from sophyane import human_conversation_cli as cli
from sophyane.rsi import verification
from sophyane.rsi.sandbox import SandboxUnavailable


def test_promoted_retry_reports_unavailable_sandbox(monkeypatch, tmp_path):
    program = "sandbox_probe.py"
    code = "print('expected')\n"
    (tmp_path / program).write_text(code)
    (tmp_path / "input.sphy").write_text("input\n")
    (tmp_path / "expected.txt").write_text("expected\n")
    calls = []

    def unavailable(command, workspace, **kwargs):
        calls.append((command, workspace))
        raise SandboxUnavailable("synthetic sandbox unavailable")

    monkeypatch.setattr(verification, "run_command", unavailable)
    candidate = {
        "status": "TRUSTED_PROMOTED",
        "capability_class": "executable." + program,
        "files": {program: code},
    }
    result = cli._execute_mode6_promoted_capability(
        candidate,
        "Run sandbox_probe.py input.sphy and compare against expected.txt",
        workspace=tmp_path,
    )
    assert result is False
    assert len(calls) == 1
    assert (tmp_path / program).read_text() == code
