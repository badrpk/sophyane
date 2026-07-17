"""Sophyane v16 CLI: repository-aware coding execution by default."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from sophyane.agent import SophyaneAgent
from sophyane.autonomy import AUTONOMOUS_WORKER_POLICY
from sophyane.config import ensure_directories
from sophyane.diagnostics import run_diagnostics
from sophyane.live_coding_doer import LiveProgressReporter
from sophyane.logging_config import configure_logging
from sophyane.main import (
    create_provider,
    handle_internal_command,
    interactive,
    list_providers,
    load_runtime_config,
    show_status,
)
from sophyane.memory import MemoryStore
from sophyane.multiagent import MultiAgentRuntime, MultiAgentStore
from sophyane.setup_wizard import run_setup_wizard
from sophyane.strict_interactive_doer import StrictInteractiveCodingDoerRuntime
from sophyane.structured_output import (
    StructuredOutputError,
    render_strict_json,
    requests_strict_json,
)
from sophyane.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sophyane",
        description=(
            "Sophyane v16 repository-aware coding agent with semantic indexing, "
            "precise patches, batched tools, self-repair and deterministic verification."
        ),
    )
    parser.add_argument("prompt", nargs="*", help="prompt to process")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--providers", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument(
        "--platform",
        action="store_true",
        help="probe OS/hardware/equipment class (Windows/macOS/Linux/Android/edge)",
    )
    parser.add_argument(
        "--edge-health",
        action="store_true",
        help="print edge/IoT health JSON for constrained chips and gateways",
    )
    parser.add_argument(
        "--hardware",
        action="store_true",
        help="print hardware vendor compatibility report (NVIDIA/Intel/AMD/…)",
    )
    parser.add_argument(
        "--hardware-json",
        action="store_true",
        help="print hardware compatibility report as JSON",
    )
    parser.add_argument(
        "--hardware-api",
        action="store_true",
        help="serve multi-language Hardware API (Python/C++/JS clients)",
    )
    parser.add_argument(
        "--hardware-host",
        default="127.0.0.1",
        help="bind host for --hardware-api (default 127.0.0.1)",
    )
    parser.add_argument(
        "--hardware-port",
        type=int,
        default=8770,
        help="bind port for --hardware-api (default 8770)",
    )
    parser.add_argument(
        "--kernel",
        action="store_true",
        help="boot Sophyane AI Kernel and print status JSON",
    )
    parser.add_argument(
        "--kernel-status",
        action="store_true",
        help="print AI Kernel status without full reboot noise",
    )
    parser.add_argument(
        "--create-app",
        metavar="TARGET",
        help="create app scaffold: web|android|harmony|ios|desktop_python|api_python",
    )
    parser.add_argument(
        "--app-name",
        default="SophyaneApp",
        help="application name for --create-app",
    )
    parser.add_argument(
        "--app-out",
        default="",
        help="output directory for --create-app",
    )
    parser.add_argument(
        "--erp",
        metavar="SYSTEM",
        nargs="?",
        const="all",
        help="probe ERP connectors (oracle|sap|odoo|dynamics|netsuite|erpnext|all)",
    )
    parser.add_argument(
        "--mesh-serve",
        action="store_true",
        help="serve Sophyane mesh peer API (WiFi/LAN control + shared storage/compute)",
    )
    parser.add_argument(
        "--mesh-port",
        type=int,
        default=8777,
        help="mesh peer port (default 8777)",
    )
    parser.add_argument(
        "--mesh-discover",
        action="store_true",
        help="discover Sophyane peers on WiFi/LAN and USB/ADB",
    )
    parser.add_argument(
        "--mesh-status",
        action="store_true",
        help="show local mesh node status and known peers",
    )
    parser.add_argument(
        "--mesh-install",
        metavar="PEER_ID",
        help="install Sophyane clone on peer (requires --yes)",
    )
    parser.add_argument(
        "--mesh-compute",
        metavar="MESSAGE",
        help="run a short chat/compute job on the best mesh peer",
    )
    parser.add_argument(
        "--mesh-ssh-user",
        default="",
        help="SSH user for --mesh-install over LAN",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm destructive/mesh install actions",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="open Sophyane Browser (Chromium profile + home UI)",
    )
    parser.add_argument(
        "--fetch",
        metavar="URL",
        help="fetch/scrape a URL into web intel store",
    )
    parser.add_argument(
        "--learn",
        metavar="URL",
        help="scrape URL and append hash-chained self-improvement proposal",
    )
    parser.add_argument(
        "--improve-status",
        action="store_true",
        help="show self-improvement ledger tip and verification",
    )
    parser.add_argument(
        "--improve-export",
        action="store_true",
        help="export today's improvement epoch (local + repo improvements/)",
    )
    parser.add_argument(
        "--improve-propose",
        metavar="TITLE",
        help="manually propose an improvement (use with --improve-body)",
    )
    parser.add_argument(
        "--improve-body",
        default="",
        help="body text for --improve-propose",
    )
    parser.add_argument(
        "--boot",
        action="store_true",
        help="boot Sophyane appliance (network + kernel + mesh + hardware API)",
    )
    parser.add_argument(
        "--boot-foreground",
        action="store_true",
        help="with --boot, keep process alive (for systemd)",
    )
    parser.add_argument(
        "--boot-browser",
        action="store_true",
        help="with --boot, also open Sophyane Browser",
    )
    parser.add_argument(
        "--wifi-ssid",
        default="",
        help="Wi‑Fi SSID for appliance network bring-up",
    )
    parser.add_argument(
        "--wifi-psk",
        default="",
        help="Wi‑Fi password for appliance network bring-up",
    )
    parser.add_argument(
        "--install-appliance-unit",
        action="store_true",
        help="write systemd user unit for appliance auto-boot",
    )
    parser.add_argument(
        "--install-chip",
        action="store_true",
        help="write sophyane-install-chip helper for Linux SoC/boards",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="run integrated feature audit (all major subsystems)",
    )
    parser.add_argument(
        "--train-status",
        action="store_true",
        help="continual federated training status (C++ core + base GGUF)",
    )
    parser.add_argument(
        "--train-opt-in",
        action="store_true",
        help="opt this device into continuous federated PEFT training",
    )
    parser.add_argument(
        "--train-opt-out",
        action="store_true",
        help="disable federated training contribution on this device",
    )
    parser.add_argument(
        "--train-step",
        action="store_true",
        help="run one local C++ continual train step on existing LLM weights",
    )
    parser.add_argument(
        "--train-round",
        action="store_true",
        help="full federated round: local C++ step + mesh publish + FedAvg",
    )
    parser.add_argument(
        "--train-build-core",
        action="store_true",
        help="build the pure C++ sophyane-train-core binary",
    )
    parser.add_argument(
        "--train-record",
        default="",
        help="record experience text for continual training (privacy-digest by default)",
    )
    parser.add_argument(
        "--exam-tough100",
        action="store_true",
        help="run 100 tough harness/coding exam questions and score replies",
    )
    parser.add_argument(
        "--exam-mode",
        choices=["expert", "llm", "hybrid"],
        default="hybrid",
        help="tough exam answer mode (default hybrid = expert pack + LLM)",
    )
    parser.add_argument(
        "--exam-limit",
        type=int,
        default=100,
        help="limit tough exam questions (default 100)",
    )
    parser.add_argument(
        "--expert-only",
        action="store_true",
        help="with --exam-tough100, use curated expert pack only",
    )
    parser.add_argument(
        "--ask",
        default="",
        help="answer a hard harness/coding question via expert+LLM hybrid",
    )
    # Future-complete agent surface
    parser.add_argument("--capabilities", action="store_true", help="show full modern-agent capability matrix")
    parser.add_argument("--skills", action="store_true", help="list reusable agent skills")
    parser.add_argument("--skill", default="", help="apply named skill to --skill-prompt")
    parser.add_argument("--skill-prompt", default="", help="user prompt for --skill")
    parser.add_argument("--rag-add", default="", help="ingest a file into local RAG index")
    parser.add_argument("--rag-query", default="", help="query local RAG knowledge base")
    parser.add_argument("--rag-status", action="store_true", help="RAG index status")
    parser.add_argument("--schedule", default="", help="schedule job name (with --schedule-prompt)")
    parser.add_argument("--schedule-prompt", default="", help="prompt for scheduled job")
    parser.add_argument("--schedule-every", type=int, default=3600, help="seconds between scheduled runs")
    parser.add_argument("--schedule-list", action="store_true", help="list scheduled jobs")
    parser.add_argument("--schedule-run", action="store_true", help="run due scheduled jobs now")
    parser.add_argument("--budget-status", action="store_true", help="token/cost budget status")
    parser.add_argument("--budget-reset", action="store_true", help="reset budget usage counters")
    parser.add_argument("--hitl-list", action="store_true", help="list pending human approvals")
    parser.add_argument("--approve", default="", help="approve HITL request id")
    parser.add_argument("--deny", default="", help="deny HITL request id")
    parser.add_argument("--hitl-request", default="", help="create HITL approval request for action")
    parser.add_argument("--trace-list", action="store_true", help="list observability run traces")
    parser.add_argument("--repl", default="", help="run sandboxed Python (code string)")
    parser.add_argument("--eval", default="", help="alias for --repl")
    parser.add_argument("--mcp-list", action="store_true", help="list MCP-lite tools")
    parser.add_argument("--mcp-call", default="", help="call MCP-lite tool by name")
    parser.add_argument("--mcp-args", default="{}", help="JSON args for --mcp-call")
    parser.add_argument("--permissions", default="", help="set permission profile: readonly|workspace|network|strict|full")
    parser.add_argument("--permissions-status", action="store_true", help="show permission profile")
    parser.add_argument("--checkpoint-list", action="store_true", help="list task checkpoints")
    parser.add_argument("--notify-test", action="store_true", help="send a test notification")
    parser.add_argument("--voice-status", action="store_true", help="voice STT/TTS capability status")
    parser.add_argument("--image", default="", help="describe an image path (multimodal hook)")
    parser.add_argument("--cloud-serve", action="store_true", help="serve Sophyane public website + token API")
    parser.add_argument("--cloud-host", default="0.0.0.0", help="cloud portal bind host")
    parser.add_argument("--cloud-port", type=int, default=8780, help="cloud portal port (default 8780)")
    parser.add_argument("--namecheap-domains", action="store_true", help="list Namecheap domains (needs API env)")
    parser.add_argument("--namecheap-longest", action="store_true", help="pick domain with longest expiry")
    parser.add_argument(
        "--namecheap-setup-site",
        action="store_true",
        help="point longest-expiry domain A/AAAA records at STATIC_IPV4/IPV6",
    )
    parser.add_argument("--namecheap-domain", default="", help="force domain for --namecheap-setup-site")
    parser.add_argument("--static-ipv4", default="", help="public static IPv4 for DNS A records")
    parser.add_argument("--static-ipv6", default="", help="optional static IPv6 for AAAA records")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--single-agent", action="store_true", help="use legacy one-worker runtime")
    parser.add_argument("--multi-agent", action="store_true", help="use legacy supervisor-worker runtime")
    parser.add_argument("--agent-json", action="store_true", help="print complete machine-readable run metadata")
    parser.add_argument("--inspect-run", metavar="RUN_ID", help="inspect a persisted legacy multi-agent run")
    parser.add_argument("--max-workers", type=int, default=6, help="maximum legacy concurrent workers")
    parser.add_argument("--agent-attempts", type=int, default=2, help="attempts per legacy worker")
    parser.add_argument("--max-steps", type=int, default=16, help="maximum planner-executor-verifier cycles")
    parser.add_argument(
        "--workspace",
        default=".",
        help="repository or directory in which approved edits and commands execute",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="disable live operational progress messages",
    )
    parser.add_argument(
        "--progress-heartbeat",
        type=float,
        default=5.0,
        help="seconds between progress heartbeats during slow provider calls",
    )
    parser.add_argument(
        "--protocol-attempts",
        type=int,
        default=3,
        help="maximum strict JSON regeneration attempts for malformed planner output",
    )
    parser.add_argument(
        "--approval-timeout",
        type=float,
        default=10.0,
        help="seconds before safe scoped actions auto-continue (legacy runtime)",
    )
    parser.add_argument(
        "--no-auto-continue",
        action="store_true",
        help="disable timeout auto-continuation for legacy safe actions",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _execution_policy(timeout: float, enabled: bool) -> str:
    if not enabled:
        return (
            AUTONOMOUS_WORKER_POLICY
            + "\nTimeout auto-continuation is disabled for this invocation; "
            "safe actions still require an explicit response."
        )
    return AUTONOMOUS_WORKER_POLICY.replace("10 seconds", f"{max(0.0, timeout):g} seconds")


def main() -> int:
    ensure_directories()
    parser = build_parser()
    args = parser.parse_args()
    logger = configure_logging(args.verbose)

    if args.single_agent and args.multi_agent:
        parser.error("--single-agent and --multi-agent cannot be used together")

    store = MultiAgentStore()
    if args.inspect_run:
        run = store.inspect_run(args.inspect_run)
        if run is None:
            print(json.dumps({"status": "not_found", "run_id": args.inspect_run}))
            return 1
        print(json.dumps(run, indent=2, ensure_ascii=False))
        return 0

    if args.doctor:
        passed, report = run_diagnostics()
        print(report)
        return 0 if passed else 1
    if args.platform:
        from sophyane.platform_probe import format_platform_report

        print(format_platform_report())
        return 0
    if args.edge_health:
        from sophyane.config import load_config
        from sophyane.edge_agent import build_edge_health

        cfg = load_config()
        health = build_edge_health(
            provider=str(cfg.get("provider", "")),
            model=str(cfg.get("model", "")),
        )
        print(health.to_json())
        return 0 if health.ok else 1
    if args.hardware or args.hardware_json:
        from sophyane.hardware_registry import (
            format_hardware_report,
            hardware_compatibility_report,
        )

        if args.hardware_json:
            print(json.dumps(hardware_compatibility_report(), indent=2))
        else:
            print(format_hardware_report())
        return 0
    if args.hardware_api:
        from sophyane.hardware_api import create_default_api, serve_hardware_api

        api = create_default_api()
        server = serve_hardware_api(
            host=str(args.hardware_host),
            port=int(args.hardware_port),
            api=api,
        )
        print(
            f"Sophyane Hardware API listening on "
            f"http://{args.hardware_host}:{args.hardware_port} "
            f"(Python/C++/JS clients)",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nHardware API stopped.")
        return 0
    if args.kernel or args.kernel_status:
        from sophyane.kernel import boot_kernel, kernel_status

        status = boot_kernel().status() if args.kernel else kernel_status()
        print(status.to_json())
        return 0 if status.ok else 1
    if args.create_app:
        from sophyane.kernel import boot_kernel

        kernel = boot_kernel()
        result = kernel.create_application(
            str(args.create_app),
            str(args.app_name),
            output_dir=str(args.app_out) or None,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.erp is not None:
        from sophyane.kernel import boot_kernel

        kernel = boot_kernel()
        system = None if args.erp in {"", "all"} else str(args.erp)
        print(json.dumps(kernel.erp_status(system), indent=2))
        return 0
    if args.audit:
        from sophyane.feature_audit import run_full_audit

        report = run_full_audit()
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 1

    if args.capabilities:
        from sophyane.capabilities import capability_matrix, format_capability_report

        if args.agent_json:
            print(json.dumps(capability_matrix(), indent=2))
        else:
            print(format_capability_report())
        return 0

    if args.skills:
        from sophyane.skills import list_skills

        print(json.dumps({"ok": True, "skills": list_skills()}, indent=2))
        return 0
    if args.skill:
        from sophyane.skills import apply_skill_prompt

        print(json.dumps(apply_skill_prompt(str(args.skill), str(args.skill_prompt or args.ask or "help")), indent=2))
        return 0

    if args.rag_status:
        from sophyane.rag import status as rag_status

        print(json.dumps(rag_status(), indent=2))
        return 0
    if args.rag_add:
        from sophyane.rag import add_document

        print(json.dumps(add_document(str(args.rag_add)), indent=2))
        return 0
    if args.rag_query:
        from sophyane.rag import query as rag_query

        print(json.dumps(rag_query(str(args.rag_query)), indent=2))
        return 0

    if args.schedule_list:
        from sophyane.scheduler import list_jobs

        print(json.dumps(list_jobs(), indent=2))
        return 0
    if args.schedule_run:
        from sophyane.scheduler import run_due

        print(json.dumps(run_due(execute=True), indent=2))
        return 0
    if args.schedule:
        from sophyane.scheduler import schedule_job

        print(
            json.dumps(
                schedule_job(
                    str(args.schedule),
                    str(args.schedule_prompt or "heartbeat"),
                    every_sec=int(args.schedule_every),
                ),
                indent=2,
            )
        )
        return 0

    if args.budget_reset:
        from sophyane.budget import reset_usage

        print(json.dumps(reset_usage(), indent=2))
        return 0
    if args.budget_status:
        from sophyane.budget import status as budget_status

        print(json.dumps(budget_status(), indent=2))
        return 0

    if args.hitl_list:
        from sophyane.hitl import list_pending

        print(json.dumps(list_pending(), indent=2))
        return 0
    if args.hitl_request:
        from sophyane.hitl import request_approval

        print(json.dumps(request_approval(str(args.hitl_request), detail=str(args.skill_prompt or "")), indent=2))
        return 0
    if args.approve:
        from sophyane.hitl import resolve

        print(json.dumps(resolve(str(args.approve), approve=True), indent=2))
        return 0
    if args.deny:
        from sophyane.hitl import resolve

        print(json.dumps(resolve(str(args.deny), approve=False), indent=2))
        return 0

    if args.trace_list:
        from sophyane.observability import list_traces

        print(json.dumps(list_traces(), indent=2))
        return 0

    if args.repl or args.eval:
        from sophyane.interpreter import run_python

        print(json.dumps(run_python(str(args.repl or args.eval)), indent=2))
        return 0

    if args.mcp_list:
        from sophyane.mcp_bridge import list_tools

        print(json.dumps(list_tools(), indent=2))
        return 0
    if args.mcp_call:
        from sophyane.mcp_bridge import call_tool

        try:
            params = json.loads(args.mcp_args or "{}")
        except json.JSONDecodeError:
            params = {}
        print(json.dumps(call_tool(str(args.mcp_call), params if isinstance(params, dict) else {}), indent=2))
        return 0

    if args.permissions_status:
        from sophyane.permissions import get_profile

        print(json.dumps(get_profile(), indent=2))
        return 0
    if args.permissions:
        from sophyane.permissions import set_profile

        print(json.dumps(set_profile(str(args.permissions)), indent=2))
        return 0

    if args.checkpoint_list:
        from sophyane.checkpoint import list_checkpoints

        print(json.dumps(list_checkpoints(), indent=2))
        return 0

    if args.notify_test:
        from sophyane.notifications import notify

        print(json.dumps(notify("Sophyane ready", "Notification channel test"), indent=2))
        return 0

    if args.voice_status:
        from sophyane.multimodal import voice_status

        print(json.dumps(voice_status(), indent=2))
        return 0
    if args.image:
        from sophyane.multimodal import describe_image

        print(json.dumps(describe_image(str(args.image)), indent=2))
        return 0

    if args.namecheap_domains or args.namecheap_longest or args.namecheap_setup_site:
        from sophyane.cloud.namecheap import NamecheapClient

        try:
            client = NamecheapClient()
        except Exception as error:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": str(error)}, indent=2))
            return 1
        if args.namecheap_domains:
            print(json.dumps({"ok": True, "domains": client.list_domains()}, indent=2))
            return 0
        if args.namecheap_longest:
            best = client.longest_expiry_domain()
            print(json.dumps({"ok": bool(best), "domain": best}, indent=2))
            return 0 if best else 1
        ipv4 = str(args.static_ipv4 or os.environ.get("STATIC_IPV4") or "").strip()
        ipv6 = str(args.static_ipv6 or os.environ.get("STATIC_IPV6") or "").strip()
        if not ipv4:
            print(json.dumps({"ok": False, "error": "STATIC_IPV4 / --static-ipv4 required"}, indent=2))
            return 1
        result = client.setup_sophyane_site(
            ipv4=ipv4,
            ipv6=ipv6,
            prefer_domain=str(args.namecheap_domain or ""),
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    if args.cloud_serve:
        from sophyane.cloud.portal import serve_portal

        host = str(args.cloud_host)
        port = int(args.cloud_port)
        server = serve_portal(host, port)
        base = f"http://{host}:{port}"
        print(
            json.dumps(
                {
                    "ok": True,
                    "url": f"{base}/",
                    "start_guide": f"{base}/start.html",
                    "login_signup": f"{base}/get-api.html",
                    "onboarding_api": f"{base}/api/v1/onboarding",
                    "api": f"{base}/api/v1/health",
                    "auth": "email_otp_from_badrpk@gmail.com",
                    "message": (
                        "Sophyane Cloud portal serving. "
                        "Users should open /start.html first for OTP login, pricing, install, and ports. "
                        "Reverse-proxy with Caddy/nginx for your domain."
                    ),
                },
                indent=2,
            ),
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nCloud portal stopped.")
        return 0

    if args.ask:
        from sophyane.expert.answer import answer_tough_question

        generate = None
        try:
            from sophyane.config import load_config

            provider = create_provider(load_config())

            def generate(prompt: str, system: str) -> str:
                return provider.generate(prompt, system)
        except Exception:  # noqa: BLE001
            generate = None
        result = answer_tough_question(
            str(args.ask),
            generate=generate,
            mode="hybrid" if generate else "expert",
        )
        print(result["answer"])
        return 0

    if args.exam_tough100:
        from sophyane.expert.exam import run_exam

        report = run_exam(
            mode="expert" if args.expert_only else str(args.exam_mode),
            limit=int(args.exam_limit),
            with_llm=not args.expert_only and args.exam_mode != "expert",
        )
        summary = {
            k: report[k]
            for k in (
                "ok",
                "version",
                "mode",
                "total",
                "passed",
                "pass_rate",
                "avg_score",
                "elapsed_sec",
                "by_category",
                "failures",
            )
        }
        print(json.dumps(summary, indent=2))
        return 0 if float(report.get("pass_rate") or 0) >= 80 else 1

    if args.train_build_core:
        from sophyane.continual.engine import ensure_train_core

        path = ensure_train_core(force_rebuild=True)
        print(json.dumps({"ok": True, "core": str(path), "language": "C++17"}, indent=2))
        return 0
    if args.train_opt_in or args.train_opt_out:
        from sophyane.continual.engine import train_opt_in

        print(json.dumps(train_opt_in(enabled=bool(args.train_opt_in)), indent=2))
        return 0
    if args.train_record:
        from sophyane.continual.engine import record_experience

        print(json.dumps(record_experience(str(args.train_record), source="cli"), indent=2))
        return 0
    if args.train_status:
        from sophyane.continual.engine import train_status

        st = train_status()
        print(json.dumps(st, indent=2))
        return 0 if st.get("ok") else 1
    if args.train_step:
        from sophyane.continual.engine import run_local_train_step, train_opt_in

        if not __import__("sophyane.continual.engine", fromlist=["is_opted_in"]).is_opted_in():
            train_opt_in(True)
        result = run_local_train_step()
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.train_round:
        from sophyane.continual.engine import contribute_round, is_opted_in, train_opt_in

        if not is_opted_in():
            train_opt_in(True)
        result = contribute_round(publish_mesh=True)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    if args.install_appliance_unit:
        from sophyane.appliance import write_systemd_unit

        path = write_systemd_unit()
        print(json.dumps({"ok": True, "unit": str(path)}, indent=2))
        return 0

    if args.install_chip:
        from sophyane.appliance import write_chip_install_script

        path = write_chip_install_script()
        print(json.dumps({"ok": True, "script": str(path)}, indent=2))
        return 0

    if args.boot:
        from sophyane.appliance import boot_appliance

        report = boot_appliance(
            wifi_ssid=str(args.wifi_ssid or "") or None,
            wifi_psk=str(args.wifi_psk or "") or None,
            open_browser=bool(args.boot_browser),
            start_mesh=True,
            start_hardware_api=True,
            start_kernel=True,
        )
        print(json.dumps(report.to_dict(), indent=2))
        # Stay up so mesh/hardware API threads remain alive (OS-like appliance).
        # Use SOPHYANE_BOOT_ONCE=1 for one-shot boot reports in scripts/tests.
        if os.environ.get("SOPHYANE_BOOT_ONCE", "").lower() not in {"1", "true", "yes"}:
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                print("\nSophyane appliance stopped.")
        return 0 if report.ok else 1

    if args.browser:
        from sophyane.browser import launch_sophyane_browser

        result = launch_sophyane_browser(open_home=True, start_apis=True)
        print(json.dumps(result, indent=2))
        # Keep process alive while local home server runs if chromium missing
        if not result.get("pid"):
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                print("\nSophyane Browser home stopped.")
        return 0

    if args.fetch:
        from sophyane.web_intel import fetch_url

        print(json.dumps(fetch_url(str(args.fetch)).to_dict(), indent=2)[:8000])
        return 0

    if args.learn:
        from sophyane.self_improve.ledger import auto_propose_from_scrape
        from sophyane.web_intel import scrape_for_improvement

        bundle = scrape_for_improvement([str(args.learn)])
        props = auto_propose_from_scrape(bundle)
        print(json.dumps({"scrape": bundle, "proposals": props}, indent=2)[:12000])
        return 0

    if args.improve_status:
        from sophyane.self_improve.ledger import chain_tip, list_proposals, verify_chain

        print(
            json.dumps(
                {
                    "tip": chain_tip(),
                    "verify": verify_chain(),
                    "recent": list_proposals(15),
                },
                indent=2,
            )
        )
        return 0

    if args.improve_export:
        from sophyane.self_improve.ledger import export_daily_epoch

        print(json.dumps(export_daily_epoch(), indent=2)[:12000])
        return 0

    if args.improve_propose:
        from sophyane.self_improve.ledger import propose_improvement

        result = propose_improvement(
            "manual",
            str(args.improve_propose),
            str(args.improve_body or args.improve_propose),
            score=0.5,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.mesh_serve or args.mesh_discover or args.mesh_status or args.mesh_install or args.mesh_compute:
        from sophyane.mesh.core import get_mesh_node
        from sophyane.mesh.discovery import MESH_PORT

        port = int(args.mesh_port or MESH_PORT)
        node = get_mesh_node(port=port)

        if args.mesh_serve:
            server = node.serve(host="0.0.0.0")
            print(
                f"Sophyane mesh peer {node.peer_id} listening on 0.0.0.0:{port}\n"
                f"Hello: http://<this-host>:{port}/v1/mesh/hello\n"
                f"Share dir: ~/.local/state/sophyane/mesh_share\n"
                f"Optional auth: SOPHYANE_MESH_TOKEN",
                flush=True,
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nMesh peer stopped.")
            return 0

        if args.mesh_discover:
            peers = node.discover(include_usb=True)
            print(json.dumps({"ok": True, "count": len(peers), "peers": peers}, indent=2))
            return 0

        if args.mesh_status:
            print(json.dumps(node.status(), indent=2))
            return 0

        if args.mesh_install:
            result = node.install_peer(
                str(args.mesh_install),
                yes=bool(args.yes),
                ssh_user=str(args.mesh_ssh_user or ""),
            )
            print(json.dumps(result, indent=2))
            return 0 if result.get("ok") else 1

        if args.mesh_compute:
            # ensure we know some peers
            if not node.peers:
                node.discover(include_usb=False)
            result = node.use_peer_compute(str(args.mesh_compute))
            print(json.dumps(result, indent=2))
            return 0 if result.get("ok") else 1

    if args.providers:
        print(list_providers())
        return 0

    config = run_setup_wizard() if args.setup else load_runtime_config()
    if args.status:
        print(show_status(config))
        return 0
    if not args.prompt:
        # Grok-style full interactive CLI (slash commands, spinner, auto-local).
        return interactive(config, args.verbose)

    original_prompt = " ".join(args.prompt)
    memory = MemoryStore()
    provider = create_provider(config)

    agent = SophyaneAgent(provider, memory, logger)
    if original_prompt.startswith("/"):
        response = agent.ask(original_prompt)
        if response.text.startswith("INTERNAL_COMMAND:"):
            command = response.text.split(":", 1)[1]
            text, _ = handle_internal_command(command, config)
            print(text)
        else:
            print(response.text)
        return 0

    # Small local models (GGUF / tiny Ollama) cannot run the full repository coding
    # planner prompt (often 5k–20k tokens). Route conversational prompts through
    # the lightweight chat agent instead of the strict coding doer.
    provider_id = str(config.get("provider") or "").lower()
    lower_prompt = original_prompt.lower()
    coding_markers = (
        "implement",
        "refactor",
        "apply patch",
        "write a function",
        "write a class",
        "create a file",
        "edit the file",
        "pytest",
        "unit test",
        "test suite",
        "debug this",
        "repository",
        "codebase",
        "pull request",
        "git commit",
    )
    looks_like_coding = any(token in lower_prompt for token in coding_markers)
    force_chat = provider_id in {"local_gguf", "ollama"} and not looks_like_coding
    if not force_chat and len(original_prompt) < 240:
        stripped = lower_prompt.strip()
        if stripped.endswith("?") or stripped.startswith(
            ("hi", "hello", "hey", "say ", "what ", "who ", "how ", "why ", "thanks")
        ):
            force_chat = True

    if force_chat and not args.single_agent and not args.multi_agent:
        response = agent.ask(original_prompt)
        print(response.text)
        return 0 if response.text else 2

    def backend(prompt: str, system: str) -> str:
        return provider.generate(prompt, system)

    if args.single_agent or args.multi_agent:
        mode = "multi" if args.multi_agent else "single"
        policy = _execution_policy(args.approval_timeout, not args.no_auto_continue)

        def legacy_backend(prompt: str, system: str) -> str:
            return provider.generate(prompt, (system + "\n\n" + policy).strip())

        runtime = MultiAgentRuntime(
            backend=legacy_backend,
            store=store,
            max_workers=args.max_workers,
            max_attempts=args.agent_attempts,
        )
        result = runtime.run(original_prompt, mode=mode)
        if args.agent_json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(result.final_output)
        return 0 if result.final_output else 2

    progress = LiveProgressReporter(
        enabled=not args.no_progress,
        heartbeat_seconds=args.progress_heartbeat,
    )
    runtime = StrictInteractiveCodingDoerRuntime(
        backend=backend,
        memory=memory,
        workspace=Path(args.workspace),
        max_steps=args.max_steps,
        protocol_attempts=args.protocol_attempts,
        progress=progress,
    )
    result = runtime.run(original_prompt)

    if args.agent_json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0 if result.goal_met else 2

    if requests_strict_json(original_prompt):
        try:
            print(render_strict_json(original_prompt, result.final_output))
            return 0 if result.goal_met else 2
        except StructuredOutputError as error:
            logger.error("Strict JSON contract failed: %s", error)
            print('{"status":"failed","error":"strict_json_contract"}')
            return 2

    repository = result.execution.get("repository", {})
    files = repository.get("files", []) if isinstance(repository, dict) else []
    print(
        f"EXECUTION_MODE=repository_coding_agent\n"
        f"RUN_ID={result.run_id}\n"
        f"GOAL_MET={'true' if result.goal_met else 'false'}\n"
        f"LOOP_STEPS={len(result.steps)}\n"
        f"STOPPED_REASON={result.stopped_reason}\n"
        f"INDEXED_FILES={len(files)}\n"
        f"WORKSPACE={result.execution.get('workspace', str(Path(args.workspace).resolve()))}"
    )
    print()
    print(result.final_output)
    return 0 if result.goal_met else 2


if __name__ == "__main__":
    raise SystemExit(main())
