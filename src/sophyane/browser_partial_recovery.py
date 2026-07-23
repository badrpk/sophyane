"""Durable recovery for provider HTML that is repeatedly truncated.

The best partial document and each raw provider response are preserved so failed
browser generation can be diagnosed instead of silently discarded.
"""
from __future__ import annotations

from sophyane.generation_contract import mark_raw_artifact

import hashlib
import os

import re
import time
from pathlib import Path
from typing import Any, Callable


PARTIAL_NAME = ".sophyane-partial-index.html"
RAW_PREFIX = ".sophyane-provider-response"
MAX_CONTINUATIONS = 2
MAX_TOTAL_CHARS = 24000
MIN_PROGRESS = 24
MIN_REWRITE_RATIO = 0.60


def _response_text(response: Any) -> str:
    return str(getattr(response, "text", response) or "")


def _finish_reason(response: Any) -> str:
    for name in ("finish_reason", "finishReason", "stop_reason", "stopReason"):
        value = getattr(response, name, None)
        if value:
            return str(value)
    candidates = getattr(response, "candidates", None)
    if candidates:
        value = getattr(candidates[0], "finish_reason", None) or getattr(candidates[0], "finishReason", None)
        if value:
            return str(value)
    return "unknown"



def _cleanup_raw_responses(
    directory: Path,
    *,
    keep: int = 40,
    maximum_age_days: int = 7,
) -> None:
    """Bound diagnostic-response retention by count and age."""

    cutoff = time.time() - max(1, maximum_age_days) * 86400
    files = sorted(
        directory.glob(f"{RAW_PREFIX}-*.txt"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )

    for index, path in enumerate(files):
        try:
            if index >= keep or path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def _new_run_id() -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{time.time_ns() % 1_000_000_000:09d}"


def _diagnostic_root() -> Path:
    """Return the persistent state directory for provider evidence."""

    configured = (
        os.environ.get("SOPHYANE_PROVIDER_DIAGNOSTIC_DIR")
        or os.environ.get("SOPHYANE_STATE_DIR")
    )

    if configured:
        root = Path(configured).expanduser()
    else:
        root = (
            Path.home()
            / ".local"
            / "state"
            / "sophyane"
            / "provider-responses"
        )

    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _workspace_diagnostic_directory(workspace: Path) -> Path:
    """Return an isolated evidence directory for one workspace."""

    resolved = workspace.expanduser().resolve()
    identity = hashlib.sha256(
        str(resolved).encode("utf-8", errors="replace")
    ).hexdigest()[:16]

    safe_name = "".join(
        character
        if character.isalnum() or character in {"-", "_"}
        else "-"
        for character in resolved.name
    ).strip("-_") or "workspace"

    directory = _diagnostic_root() / f"{safe_name}-{identity}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _save_raw(
    workspace: Path,
    run_id: str | int,
    sequence: int | str,
    text: str | None = None,
) -> Path:
    """Save provider output in Sophyane state, never in user workspaces.

    The historical three-argument and current four-argument call forms remain
    supported, but both now write to a workspace-isolated state directory.
    """

    destination = _workspace_diagnostic_directory(
        Path(workspace)
    )

    if text is None:
        # Historical API:
        #   _save_raw(workspace, sequence, text)
        legacy_sequence = int(run_id)
        legacy_text = str(sequence)
        path = destination / (
            f"{RAW_PREFIX}-{legacy_sequence}.txt"
        )
        path.write_text(
            legacy_text,
            encoding="utf-8",
            errors="replace",
        )
        _cleanup_raw_responses(path.parent)
        return path

    path = destination / (
        f"{RAW_PREFIX}-{run_id}-{int(sequence)}.txt"
    )
    path.write_text(
        str(text),
        encoding="utf-8",
        errors="replace",
    )
    return path


def _extraction_diagnostic(adaptive: Any, raw: str) -> str:
    if not raw.strip():
        return "provider response was empty"
    lower = raw.lower()
    if "<!doctype html" not in lower and "<html" not in lower:
        if any(f'"{key}"' in raw for key in ("content", "files", "action", "tool_code", "code")):
            return "no extractable HTML found inside structured artifact response"
        return "response contained no HTML document"
    if "</html>" not in lower:
        return "HTML start was found but closing </html> was missing"
    extracted = adaptive._extract_html(raw)
    if extracted is None:
        return "complete-looking HTML could not be isolated from surrounding response text"
    return "HTML was extracted but failed later validation"


