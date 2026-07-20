"""Recovery patch for browser artifacts and natural project follow-ups."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable


def _html_document_from_string(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    lower = stripped.lower()
    starts = [p for p in (lower.find("<!doctype html"), lower.find("<html")) if p >= 0]
    if not starts:
        return None
    start = min(starts)
    end = lower.rfind("</html>")
    if end < start:
        return None
    document = stripped[start : end + len("</html>")].strip()
    if not document.lower().startswith(("<!doctype html", "<html")):
        return None
    return document if len(document.encode("utf-8")) >= 300 else None


def _extract_html_from_json(raw: str) -> str | None:
    candidate = (raw or "").strip()
    if not candidate:
        return None
    if candidate.startswith("```"):
        first_newline = candidate.find("\n")
        if first_newline >= 0:
            candidate = candidate[first_newline + 1 :]
        if candidate.rstrip().endswith("```"):
            candidate = candidate.rstrip()[:-3].rstrip()

    matches: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, str):
            document = _html_document_from_string(value)
            if document:
                matches.append(document)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    try:
        walk(json.loads(candidate))
    except (json.JSONDecodeError, TypeError):
        pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r'"(?:content|html|text|source)"\s*:\s*', candidate, re.I):
        position = match.end()
        while position < len(candidate) and candidate[position].isspace():
            position += 1
        if position >= len(candidate) or candidate[position] != '"':
            continue
        try:
            decoded, _ = decoder.raw_decode(candidate[position:])
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, str):
            document = _html_document_from_string(decoded)
            if document:
                matches.append(document)

    return max(matches, key=len) if matches else None


def _extract_html(text: str) -> str | None:
    return _extract_html_from_json(text) or _html_document_from_string(text)


def _complete_truncated_html(adaptive: Any, html: str | None) -> str | None:
    if not isinstance(html, str) or not html.strip():
        return html
    candidate = html.strip()
    lower = candidate.lower()
    if "<body" not in lower:
        return candidate
    opened = lower.count("<script")
    closed = lower.count("</script>")
    if opened == closed + 1:
        start = lower.rfind("<script")
        body_start = candidate.find(">", start)
        if body_start >= 0 and not adaptive._javascript_balance_problem(candidate[body_start + 1 :]):
            candidate += "\n</script>"
            lower = candidate.lower()
            closed += 1
    if opened != closed:
        return candidate
    if lower.count("<body") > lower.count("</body>"):
        candidate += "\n</body>"
        lower = candidate.lower()
    if "<html" in lower and "</html>" not in lower:
        candidate += "\n</html>"
    return candidate + "\n"


def _replacement_prompt(request: str, problem: str) -> str:
    return (
        "Generate a NEW complete standalone index.html only. Return raw HTML, not JSON, markdown, or commentary. "
        "Use inline CSS and JavaScript, no external resources, and keep it compact. Close every string, bracket, "
        "script, body, and html tag. End exactly with </script></body></html>.\n"
        f"Request: {request[-900:]}\nPrevious validation failure: {problem}"
    )


def install_generation_recovery_patch() -> None:
    from sophyane import adaptive_execution as adaptive
    from sophyane import tui_v2

    adaptive._extract_html = _extract_html

    original_one_shot = adaptive._one_shot_browser_artifact

    def one_shot(*, ask: Callable[[str], Any], original_request: str,
                 workspace: Path, progress: Callable[[str], None]) -> str | None:
        target = workspace / "index.html"
        existing = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        progress("Requesting one-shot provider-generated HTML edit" if existing else
                 "Requesting one-shot provider-generated HTML artifact")
        response = ask(adaptive._raw_html_prompt(original_request, existing))
        raw = getattr(response, "text", str(response))
        html = _extract_html(raw)
        partial = adaptive._extract_partial_html(raw)

        if html is None and partial is not None:
            html = _extract_html(_complete_truncated_html(adaptive, partial) or "")

        for attempt in range(1, 3):
            problem = adaptive._validate_html(html, original_request) if html else "document has no closing </html>"
            if html and not problem:
                break
            structural = {
                "document has no closing </html>", "HTML structure is incomplete",
                "HTML body tag is not closed", "HTML script tag is not closed",
            }
            if html and problem not in structural:
                progress(f"Provider HTML requires semantic replacement: {problem}")
                response = ask(_replacement_prompt(original_request, problem))
                raw = getattr(response, "text", str(response))
                try:
                    (workspace / f".provider-html-replacement-{attempt}.txt").write_text(raw, encoding="utf-8")
                except OSError:
                    pass
                html = _extract_html(raw)
                if html is None:
                    candidate = _complete_truncated_html(adaptive, adaptive._extract_partial_html(raw))
                    html = _extract_html(candidate or "")
                continue
            if partial is None and html is not None:
                partial = adaptive._prepare_for_continuation(html)
            elif partial is not None:
                partial = adaptive._prepare_for_continuation(partial)
            if partial is None:
                break
            progress(f"Repairing incomplete provider HTML ({attempt}/2; {len(partial)} characters preserved): {problem}")
            response = ask(adaptive._html_continuation_prompt(partial, problem))
            partial = adaptive._join_html_continuation(partial, getattr(response, "text", str(response)))
            partial = _complete_truncated_html(adaptive, partial)
            html = _extract_html(partial or "")

        if html is None:
            return None
        problem = adaptive._validate_html(html, original_request)
        if problem:
            progress(f"Provider HTML rejected after targeted repair: {problem}")
            return None
        temporary = target.with_suffix(".html.tmp")
        temporary.write_text(html, encoding="utf-8")
        temporary.replace(target)
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
            "- HTML body/script structure verified\n- JavaScript bracket structure verified\n"
            f"- {result}"
        )

    adaptive._one_shot_browser_artifact = one_shot

    base_execution = tui_v2._execution_requested

    def execution_requested(message: str) -> bool:
        text = " ".join(message.lower().split())
        explicit = re.match(
            r"^(?:build|make|create|design|develop|implement|write|fix|repair|patch|compile|run|test|deploy|open|continue|resume|convert|install|integrate|optimi[sz]e|execute|add|remove|change|update|improve|style|replace|modify)\b",
            text,
        )
        if explicit:
            return True
        return base_execution(message)

    tui_v2._execution_requested = execution_requested

    def project_continuation(message: str, has_project: bool) -> bool:
        if not has_project or tui_v2._explicit_new_benchmark(message):
            return False
        text = " ".join(message.lower().split())
        markers = (
            "update", "change", "modify", "edit", "fix", "improve", "make it", "make the",
            "should be", "should have", "bigger", "larger", "smaller", "full screen", "fullscreen",
            "whole screen", "font", "button", "background", "layout", "color", "add ", "remove ",
            "existing", "current game", "current page", "reopen", "run again",
        )
        return any(marker in text for marker in markers)

    tui_v2._project_continuation = project_continuation
