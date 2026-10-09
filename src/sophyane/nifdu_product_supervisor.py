from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


_REPORT_RE = re.compile(
    r"^\s*Report\s*:\s*(.+?)\s*$",
    re.MULTILINE,
)


def _home() -> Path:
    return Path(os.environ.get("HOME", "~")).expanduser()


def _nifdu_binary() -> Path:
    return _home() / ".local" / "bin" / "nifdu-bin"


def _browser_bridge() -> Path:
    configured = os.environ.get("NIFDU_BROWSER_BRIDGE", "").strip()

    if configured:
        return Path(configured).expanduser()

    return _home() / "nifdu" / "tools" / "nifdu_browser_bridge.py"


def _report_from_output(output: str) -> Path:
    match = _REPORT_RE.search(output)

    if not match:
        raise RuntimeError(
            "NIFDU did not report its final-report.json path"
        )

    return Path(match.group(1).strip()).expanduser()


def _validate_report(
    report_file: Path,
) -> dict[str, Any]:
    home = _home().resolve()
    workspace_root = (
        home / "nifdu-workspaces"
    ).resolve()

    report_file = report_file.resolve()

    try:
        report_file.relative_to(workspace_root)
    except ValueError as exc:
        raise RuntimeError(
            "NIFDU report is outside the NIFDU workspace root"
        ) from exc

    if report_file.name != "final-report.json":
        raise RuntimeError(
            "NIFDU reported an unexpected report filename"
        )

    if not report_file.is_file():
        raise RuntimeError(
            f"NIFDU final report does not exist: {report_file}"
        )

    try:
        report = json.loads(
            report_file.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "NIFDU final report is unreadable or invalid JSON"
        ) from exc

    if not isinstance(report, dict):
        raise RuntimeError(
            "NIFDU final report must be a JSON object"
        )

    final_file_raw = report.get("final_file")

    if not isinstance(final_file_raw, str) or not final_file_raw.strip():
        raise RuntimeError(
            "NIFDU final report has no valid final_file"
        )

    final_file = Path(
        final_file_raw
    ).expanduser().resolve()

    workspace = report_file.parent.resolve()

    try:
        final_file.relative_to(workspace)
    except ValueError as exc:
        raise RuntimeError(
            "NIFDU final product is outside its reported workspace"
        ) from exc

    expected_product = (
        workspace / "product" / "index.html"
    ).resolve()

    if final_file != expected_product:
        raise RuntimeError(
            "NIFDU final product is not the workspace product/index.html"
        )

    if not final_file.is_file():
        raise RuntimeError(
            f"NIFDU final product does not exist: {final_file}"
        )

    html = final_file.read_text(
        encoding="utf-8"
    )

    lowered = html.lower()

    if (
        "<html" not in lowered
        and "<!doctype html" not in lowered
    ):
        raise RuntimeError(
            "NIFDU final product is not a valid HTML document"
        )

    result = dict(report)
    result["final_file"] = final_file
    result["report_file"] = report_file
    result["workspace"] = workspace

    return result


def run_nifdu_product_cycle(
    requirement: str,
) -> dict[str, Any]:
    requirement = str(requirement or "").strip()

    if not requirement:
        raise ValueError(
            "NIFDU product requirement must not be empty"
        )

    nifdu_bin = _nifdu_binary()

    if not nifdu_bin.is_file():
        raise RuntimeError(
            f"NIFDU executable unavailable: {nifdu_bin}"
        )

    if not os.access(nifdu_bin, os.X_OK):
        raise RuntimeError(
            f"NIFDU executable is not executable: {nifdu_bin}"
        )

    bridge = _browser_bridge()

    if not bridge.is_file():
        raise RuntimeError(
            f"NIFDU browser bridge unavailable: {bridge}"
        )

    child_env = os.environ.copy()

    binding_root = (
        _home() / ".cache" / "sophyane"
    )
    binding_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    binding_fd, binding_name = tempfile.mkstemp(
        prefix="nifdu-target-",
        suffix=".json",
        dir=binding_root,
    )
    os.close(binding_fd)

    binding_file = Path(binding_name)

    # Absence, rather than an empty JSON document, is the clean first-use
    # state understood by the browser bridge.
    try:
        binding_file.unlink()
    except FileNotFoundError:
        pass

    child_env.update(
        {
            "NIFDU_BUILDER_PROVIDER": "browser_chatgpt",
            "NIFDU_BUILDER_MODEL": "chatgpt-browser",
            "NIFDU_JUDGE_PROVIDER": "browser_chatgpt",
            "NIFDU_JUDGE_MODEL": "chatgpt-browser",
            "NIFDU_BROWSER_BRIDGE": str(bridge),
            "NIFDU_TARGET_BINDING_FILE": str(binding_file),
            "NIFDU_BROWSER_PYTHON": child_env.get(
                "NIFDU_BROWSER_PYTHON",
                "python",
            ),
            "NIFDU_CDP_HOST": child_env.get(
                "NIFDU_CDP_HOST",
                "127.0.0.1",
            ),
            "NIFDU_CDP_PORT": child_env.get(
                "NIFDU_CDP_PORT",
                "9222",
            ),
        }
    )

    completed = subprocess.run(
        [
            str(nifdu_bin),
            "build",
            requirement,
        ],
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        env=child_env,
    )

    combined_output = (
        (completed.stdout or "")
        + "\n"
        + (completed.stderr or "")
    )

    report_file = _report_from_output(
        combined_output
    )

    result = _validate_report(
        report_file
    )

    result["returncode"] = completed.returncode
    result["stdout"] = completed.stdout or ""
    result["stderr"] = completed.stderr or ""

    # NIFDU deliberately returns failure when its complete
    # quality loop expires without acceptance. Preserve that
    # result for Sophyane instead of hiding the judge outcome.
    if completed.returncode != 0 and result.get("accepted") is True:
        raise RuntimeError(
            "NIFDU exited unsuccessfully despite reporting acceptance"
        )

    return result