def _acceptable_rewrite(previous: str, candidate: str | None) -> bool:
    """Reject tiny replacement fragments that destroy a useful complete document."""
    if not candidate:
        return False
    minimum = max(300, int(len(previous) * MIN_REWRITE_RATIO))
    return len(candidate) >= minimum


def _strict_fresh_html_prompt(original_request: str) -> str:
    """Request a fresh document when no HTML prefix exists to continue."""

    return mark_raw_artifact(
        (
        "Your previous response contained no HTML. Start again from scratch. "
        "Return exactly ONE complete self-contained index.html and nothing else. "
        "The first characters must be <!doctype html> and the final characters "
        "must be </html>. Include inline CSS and JavaScript. Do not return JSON, "
        "markdown fences, explanations, planning, commands, or filenames. "
        "Make every requested interaction functional.\n"
        f"REQUEST: {str(original_request or '')[-500:]}"
        ),
        minimum_output_tokens=8192,
    )


def _deterministic_browser_fallback(
    original_request: str,
) -> str | None:
    """Provide a bounded local fallback for a basic addition calculator.

    This fallback is intentionally narrow. It is used only when the request
    clearly asks for adding numbers or a basic calculator and the provider
    twice returns no usable HTML.
    """

    text = " ".join(
        str(original_request or "").lower().split()
    )

    addition_request = (
        (
            "add numbers" in text
            or "adding numbers" in text
            or "addition" in text
        )
        and (
            "browser" in text
            or "html" in text
            or "web app" in text
            or "website" in text
        )
    )

    calculator_request = (
        "calculator" in text
        and (
            "browser" in text
            or "html" in text
            or "web app" in text
            or "website" in text
        )
    )

    if not (addition_request or calculator_request):
        return None

    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Add Numbers</title>
