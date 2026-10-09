import json
from pathlib import Path


def test_nifdu_product_supervisor_runs_real_quality_cycle_contract(
    monkeypatch,
    tmp_path: Path,
):
    from sophyane import nifdu_product_supervisor as supervisor

    home = tmp_path / "home"
    home.mkdir()

    nifdu_bin = home / ".local/bin/nifdu-bin"
    nifdu_bin.parent.mkdir(parents=True)
    nifdu_bin.write_text("binary", encoding="utf-8")
    nifdu_bin.chmod(0o755)

    bridge = home / "nifdu/tools/nifdu_browser_bridge.py"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("# bridge\n", encoding="utf-8")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DISPLAY", ":2")
    monkeypatch.setenv("NIFDU_CDP_HOST", "127.0.0.1")
    monkeypatch.setenv("NIFDU_CDP_PORT", "9222")

    workspace = home / "nifdu-workspaces/product-test"
    product = workspace / "product/index.html"
    report = workspace / "final-report.json"

    calls = []

    class Completed:
        returncode = 0
        stdout = (
            "Final product\n"
            f"Product    : {product}\n"
            f"Report     : {report}\n"
        )
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

        product.parent.mkdir(parents=True, exist_ok=True)
        product.write_text(
            "<!doctype html><html><body>accepted game</body></html>",
            encoding="utf-8",
        )

        report.write_text(
            json.dumps(
                {
                    "accepted": True,
                    "score": 97,
                    "iterations": 3,
                    "final_file": str(product),
                    "preview": "http://127.0.0.1:45678",
                    "summary": "accepted",
                }
            ),
            encoding="utf-8",
        )

        return Completed()

    monkeypatch.setattr(
        supervisor.subprocess,
        "run",
        fake_run,
    )

    result = supervisor.run_nifdu_product_cycle(
        "make snake game"
    )

    assert len(calls) == 1

    command, kwargs = calls[0]

    assert command == [
        str(nifdu_bin),
        "build",
        "make snake game",
    ]

    assert kwargs["stdin"] is supervisor.subprocess.DEVNULL
    assert kwargs["text"] is True
    assert kwargs["capture_output"] is True

    env = kwargs["env"]

    assert env["NIFDU_BUILDER_PROVIDER"] == "browser_chatgpt"
    assert env["NIFDU_BUILDER_MODEL"] == "chatgpt-browser"
    assert env["NIFDU_JUDGE_PROVIDER"] == "browser_chatgpt"
    assert env["NIFDU_JUDGE_MODEL"] == "chatgpt-browser"

    assert env["NIFDU_BROWSER_BRIDGE"] == str(bridge)
    assert env["NIFDU_CDP_HOST"] == "127.0.0.1"
    assert env["NIFDU_CDP_PORT"] == "9222"

    assert result["accepted"] is True
    assert result["score"] == 97
    assert result["iterations"] == 3
    assert result["final_file"] == product
    assert result["final_file"].read_text(
        encoding="utf-8"
    ).endswith("</html>")


def test_nifdu_product_supervisor_rejects_unaccepted_product(
    monkeypatch,
    tmp_path: Path,
):
    from sophyane import nifdu_product_supervisor as supervisor

    home = tmp_path / "home"
    home.mkdir()

    nifdu_bin = home / ".local/bin/nifdu-bin"
    nifdu_bin.parent.mkdir(parents=True)
    nifdu_bin.write_text("binary", encoding="utf-8")
    nifdu_bin.chmod(0o755)

    bridge = home / "nifdu/tools/nifdu_browser_bridge.py"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("# bridge\n", encoding="utf-8")

    workspace = home / "nifdu-workspaces/product-test"
    product = workspace / "product/index.html"
    report = workspace / "final-report.json"

    monkeypatch.setenv("HOME", str(home))

    class Completed:
        returncode = 1
        stdout = (
            "Final product\n"
            f"Product    : {product}\n"
            f"Report     : {report}\n"
        )
        stderr = ""

    def fake_run(command, **kwargs):
        product.parent.mkdir(parents=True, exist_ok=True)
        product.write_text(
            "<html><body>failed</body></html>",
            encoding="utf-8",
        )

        report.write_text(
            json.dumps(
                {
                    "accepted": False,
                    "score": 88,
                    "iterations": 10,
                    "final_file": str(product),
                    "summary": "quality threshold not reached",
                }
            ),
            encoding="utf-8",
        )

        return Completed()

    monkeypatch.setattr(
        supervisor.subprocess,
        "run",
        fake_run,
    )

    result = supervisor.run_nifdu_product_cycle(
        "make snake game"
    )

    assert result["accepted"] is False
    assert result["score"] == 88
    assert result["iterations"] == 10
