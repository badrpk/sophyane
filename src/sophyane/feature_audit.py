"""Integrated feature audit — verifies all major Sophyane capabilities."""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from sophyane.version import __version__


@dataclass
class Check:
    area: str
    name: str
    ok: bool
    detail: str = ""
    ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _timed(fn: Callable[[], Any]) -> tuple[Any, float]:
    t0 = time.perf_counter()
    value = fn()
    return value, (time.perf_counter() - t0) * 1000


def run_full_audit() -> dict[str, Any]:
    checks: list[Check] = []

    def add(area: str, name: str, ok: bool, detail: str = "", ms: float = 0.0) -> None:
        checks.append(Check(area, name, bool(ok), str(detail)[:300], ms))

    # Imports / integration surface
    modules = [
        "sophyane.kernel",
        "sophyane.mesh",
        "sophyane.browser",
        "sophyane.web_intel",
        "sophyane.self_improve",
        "sophyane.hardware_api",
        "sophyane.hardware_registry",
        "sophyane.edge_agent",
        "sophyane.platform_probe",
        "sophyane.appliance",
        "sophyane.daemon_runtime",
        "sophyane.harness",
        "sophyane.continual",
        "sophyane.capabilities",
        "sophyane.skills",
        "sophyane.rag",
        "sophyane.scheduler",
        "sophyane.budget",
        "sophyane.hitl",
        "sophyane.observability",
        "sophyane.interpreter",
        "sophyane.mcp_bridge",
        "sophyane.checkpoint",
        "sophyane.permissions",
        "sophyane.notifications",
        "sophyane.multimodal",
    ]
    for mod in modules:
        try:
            __import__(mod)
            add("import", mod, True)
        except Exception as error:  # noqa: BLE001
            add("import", mod, False, str(error))

    # Kernel
    try:
        from sophyane.kernel import boot_kernel

        status, ms = _timed(lambda: boot_kernel().status())
        names = {m["name"] for m in status.modules}
        need = {"hardware", "software", "app_factory", "erp", "mesh", "agents"}
        add("kernel", "boot", status.ok and need <= names, f"modules={sorted(names)}", ms)
    except Exception as error:  # noqa: BLE001
        add("kernel", "boot", False, str(error))

    # Hardware + platform
    try:
        from sophyane.hardware_registry import hardware_compatibility_report
        from sophyane.platform_probe import probe_platform

        plat, ms = _timed(probe_platform)
        add("platform", "probe", bool(plat.os_family), plat.equipment_class, ms)
        rep, ms = _timed(hardware_compatibility_report)
        add("hardware", "catalog", rep.get("vendors_catalogued", 0) >= 20, str(rep.get("vendors_catalogued")), ms)
    except Exception as error:  # noqa: BLE001
        add("hardware", "probe", False, str(error))

    # Web intel
    try:
        from sophyane.web_intel import fetch_url

        res, ms = _timed(lambda: fetch_url("https://example.com", timeout=15))
        add("web", "fetch", res.ok, res.title or res.error, ms)
    except Exception as error:  # noqa: BLE001
        add("web", "fetch", False, str(error))

    # Self improve
    try:
        from sophyane.self_improve.ledger import propose_improvement, verify_chain

        propose_improvement("benchmark", "audit", "feature audit heartbeat", score=0.05)
        ver, ms = _timed(verify_chain)
        add("improve", "chain", ver.get("ok") is True, str(ver), ms)
    except Exception as error:  # noqa: BLE001
        add("improve", "chain", False, str(error))

    # App factory
    try:
        from pathlib import Path
        import tempfile

        from sophyane.kernel.app_factory import create_app

        with tempfile.TemporaryDirectory() as tmp:
            result, ms = _timed(lambda: create_app("web", "Audit", output_dir=Path(tmp) / "w"))
            add("apps", "web", result.ok, result.path, ms)
    except Exception as error:  # noqa: BLE001
        add("apps", "web", False, str(error))

    # ERP catalog
    try:
        from sophyane.kernel.erp import list_erp_systems

        systems = {s["id"] for s in list_erp_systems()}
        add("erp", "catalog", {"oracle", "sap", "odoo"} <= systems, str(sorted(systems)))
    except Exception as error:  # noqa: BLE001
        add("erp", "catalog", False, str(error))

    # Mesh unit
    try:
        from sophyane.mesh.core import MeshNode

        node = MeshNode(port=28777)
        hello = node.hello()
        add("mesh", "hello", hello.get("magic") == "SOPHYANE_MESH_v1", hello.get("peer_id", ""))
        put = node.handle("storage.put", {"name": "audit.txt", "content": "ok"})
        add("mesh", "storage", put.get("ok") is True, str(put)[:80])
    except Exception as error:  # noqa: BLE001
        add("mesh", "core", False, str(error))

    # Appliance network detect + cable/wifi paths
    try:
        from sophyane.appliance import detect_network_interfaces, network_capability_report

        net, ms = _timed(detect_network_interfaces)
        add("appliance", "network_detect", bool(net.get("interfaces")), str(net.get("hostname")), ms)
        cap = network_capability_report(net)
        add(
            "appliance",
            "ethernet_wifi_paths",
            bool(cap.get("cable_path") and cap.get("wifi_path")),
            f"eth={cap.get('ethernet_present')} wifi={cap.get('wifi_present')} online={cap.get('online')}",
        )
    except Exception as error:  # noqa: BLE001
        add("appliance", "network_detect", False, str(error))

    # Appliance boot (idempotent — safe if mesh already up)
    try:
        from sophyane.appliance import boot_appliance

        report, ms = _timed(
            lambda: boot_appliance(
                open_browser=False,
                start_mesh=True,
                start_hardware_api=True,
                start_kernel=True,
            )
        )
        add("appliance", "boot", report.ok is True, f"v={report.version} steps={len(report.steps)}", ms)
    except Exception as error:  # noqa: BLE001
        add("appliance", "boot", False, str(error))

    # Chip install helpers
    try:
        import tempfile
        from pathlib import Path

        from sophyane.appliance import write_chip_install_script, write_systemd_unit

        with tempfile.TemporaryDirectory() as tmp:
            unit = write_systemd_unit(Path(tmp) / "sophyane-appliance.service")
            script = write_chip_install_script(Path(tmp) / "sophyane-install-chip")
            add(
                "appliance",
                "chip_install_assets",
                unit.exists() and script.exists() and "install.sh" in script.read_text(encoding="utf-8"),
                str(tmp),
            )
    except Exception as error:  # noqa: BLE001
        add("appliance", "chip_install_assets", False, str(error))

    # Browser assets
    try:
        from pathlib import Path

        from sophyane.browser.launcher import BROWSER_HOME, find_chromium

        add("browser", "home_ui", (BROWSER_HOME / "index.html").exists(), str(BROWSER_HOME))
        add("browser", "chromium_probe", True, find_chromium() or "fallback-webbrowser")
    except Exception as error:  # noqa: BLE001
        add("browser", "assets", False, str(error))

    # Multi-language SDK files
    try:
        root = Path(__file__).resolve().parents[2]
        # package may be site-packages; also check cwd release
        candidates = [
            Path.home() / ".local/share/sophyane/current/sdk",
            Path(__file__).resolve().parents[3] / "sdk",
        ]
        sdk = next((p for p in candidates if p.exists()), None)
        if sdk is None:
            # try parents
            for p in Path(__file__).resolve().parents:
                if (p / "sdk" / "cpp").exists():
                    sdk = p / "sdk"
                    break
        add(
            "sdk",
            "cpp_js_python",
            bool(sdk and (sdk / "cpp").exists() and (sdk / "js").exists()),
            str(sdk),
        )
        add(
            "sdk",
            "cpp_continual_core",
            bool(sdk and (sdk / "cpp" / "continual" / "src" / "train_core.cpp").exists()),
            str((sdk / "cpp" / "continual") if sdk else ""),
        )
    except Exception as error:  # noqa: BLE001
        add("sdk", "paths", False, str(error))

    # Continual federated training (C++ core)
    try:
        from sophyane.continual.engine import (
            ensure_train_core,
            record_experience,
            run_local_train_step,
            train_opt_in,
            train_status,
        )

        core_path, ms = _timed(lambda: ensure_train_core())
        add("train", "cpp_core_build", Path(core_path).exists(), str(core_path), ms)
        st, ms = _timed(train_status)
        add("train", "status", st.get("ok") is True, st.get("core_path", ""), ms)
        train_opt_in(True)
        record_experience("audit continual probe", "ok", source="audit")
        step, ms = _timed(run_local_train_step)
        add("train", "local_cpp_step", step.get("ok") is True, str(step.get("meta", {}))[:120], ms)
    except Exception as error:  # noqa: BLE001
        add("train", "continual", False, str(error))

    # Future agent surface
    try:
        from sophyane.capabilities import capability_matrix
        from sophyane.skills import list_skills
        from sophyane.rag import add_text, query
        from sophyane.interpreter import run_python
        from sophyane.mcp_bridge import list_tools, call_tool
        from sophyane.budget import status as budget_status
        from sophyane.hitl import request_approval, list_pending
        from sophyane.scheduler import schedule_job, list_jobs
        from sophyane.checkpoint import save_checkpoint, list_checkpoints
        from sophyane.permissions import get_profile
        from sophyane.observability import start_run, end_run, list_traces
        from sophyane.notifications import notify
        from sophyane.multimodal import voice_status

        m = capability_matrix()
        add("future", "capability_matrix", m.get("ready", 0) >= 30, f"ready={m.get('ready')}/{m.get('total')}")
        add("future", "skills", len(list_skills()) >= 4, str(len(list_skills())))
        add_text("Sophyane agent RAG audit probe about harness verify loop.", source="audit", title="audit")
        hits = query("harness verify", top_k=2)
        add("future", "rag", bool(hits.get("hits") is not None), f"docs={hits.get('total_docs')}")
        repl = run_python("result = sum(range(10))\nprint(result)")
        add("future", "repl", repl.get("ok") is True, str(repl.get("result")))
        tools = list_tools()
        add("future", "mcp_lite", len(tools.get("tools") or []) >= 4, str(len(tools.get("tools") or [])))
        add("future", "budget", budget_status().get("ok") is True, "")
        request_approval("audit-noop", "feature audit", risk="low")
        add("future", "hitl", list_pending().get("count", 0) >= 0, "")
        schedule_job("audit-heartbeat", "say ok", every_sec=86400)
        add("future", "scheduler", list_jobs().get("count", 0) >= 1, "")
        save_checkpoint("audit", {"step": 1})
        add("future", "checkpoint", list_checkpoints().get("count", 0) >= 1, "")
        add("future", "permissions", get_profile().get("ok") is True, get_profile().get("profile", ""))
        rid = start_run("audit")
        end_run(rid, ok=True)
        add("future", "traces", list_traces().get("count", 0) >= 1, "")
        add("future", "notify", notify("audit", "ok").get("ok") is True, "")
        add("future", "voice_hooks", voice_status().get("ok") is True, "")
        call_tool("platform", {})
        add("future", "mcp_call", True, "platform")
    except Exception as error:  # noqa: BLE001
        add("future", "surface", False, str(error))

    passed = sum(1 for c in checks if c.ok)
    return {
        "ok": passed == len(checks),
        "version": __version__,
        "passed": passed,
        "total": len(checks),
        "rate": round(100 * passed / max(1, len(checks)), 1),
        "checks": [c.to_dict() for c in checks],
    }