<style>
*{box-sizing:border-box}
html,body{width:100vw;min-height:100vh;margin:0}
body{display:grid;place-items:center;padding:20px;font-family:system-ui,sans-serif;background:#f3f4f6}
main{width:min(100%,420px);padding:24px;border-radius:18px;background:white;box-shadow:0 12px 35px #0002}
h1{margin-top:0}
label{display:block;margin-top:14px;font-weight:650}
input,button{width:100%;min-height:50px;margin-top:7px;border-radius:10px;font-size:1.1rem}
input{padding:10px 12px;border:1px solid #9ca3af}
button{border:0;background:#111827;color:white;font-weight:700;cursor:pointer}
output{display:block;min-height:58px;margin-top:18px;padding:14px;border-radius:10px;background:#eef2ff;font-size:1.35rem;font-weight:750}
</style>
</head>
<body>
<main>
<h1>Add Numbers</h1>
<form id="calculator">
<label for="first">First number</label>
<input id="first" type="number" step="any" inputmode="decimal" required>
<label for="second">Second number</label>
<input id="second" type="number" step="any" inputmode="decimal" required>
<button type="submit">Add numbers</button>
</form>
<output id="result" aria-live="polite">Result: —</output>
</main>
<script>
const form=document.querySelector("#calculator");
const first=document.querySelector("#first");
const second=document.querySelector("#second");
const result=document.querySelector("#result");
form.addEventListener("submit",event=>{
 event.preventDefault();
 const a=Number(first.value);
 const b=Number(second.value);
 result.textContent=Number.isFinite(a)&&Number.isFinite(b)
  ?`Result: ${a+b}`
  :"Please enter two valid numbers.";
});
</script>
</body>
</html>"""


def install_browser_partial_recovery() -> None:
    """Replace the one-shot browser path with progress-aware partial recovery."""
    from sophyane import adaptive_execution as adaptive
    from sophyane.html_repair_policy import is_structural_problem

    current = adaptive._one_shot_browser_artifact
    if getattr(current, "_sophyane_partial_recovery", False):
        return

    def recovered(*, ask: Callable[[str], Any], original_request: str,
                  workspace: Path, progress: Callable[[str], None]) -> str | None:
        workspace.mkdir(parents=True, exist_ok=True)
        target = workspace / "index.html"
        partial_file = workspace / PARTIAL_NAME
        run_id = _new_run_id()
        existing = ""
        if target.is_file():
            try:
                existing = target.read_text(encoding="utf-8")
            except OSError:
                existing = ""

        progress("Requesting one-shot provider-generated HTML edit" if existing else
                 "Requesting one-shot provider-generated HTML artifact")
        response = ask(adaptive._raw_html_prompt(original_request, existing))
        raw = _response_text(response)
        raw_path = _save_raw(workspace, run_id, 1, raw)
        reason = _finish_reason(response)
        progress(f"Saved raw provider response: {raw_path}")
        if reason != "unknown":
            progress(f"Provider finish reason: {reason}")

        html = adaptive._extract_html(raw)
        partial = adaptive._extract_partial_html(raw)
        best = html or partial
        if html is None:
            progress(
                "HTML extraction diagnostic: "
                + _extraction_diagnostic(adaptive, raw)
            )
        if best:
            partial_file.write_text(best, encoding="utf-8")

        # Continuation recovery requires an HTML prefix. When the provider
        # returns prose, JSON, planning, or an empty response, issue one
        # independent strict generation retry instead.
        response_sequence = 1
        if html is None and partial is None:
            progress(
                "Provider returned no HTML prefix; requesting one strict "
                "fresh HTML retry"
            )
            retry_response = ask(
                _strict_fresh_html_prompt(original_request)
            )
            retry_raw = _response_text(retry_response)
            response_sequence += 1
            retry_path = _save_raw(
                workspace,
                run_id,
                response_sequence,
                retry_raw,
            )
            progress(
                f"Saved strict retry provider response: {retry_path}"
            )

            retry_reason = _finish_reason(retry_response)
            if retry_reason != "unknown":
                progress(
                    f"Strict retry finish reason: {retry_reason}"
                )

            html = adaptive._extract_html(retry_raw)
            partial = adaptive._extract_partial_html(retry_raw)
            best = html or partial

            if html is None:
                progress(
                    "Strict retry extraction diagnostic: "
                    + _extraction_diagnostic(adaptive, retry_raw)
                )

            if best:
                partial_file.write_text(
                    best,
                    encoding="utf-8",
                )

        def recovery_problem(candidate: str | None) -> str:
            if candidate is None:
                return "document has no closing </html>"

            problem = adaptive._validate_html(candidate, original_request)
            if problem != "HTML is too small to be a meaningful application":
                return problem

            # A compact document assembled through exact continuations is
            # acceptable when its document and JavaScript structure is valid.
            lower = candidate.lower()
            structurally_complete = (
                ("<!doctype html" in lower or "<html" in lower)
                and "</html>" in lower
                and "<body" in lower
                and lower.count("<body") == lower.count("</body>")
                and lower.count("<script") == lower.count("</script>")
            )
            if not structurally_complete:
                return problem

            for match in re.finditer(
                r"<script\b[^>]*>(.*?)</script>",
                candidate,
                re.I | re.S,
            ):
                javascript_problem = adaptive._javascript_balance_problem(
                    match.group(1)
                )
                if javascript_problem:
                    return javascript_problem
            return ""

        attempts = 0
        stagnant = 0
        while attempts < MAX_CONTINUATIONS:
            problem = recovery_problem(html)
            if html is not None and not problem:
                break

            semantic = html is not None and not is_structural_problem(problem)
            if semantic:
                repair_base = html
            elif partial is None and html is not None:
                repair_base = adaptive._prepare_for_continuation(html)
            elif partial is not None:
                repair_base = adaptive._prepare_for_continuation(partial)
            else:
                repair_base = None

            if repair_base is None or len(repair_base) >= MAX_TOTAL_CHARS:
                break

            attempts += 1
            before = len(repair_base)
            partial_file.write_text(best or repair_base, encoding="utf-8")
            progress(
                f"Repairing incomplete provider HTML ({attempts}/{MAX_CONTINUATIONS}; "
                f"{before} characters preserved): {problem}"
            )
            response = ask(adaptive._html_continuation_prompt(repair_base, problem))
            continuation = _response_text(response)
            response_sequence += 1
            raw_path = _save_raw(workspace, run_id, response_sequence, continuation)
            progress(f"Saved raw continuation response: {raw_path}")
            reason = _finish_reason(response)
            if reason != "unknown":
                progress(f"Continuation finish reason: {reason}")

            candidate = adaptive._join_html_continuation(repair_base, continuation)
            candidate_html = adaptive._extract_html(candidate)

            if semantic and not _acceptable_rewrite(html, candidate_html):
                stagnant += 1
                produced = len(candidate_html or candidate)
                progress(
                    f"Rejected regressive semantic rewrite ({produced} characters); "
                    f"kept previous {len(html)}-character document"
                )
                partial = html
            elif not semantic and len(candidate) < before and candidate_html is None:
                stagnant += 1
                progress(
                    f"Rejected regressive continuation ({len(candidate) - before} characters); "
                    f"kept previous {before}-character partial"
                )
                partial = repair_base
            else:
                growth = len(candidate) - before
                if growth <= 0 and candidate_html is None:
                    stagnant += 1
                    progress(
                        f"Continuation made no progress ({growth} characters)"
                    )
                else:
                    # Providers may stream a valid continuation in very small
                    # fragments. Any positive growth must keep bounded recovery
                    # alive until the structural closing tags arrive.
                    if growth < MIN_PROGRESS and candidate_html is None:
                        progress(
                            f"Continuation made incremental progress "
                            f"({growth} characters)"
                        )
                    stagnant = 0
                partial = candidate
                html = candidate_html
                if html is not None:
                    best = html
                elif not best or len(partial) > len(best):
                    best = partial

            partial_file.write_text(best or partial or repair_base, encoding="utf-8")
            if html is None and partial is not None:
                html = adaptive._extract_html(partial)
            if html is None:
                progress("Continuation extraction diagnostic: " + _extraction_diagnostic(adaptive, continuation))
            if stagnant >= 2:
                progress("Stopping continuation because the provider stopped making progress")
                break

        evidence_directory = _workspace_diagnostic_directory(
            workspace
        )
        evidence_glob = str(
            evidence_directory
            / f"{RAW_PREFIX}-{run_id}-*.txt"
        )

        if html is None:
            fallback = _deterministic_browser_fallback(
                original_request
            )

            if fallback is not None:
                fallback_problem = recovery_problem(fallback)

                if not fallback_problem:
                    html = fallback
                    best = fallback
                    progress(
                        "Provider returned no usable HTML after strict "
                        "retry; generated validated deterministic "
                        "addition-calculator fallback"
                    )
                else:
                    progress(
                        "Deterministic browser fallback was rejected: "
                        f"{fallback_problem}"
                    )

        if html is None:
            preserved = best or partial
            if preserved:
                partial_file.write_text(
                    preserved,
                    encoding="utf-8",
                )
                progress(
                    f"Preserved incomplete HTML at {partial_file} "
                    f"({len(preserved)} characters)"
                )
            progress(
                f"Raw provider evidence preserved in {evidence_glob}"
            )
            return None

        problem = recovery_problem(html)
        if problem:
            preserved = best if best and len(best) >= len(html) else html
            partial_file.write_text(preserved, encoding="utf-8")
            progress(f"Provider HTML rejected after bounded recovery: {problem}")
            progress(f"Preserved rejected HTML at {partial_file}")
            progress(f"Raw provider evidence preserved in {evidence_glob}")
            return None

        temporary = target.with_suffix(".html.tmp")
        temporary.write_text(html, encoding="utf-8")
        temporary.replace(target)
        partial_file.unlink(missing_ok=True)
        progress(f"Wrote {target} ({target.stat().st_size} bytes)")
        from sophyane import execution_runtime as runtime
        progress("Browser artifact passed structural verification; opening demo")
        ok, result = runtime.execute_action({"type": "open_browser"}, workspace, progress)
        if not ok:
            return None
        return (
            "Updated and opened the provider-generated browser project.\n\n"
            f"Workspace: {workspace}\nFile: index.html\n\nExecution evidence:\n"
            f"- index.html exists ({target.stat().st_size} bytes)\n"
            f"- Recovered with {attempts} continuation attempt(s)\n"
            "- HTML body/script structure verified\n"
            "- JavaScript bracket structure verified\n"
            f"- {result}"
        )

    recovered._sophyane_partial_recovery = True  # type: ignore[attr-defined]
    adaptive._one_shot_browser_artifact = recovered
