from types import SimpleNamespace
from unittest.mock import patch

from sophyane.native_capability import try_any_native_reply


def test_nifdu_build_requires_explicit_command():
    assert try_any_native_reply("explain recursion") is None


def test_nifdu_build_uses_discovered_binary_without_auto_install():
    probe = SimpleNamespace(path="/fake/nifdu")
    completed = SimpleNamespace(returncode=0, stdout="report", stderr="")
    with patch("sophyane.native_backends.probe_nifdu", return_value=probe), patch(
        "sophyane.native_capability.subprocess.run", return_value=completed
    ) as run:
        assert try_any_native_reply("nifdu build make a calculator") == "report"
    run.assert_called_once()
    assert run.call_args.args[0] == ["/fake/nifdu", "build", "make a calculator"]


def test_mode4_session_selects_browser_provider_for_nifdu():
    probe = SimpleNamespace(path="/fake/nifdu")
    completed = SimpleNamespace(returncode=0, stdout="report", stderr="")
    with patch.dict("os.environ", {"SOPHYANE_SESSION_MODE": "nifdu_llm"}), patch(
        "sophyane.native_backends.probe_nifdu", return_value=probe
    ), patch("sophyane.native_capability.subprocess.run", return_value=completed) as run:
        try_any_native_reply("nifdu build make a game")
    env = run.call_args.kwargs["env"]
    assert env["NIFDU_BUILDER_PROVIDER"] == "browser_chatgpt"
    assert env["NIFDU_JUDGE_PROVIDER"] == "browser_chatgpt"


def test_empty_nifdu_build_is_neutral_prompt():
    assert "provide a product request" in try_any_native_reply("nifdu build").lower()
