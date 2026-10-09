import importlib.util
import json
from pathlib import Path


BRIDGE = (
    Path.home()
    / "nifdu"
    / "tools"
    / "nifdu_browser_bridge.py"
)


def _load_bridge():
    spec = importlib.util.spec_from_file_location(
        "nifdu_bridge_persistent_target_test",
        BRIDGE,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _chatgpt_page(target_id: str):
    return {
        "id": target_id,
        "type": "page",
        "url": "https://chatgpt.com/",
        "title": "ChatGPT",
        "webSocketDebuggerUrl": (
            "ws://127.0.0.1:9222/devtools/page/"
            + target_id
        ),
    }


def test_bridge_reuses_persisted_target_across_process_state(
    monkeypatch,
    tmp_path,
):
    bridge = _load_bridge()

    binding = tmp_path / "target-binding.json"

    monkeypatch.setenv(
        "NIFDU_TARGET_BINDING_FILE",
        str(binding),
    )

    # Simulate a target persisted by an earlier Python bridge
    # process. The current module-level dictionary is empty.
    binding.write_text(
        json.dumps({"chatgpt": "nifdu-owned-target"}),
        encoding="utf-8",
    )
    bridge._SESSION_TARGETS.clear()

    existing = _chatgpt_page("sophyane-conversation")
    owned = _chatgpt_page("nifdu-owned-target")

    selected = bridge.find_page(
        "chatgpt",
        [existing, owned],
    )

    assert selected is not None
    assert selected["id"] == "nifdu-owned-target"
    assert (
        bridge._SESSION_TARGETS["chatgpt"]
        == "nifdu-owned-target"
    )


def test_bridge_persists_new_binding(
    monkeypatch,
    tmp_path,
):
    bridge = _load_bridge()

    binding = tmp_path / "target-binding.json"

    monkeypatch.setenv(
        "NIFDU_TARGET_BINDING_FILE",
        str(binding),
    )

    bridge._SESSION_TARGETS.clear()

    selected = bridge.find_page(
        "chatgpt",
        [_chatgpt_page("new-owned-target")],
    )

    assert selected is not None
    assert selected["id"] == "new-owned-target"

    payload = json.loads(
        binding.read_text(encoding="utf-8")
    )

    assert payload == {
        "chatgpt": "new-owned-target",
    }


def test_supervisor_supplies_unique_binding_file(
    monkeypatch,
    tmp_path,
):
    from sophyane import nifdu_product_supervisor as supervisor

    home = tmp_path / "home"
    bin_dir = home / ".local/bin"
    bridge_dir = home / "nifdu/tools"
    workspace = home / "nifdu-workspaces/product-test"
    product = workspace / "product/index.html"

    bin_dir.mkdir(parents=True)
    bridge_dir.mkdir(parents=True)
    product.parent.mkdir(parents=True)

    nifdu_bin = bin_dir / "nifdu-bin"
    nifdu_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    nifdu_bin.chmod(0o755)

    bridge = bridge_dir / "nifdu_browser_bridge.py"
    bridge.write_text("# test bridge\n", encoding="utf-8")

    product.write_text(
        "<!doctype html><html><body>"
        "accepted"
        "</body></html>",
        encoding="utf-8",
    )

    report = workspace / "final-report.json"
    report.write_text(
        json.dumps(
            {
                "accepted": True,
                "score": 99,
                "iterations": 1,
                "summary": "accepted",
                "final_file": str(product),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv(
        "NIFDU_TARGET_BINDING_FILE",
        raising=False,
    )

    seen = []

    class Completed:
        returncode = 0
        stdout = f"Report : {report}\n"
        stderr = ""

    def fake_run(*args, **kwargs):
        seen.append(kwargs["env"])
        return Completed()

    monkeypatch.setattr(
        supervisor.subprocess,
        "run",
        fake_run,
    )

    supervisor.run_nifdu_product_cycle(
        "make snake game"
    )
    supervisor.run_nifdu_product_cycle(
        "make pong game"
    )

    assert len(seen) == 2

    first = seen[0].get(
        "NIFDU_TARGET_BINDING_FILE"
    )
    second = seen[1].get(
        "NIFDU_TARGET_BINDING_FILE"
    )

    assert first
    assert second
    assert first != second

    # Supervisor-owned state must not be a global/reused
    # user binding inherited from the parent environment.
    assert Path(first).name
    assert Path(second).name


def test_existing_bridge_behavior_without_binding_file(
    monkeypatch,
):
    bridge = _load_bridge()

    monkeypatch.delenv(
        "NIFDU_TARGET_BINDING_FILE",
        raising=False,
    )

    bridge._SESSION_TARGETS.clear()

    page = bridge.find_page(
        "chatgpt",
        [_chatgpt_page("ordinary-target")],
    )

    assert page is not None
    assert page["id"] == "ordinary-target"


def test_empty_owned_binding_creates_dedicated_target(
    monkeypatch,
    tmp_path,
):
    bridge = _load_bridge()

    binding = tmp_path / "target-binding.json"

    monkeypatch.setenv(
        "NIFDU_TARGET_BINDING_FILE",
        str(binding),
    )

    bridge._SESSION_TARGETS.clear()

    existing = _chatgpt_page(
        "sophyane-conversation"
    )
    dedicated = _chatgpt_page(
        "nifdu-dedicated-target"
    )

    monkeypatch.setattr(
        bridge,
        "pages",
        lambda: [existing],
    )

    created = []

    def fake_create(url):
        created.append(url)
        return dedicated

    monkeypatch.setattr(
        bridge,
        "create_page",
        fake_create,
    )

    selected = bridge.ensure_page(
        "chatgpt",
        timeout=0.1,
    )

    assert created == [
        bridge.PROFILES["chatgpt"]["url"]
    ]
    assert selected["id"] == (
        "nifdu-dedicated-target"
    )

    payload = json.loads(
        binding.read_text(encoding="utf-8")
    )

    assert payload == {
        "chatgpt": "nifdu-dedicated-target",
    }
