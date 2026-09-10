"""Durable recovery for provider HTML that is repeatedly truncated.

The best partial document and each raw provider response are preserved so failed
browser generation can be diagnosed instead of silently discarded.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Callable


PARTIAL_NAME = ".sophyane-partial-index.html"
RAW_PREFIX = ".sophyane-provider-response"
MAX_CONTINUATIONS = 6
# SOPHYANE_PROVIDER_MANAGED_ARTIFACT_SIZE_V1
#
# Zero means no Sophyane-imposed character ceiling. Provider transport/context
# budgeting belongs at the provider layer. Recovery remains bounded by
# MAX_CONTINUATIONS and no-progress detection.
MAX_TOTAL_CHARS = 0
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


def _new_run_id() -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{time.time_ns() % 1_000_000_000:09d}"


def _save_raw(
    workspace: Path,
    run_id: str | int,
    sequence: int | str,
    text: str | None = None,
) -> Path:
    """Save provider output while preserving the historical three-argument API.

    Supported forms:
      _save_raw(workspace, run_id, sequence, text)
      _save_raw(workspace, sequence, text)
    """
    if text is None:
        # Historical API:
        #   _save_raw(workspace, sequence, text)
        legacy_sequence = int(run_id)
        legacy_text = str(sequence)
        path = workspace / f"{RAW_PREFIX}-{legacy_sequence}.txt"
        path.write_text(
            legacy_text,
            encoding="utf-8",
            errors="replace",
        )
        return path

    path = workspace / f"{RAW_PREFIX}-{run_id}-{int(sequence)}.txt"
    path.write_text(str(text), encoding="utf-8", errors="replace")
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


# SOPHYANE_BROWSER_SEMANTIC_PROGRESS_KEY_V1
def _semantic_repair_state(
    candidate: str,
    problem: str,
) -> tuple[str, str]:
    """Return a stable state key for semantic repair progress."""

    normalized_document = re.sub(
        r"\s+",
        " ",
        str(candidate or ""),
    ).strip()

    # Formatting-only whitespace between tags is not semantic progress.
    normalized_document = re.sub(
        r">\s+<",
        "><",
        normalized_document,
    )

    normalized_problem = " ".join(
        str(problem or "")
        .casefold()
        .split()
    )

    digest = hashlib.sha256(
        normalized_document.encode("utf-8")
    ).hexdigest()

    return normalized_problem, digest


QUALITY_SCORE = 95
QUALITY_LOOPS = 3


def _json_object(raw: str):
    """Extract one valid JSON object from a provider response.

    Accept transport decoration such as Markdown JSON fences or a short
    explanatory prefix/suffix, but never accept Python literals, repaired
    JSON, or non-object payloads.
    """
    import json
    import re

    text = str(raw or "").strip()
    if not text:
        return None

    def decode(candidate: str):
        candidate = candidate.strip()
        if not candidate:
            return None
        try:
            value = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    # Best case: provider obeyed the contract exactly.
    # If the complete response is valid JSON but has the wrong top-level
    # type, reject it terminally instead of extracting a nested object.
    try:
        complete = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        complete = None
    else:
        return complete if isinstance(complete, dict) else None

    # Common browser-LLM envelope:
    #
    # ```json
    # {...}
    # ```
    for match in re.finditer(
        r"```(?:json)?\s*(.*?)```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        value = decode(match.group(1))
        if value is not None:
            return value

    # Last tolerant transport step: locate a balanced JSON object while
    # respecting braces that occur inside JSON strings.
    starts = [
        index
        for index, character in enumerate(text)
        if character == "{"
    ]

    for start in starts:
        depth = 0
        in_string = False
        escaped = False

        for index in range(start, len(text)):
            character = text[index]

            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue

            if character == '"':
                in_string = True
                continue

            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1

                if depth == 0:
                    value = decode(text[start:index + 1])
                    if value is not None:
                        return value
                    break

                if depth < 0:
                    break

    return None




# SOPHYANE_NIFDU_QUALITY_BROWSER_BOOTSTRAP_V1
def _nifdu_multimodal_ask(
    prompt: str,
    screenshot: Path,
) -> str:
    """Invoke tracked NIFDU only after its Chromium/CDP transport is ready.

    The normal NifduBrowserProvider bootstraps Chromium before each
    invocation. Visual judge/repair calls attach screenshots directly
    through the tracked bridge, so they must preserve that same browser
    lifecycle contract instead of assuming port 9222 remains alive.
    """
    from sophyane.browser import launch_nifdu_browser
    from sophyane.providers import nifdu_cdp_bridge
    browser_state = launch_nifdu_browser()

    if not browser_state.get("ok"):
        detail = str(
            browser_state.get("error")
            or "tracked Chromium/CDP browser failed to start"
        )
        raise RuntimeError(
            "NIFDU quality browser bootstrap failed: "
            + detail
        )

    return str(
        nifdu_cdp_bridge.ask(
            prompt,
            str(screenshot),
        )
        or ""
    )


def _nifdu_visual_judge(
    *,
    original_request: str,
    html: str,
    screenshot: Path,
    rendered: Any,
    iteration: int,
    progress: Callable[[str], None],
) -> dict[str, Any]:
    # SOPHYANE_COMPACT_VISUAL_JUDGE_CONTRACT_V1
    #
    # Keep the judge transport deliberately scalar-only. Free-form prose
    # containing quotes, snippets or newlines is produced separately by the
    # repair model and must never decide whether the quality gate passed.
    # SOPHYANE_VISUAL_JUDGE_AUTHORITY_BOUNDARY_V1
    # Runtime facts such as broken images and evidence freshness are
    # deterministic browser responsibilities, not visual-model opinions.
    _repair_codes = {
        "NONE",
        "MISSING_REQUIRED_CONTENT",
        "VISUAL_HIERARCHY",
        "RESPONSIVE_LAYOUT",
        "ACCESSIBILITY",
        "INTERACTION_FAILURE",
        "MULTIPLE_ISSUES",
    }

    _render_facts = {
        "images": int(rendered.images),
        "broken_images": int(rendered.broken_images),
        "console_errors": int(rendered.console_errors),
        "log_errors": int(rendered.log_errors),
        "horizontal_overflow": bool(rendered.horizontal_overflow),
    }

    prompt = (
        "You are NIFDU's independent visual product judge. "
        "Inspect the attached rendered screenshot carefully and compare it "
        "against the immutable customer request and CURRENT HTML. "
        "Judge visual hierarchy, typography, spacing, imagery, composition, "
        "responsive/mobile polish, accessibility, completeness and obvious "
        "interaction quality. A mechanically valid page is NOT automatically "
        "a good product. "
        "Return ONLY one valid minified JSON object. No Markdown, no prose, "
        "no code fence and no newline inside string values. "
        "Use EXACTLY these five keys and no others: "
        '{"accepted":false,"score":0,"critical_issues":0,'
        '"unmet_requirements":0,"repair_code":"MULTIPLE_ISSUES"}. '
        "repair_code MUST be exactly one of: "
        "NONE, MISSING_REQUIRED_CONTENT, VISUAL_HIERARCHY, "
        "RESPONSIVE_LAYOUT, ACCESSIBILITY, INTERACTION_FAILURE, "
        "MULTIPLE_ISSUES. "
        "Do NOT diagnose BROKEN_IMAGES or STALE_RENDER_EVIDENCE. "
        "Those are deterministic runtime facts owned by Sophyane, not "
        "visual-model judgments. "
        "The browser facts below are authoritative. Do not contradict them. "
        f"DETERMINISTIC RENDER FACTS: {_render_facts}. "
        f"Acceptance requires score >= {QUALITY_SCORE}, "
        "zero critical_issues, zero unmet_requirements, and repair_code NONE. "
        f"Iteration: {iteration}. CUSTOMER REQUEST: {original_request}\n"
        "CURRENT HTML:\n" + html
    )
    progress(
        f"NIFDU visual quality judge: iteration {iteration}/{QUALITY_LOOPS}; "
        f"attaching {screenshot}"
    )
    # SOPHYANE_NIFDU_JUDGE_JSON_RETRY_V1
    # A malformed provider envelope is not a quality verdict.
    # Save it for evidence and allow exactly one serialization retry.
    # Never infer acceptance from malformed output.
    from pathlib import Path as _JudgePath
    import time as _judge_time

    report = None
    raw = ""

    for _judge_json_attempt in range(1, 3):
        if _judge_json_attempt == 1:
            raw = _nifdu_multimodal_ask(prompt, screenshot)
        else:
            _judge_retry_prompt = (
                str(prompt)
                + "\n\nSTRICT SERIALIZATION RETRY:\n"
                + "Your preceding response was not one valid JSON object. "
                + "Repeat the same evaluation and return ONLY the exact "
                + "JSON object requested above. No Markdown. No code fence. "
                + "No prose before or after it. Use JSON double quotes, "
                + "valid JSON booleans, and include every required field."
            )

            raw = _nifdu_multimodal_ask(_judge_retry_prompt, screenshot)

        _judge_raw_dir = _JudgePath(
            ".sophyane/visual-quality/raw-judge-responses"
        )
        _judge_raw_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        _judge_raw_path = _judge_raw_dir / (
            "judge-"
            + str(_judge_time.time_ns())
            + "-attempt-"
            + str(_judge_json_attempt)
            + ".txt"
        )

        _judge_raw_path.write_text(
            str(raw or ""),
            encoding="utf-8",
        )

        report = _json_object(raw)

        if report is not None:
            _expected_judge_keys = {
                "accepted",
                "score",
                "critical_issues",
                "unmet_requirements",
                "repair_code",
            }

            _schema_ok = (
                set(report) == _expected_judge_keys
                and isinstance(report.get("accepted"), bool)
                and isinstance(report.get("score"), int)
                and not isinstance(report.get("score"), bool)
                and 0 <= report.get("score") <= 100
                and isinstance(report.get("critical_issues"), int)
                and not isinstance(report.get("critical_issues"), bool)
                and report.get("critical_issues") >= 0
                and isinstance(report.get("unmet_requirements"), int)
                and not isinstance(report.get("unmet_requirements"), bool)
                and report.get("unmet_requirements") >= 0
                and isinstance(report.get("repair_code"), str)
                and report.get("repair_code") in _repair_codes
            )

            if not _schema_ok:
                report = None

        if report is not None:
            break


    if report is None:
        raise RuntimeError(
            "NIFDU visual judge returned invalid JSON "
            "after bounded serialization retry"
        )

    score = int(report["score"])
    critical = int(report["critical_issues"])
    unmet = int(report["unmet_requirements"])
    repair_code = str(report["repair_code"])
    model_accepted = bool(report["accepted"])

    report["accepted"] = bool(
        model_accepted
        and score >= QUALITY_SCORE
        and critical == 0
        and unmet == 0
        and repair_code == "NONE"
    )

    report["score"] = score
    report["critical_issues"] = critical
    report["unmet_requirements"] = unmet
    report["repair_code"] = repair_code

    _repair_instructions = {
        "NONE": "No judge-requested repair.",
        "BROKEN_IMAGES": (
            "Repair all broken, malformed or unreliable image sources and "
            "verify the final rendered photography."
        ),
        "MISSING_REQUIRED_CONTENT": (
            "Restore every customer-requested section, feature and content "
            "requirement that is missing or incomplete."
        ),
        "VISUAL_HIERARCHY": (
            "Improve visual hierarchy, composition, typography, spacing and "
            "CTA emphasis while preserving all required functionality."
        ),
        "RESPONSIVE_LAYOUT": (
            "Repair responsive/mobile composition, spacing, sizing and "
            "viewport behavior without regressing desktop behavior."
        ),
        "ACCESSIBILITY": (
            "Repair accessibility semantics, labels, focus behavior, state "
            "announcements and contrast while preserving the visual design."
        ),
        "INTERACTION_FAILURE": (
            "Repair visibly or mechanically broken interactions and preserve "
            "all existing working features."
        ),
        "STALE_RENDER_EVIDENCE": (
            "Ensure the screenshot is rendered from the exact current HTML "
            "and that rendered evidence matches the artifact being judged."
        ),
        "MULTIPLE_ISSUES": (
            "Perform a comprehensive repair against the customer request, "
            "current HTML and rendered screenshot, addressing every material "
            "visual, functional, responsive and accessibility weakness."
        ),
    }

    _instruction = _repair_instructions[repair_code]

    # SOPHYANE_NIFDU_TARGETED_REPAIR_DIAGNOSIS_V1
    #
    # The compact five-key verdict remains the sole quality authority.
    # A rejected verdict, however, does not contain enough information for
    # a corrective model to make a targeted repair. Ask the same visual
    # provider for a separate non-authoritative diagnosis rather than
    # expanding or weakening the strict verdict schema.
    report["summary"] = (
        "Accepted by compact visual judge."
        if report["accepted"]
        else f"Visual judge requested repair: {repair_code}."
    )
    report["problems"] = []
    report["repair_instruction"] = _instruction

    if not report["accepted"]:
        diagnosis_prompt = (
            "You are NIFDU's visual repair diagnostician. "
            "The independent visual judge has already REJECTED this product. "
            "Do not reconsider, override or change that verdict. "
            "Inspect the same rendered screenshot, immutable customer request "
            "and CURRENT HTML and identify the concrete reasons the product "
            "needs repair. Focus only on visible/product deficiencies that a "
            "corrective engineer can actually fix. Do not invent broken images, "
            "console errors, stale-render claims or other deterministic facts. "
            "The browser facts below are authoritative. "
            f"DETERMINISTIC RENDER FACTS: {_render_facts}. "
            f"VERDICT: score={score}, critical_issues={critical}, "
            f"unmet_requirements={unmet}, repair_code={repair_code}. "
            "Return ONLY one valid minified JSON object with EXACTLY these "
            "three keys and no others: "
            '{"problems":["specific repairable problem"],'
            '"repair_instruction":"targeted corrective instruction",'
            '"summary":"short diagnosis summary"}. '
            "problems MUST contain 1 to 6 specific, non-duplicate findings. "
            "Each finding must describe what is wrong, not merely name a "
            "category. repair_instruction MUST tell the engineer to preserve "
            "working functionality and fix only the listed deficiencies; "
            "do not request a broad redesign unless the screenshot genuinely "
            "requires one. No Markdown, no prose outside JSON. "
            f"Iteration: {iteration}. CUSTOMER REQUEST: {original_request}\n"
            "CURRENT HTML:\n" + html
        )

        progress(
            "NIFDU visual diagnosis: requesting specific repair findings "
            f"for iteration {iteration}"
        )

        diagnosis = None
        diagnosis_raw = ""

        for _diagnosis_attempt in range(1, 3):
            if _diagnosis_attempt == 1:
                diagnosis_raw = _nifdu_multimodal_ask(
                    diagnosis_prompt,
                    screenshot,
                )
            else:
                diagnosis_raw = _nifdu_multimodal_ask(
                    diagnosis_prompt
                    + "\n\nSTRICT SERIALIZATION RETRY: Return ONLY the "
                    "three-key JSON object requested above. No Markdown, "
                    "no code fence and no prose.",
                    screenshot,
                )

            _diagnosis_raw_path = _judge_raw_dir / (
                "diagnosis-"
                + str(_judge_time.time_ns())
                + "-attempt-"
                + str(_diagnosis_attempt)
                + ".txt"
            )
            _diagnosis_raw_path.write_text(
                str(diagnosis_raw or ""),
                encoding="utf-8",
            )

            candidate = _json_object(diagnosis_raw)
            if candidate is None:
                continue

            problems = candidate.get("problems")
            instruction = candidate.get("repair_instruction")
            summary = candidate.get("summary")

            diagnosis_ok = (
                set(candidate) == {
                    "problems",
                    "repair_instruction",
                    "summary",
                }
                and isinstance(problems, list)
                and 1 <= len(problems) <= 6
                and all(
                    isinstance(item, str)
                    and item.strip()
                    and len(item.strip()) <= 500
                    for item in problems
                )
                and isinstance(instruction, str)
                and bool(instruction.strip())
                and len(instruction.strip()) <= 2000
                and isinstance(summary, str)
                and bool(summary.strip())
                and len(summary.strip()) <= 1000
            )

            if diagnosis_ok:
                diagnosis = candidate
                break

        if diagnosis is not None:
            report["problems"] = [
                item.strip()
                for item in diagnosis["problems"]
            ]
            report["repair_instruction"] = str(
                diagnosis["repair_instruction"]
            ).strip()
            report["summary"] = str(
                diagnosis["summary"]
            ).strip()
            progress(
                "NIFDU visual diagnosis: captured "
                f"{len(report['problems'])} targeted finding(s)"
            )
        else:
            # Safe compatibility fallback: a malformed diagnosis must never
            # invalidate or alter the already-valid compact rejection verdict.
            report["problems"] = [_instruction]
            progress(
                "NIFDU visual diagnosis unavailable after bounded retry; "
                "using repair-code fallback"
            )

    return report


def _nifdu_visual_repair(
    *,
    adaptive: Any,
    original_request: str,
    html: str,
    report: dict[str, Any],
    screenshot: Path,
    iteration: int,
    progress: Callable[[str], None],
) -> str:
    prompt = (
        "Act as NIFDU's senior corrective product engineer. "
        "Repair the current web product using every finding from the independent visual judge. "
        "The original customer request is immutable. Preserve all working functionality. "
        "Return ONE complete raw index.html only; no markdown, JSON, explanation or shell commands. "
        "Improve the actual product, not merely the wording. "
        f"ORIGINAL REQUEST: {original_request}\n"
        "JUDGE REPORT:\n" + json.dumps(report, ensure_ascii=False) + "\n"
        "CURRENT HTML:\n" + html
    )
    progress(f"Applying NIFDU judge-required repair after iteration {iteration}")
    raw = _nifdu_multimodal_ask(prompt, screenshot)
    repaired = adaptive._extract_html(str(raw or ""))
    if repaired is None:
        raise RuntimeError("NIFDU corrective pass returned no complete HTML")
    problem = adaptive._validate_html(repaired, original_request)
    if problem:
        raise RuntimeError(f"NIFDU corrective HTML failed structural validation: {problem}")
    return repaired



# SOPHYANE_DETERMINISTIC_RENDER_QUALITY_GATE_V1
def _request_requires_rendered_images(original_request: str) -> bool:
    text = " ".join(
        str(original_request or "")
        .casefold()
        .replace("-", " ")
        .split()
    )
    image_terms = (
        "photography",
        "photograph",
        "photos",
        "photo",
        "images",
        "image",
        "imagery",
        "picture",
        "pictures",
    )
    return any(term in text for term in image_terms)


def _apply_render_quality_gate(
    report: dict[str, Any],
    rendered: Any,
    original_request: str,
) -> dict[str, Any]:
    """Combine AI judgment with deterministic browser evidence.

    AI acceptance can never override observable renderer failures.
    """
    combined = dict(report)

    facts = {
        "images": int(rendered.images),
        "broken_images": int(rendered.broken_images),
        "console_errors": int(rendered.console_errors),
        "log_errors": int(rendered.log_errors),
        "horizontal_overflow": bool(rendered.horizontal_overflow),
        "required_images": _request_requires_rendered_images(
            original_request
        ),
    }
    combined["render_facts"] = facts

    problems: list[str] = []
    render_codes: list[str] = []

    if facts["broken_images"] > 0:
        problems.append(
            f"{facts['broken_images']} rendered image(s) are broken"
        )
        render_codes.append("BROKEN_IMAGES")
        combined["critical_issues"] = max(
            1,
            int(combined.get("critical_issues", 0)),
        )

    if facts["console_errors"] > 0 or facts["log_errors"] > 0:
        problems.append(
            "browser runtime reported "
            f"{facts['console_errors']} console error(s) and "
            f"{facts['log_errors']} log error(s)"
        )
        render_codes.append("INTERACTION_FAILURE")
        combined["critical_issues"] = max(
            1,
            int(combined.get("critical_issues", 0)),
        )

    if facts["horizontal_overflow"]:
        problems.append(
            "rendered page has horizontal viewport overflow"
        )
        render_codes.append("RESPONSIVE_LAYOUT")
        combined["critical_issues"] = max(
            1,
            int(combined.get("critical_issues", 0)),
        )

    if facts["required_images"] and facts["images"] <= 0:
        problems.append(
            "customer explicitly requested photography/images "
            "but zero images rendered"
        )
        render_codes.append("MISSING_REQUIRED_CONTENT")
        combined["unmet_requirements"] = max(
            1,
            int(combined.get("unmet_requirements", 0)),
        )

    if not problems:
        return combined

    combined["accepted"] = False

    existing_code = str(
        combined.get("repair_code", "MULTIPLE_ISSUES")
    )
    codes = {
        code
        for code in render_codes
        if code != "NONE"
    }
    if existing_code != "NONE":
        codes.add(existing_code)

    combined["repair_code"] = (
        next(iter(codes))
        if len(codes) == 1
        else "MULTIPLE_ISSUES"
    )

    existing_problems = combined.get("problems")
    if isinstance(existing_problems, list):
        combined["problems"] = [
            *existing_problems,
            *problems,
        ]
    else:
        combined["problems"] = problems

    # SOPHYANE_NIFDU_DIAGNOSIS_RENDER_MERGE_V1
    #
    # Deterministic renderer failures are authoritative, but they must augment
    # rather than erase the visual diagnostician's actionable repair guidance.
    # Otherwise a rich diagnosis collapses back to a single mechanical issue.
    _existing_summary = str(combined.get("summary") or "").strip()
    _existing_instruction = str(
        combined.get("repair_instruction") or ""
    ).strip()

    _render_summary = (
        "Deterministic rendered-browser evidence also blocks certification: "
        + "; ".join(problems)
        + "."
    )
    _render_instruction = (
        "Also repair these deterministic rendered-browser failures: "
        + "; ".join(problems)
        + ". Re-render and verify them before certification."
    )

    combined["summary"] = (
        (_existing_summary.rstrip() + " " + _render_summary).strip()
        if _existing_summary
        else _render_summary
    )

    if (
        _existing_instruction
        and _existing_instruction != "No judge-requested repair."
    ):
        combined["repair_instruction"] = (
            _existing_instruction.rstrip()
            + " "
            + _render_instruction
        )
    else:
        combined["repair_instruction"] = _render_instruction

    return combined



# SOPHYANE_NIFDU_BEST_ARTIFACT_CONVERGENCE_V1
def _deterministic_render_failure_count(report: dict[str, Any]) -> int:
    facts = report.get("render_facts")
    if not isinstance(facts, dict):
        return 0

    failures = 0

    if int(facts.get("broken_images", 0)) > 0:
        failures += 1

    if (
        int(facts.get("console_errors", 0)) > 0
        or int(facts.get("log_errors", 0)) > 0
    ):
        failures += 1

    if bool(facts.get("horizontal_overflow", False)):
        failures += 1

    if (
        bool(facts.get("required_images", False))
        and int(facts.get("images", 0)) <= 0
    ):
        failures += 1

    return failures


def _quality_rank(report: dict[str, Any]) -> tuple[int, int, int]:
    """Higher tuple is better.

    Observable browser correctness outranks subjective judge score.
    """
    deterministic_failures = _deterministic_render_failure_count(report)
    critical = int(report.get("critical_issues", 0))
    unmet = int(report.get("unmet_requirements", 0))
    score = int(report.get("score", 0))

    return (
        -deterministic_failures,
        -(critical + unmet),
        score,
    )


def _reconcile_visual_repair_code(
    report: dict[str, Any],
) -> dict[str, Any]:
    """Do not let subjective codes contradict deterministic browser facts."""
    combined = dict(report)
    facts = combined.get("render_facts")

    if not isinstance(facts, dict):
        return combined

    code = str(combined.get("repair_code", ""))

    if (
        code == "BROKEN_IMAGES"
        and int(facts.get("broken_images", 0)) == 0
    ):
        combined["repair_code"] = "MULTIPLE_ISSUES"
        combined["summary"] = (
            "Visual judge requested further improvement, but deterministic "
            "browser evidence reports zero broken images."
        )
        combined["problems"] = [
            "Do not replace working image sources merely because the visual "
            "judge emitted BROKEN_IMAGES; browser evidence reports zero "
            "broken images. Improve the remaining visual/product weaknesses."
        ]
        combined["repair_instruction"] = (
            "Preserve all currently rendering images. Improve visual hierarchy, "
            "composition, responsive polish, accessibility and requirement "
            "coverage without treating working images as broken."
        )

    elif code == "STALE_RENDER_EVIDENCE":
        combined["repair_code"] = "MULTIPLE_ISSUES"
        combined["summary"] = (
            "Visual judge suspected stale evidence, but staleness is not "
            "accepted as a visual-only fact."
        )
        combined["problems"] = [
            "Preserve the current valid artifact and improve actual visible "
            "quality; do not rewrite the product solely because the judge "
            "guessed that evidence was stale."
        ]
        combined["repair_instruction"] = (
            "Improve the actual rendered product while preserving working "
            "content and interactions. Evidence freshness must be established "
            "deterministically rather than inferred visually."
        )

    return combined



# SOPHYANE_CREATIVE_EPISODE_RUNTIME_V1
def _record_creative_episode(
    *,
    workspace: Path,
    target: Path,
    original_request: str,
    rendered: Any,
    report: dict[str, Any],
    iteration: int,
    screenshot: Path,
    iteration_html: Path,
    iteration_screenshot: Path,
    previous_score: int | None,
    parent_artifact_sha256: str,
    progress,
) -> tuple[int, str]:
    """
    Persist advisory creative memory from an already-judged candidate.

    Authority boundary:
      - NIFDU/render gates decide acceptance.
      - Neuron only enriches perception.
      - Xerus only stores/retrieves memory.
      - Any memory failure is non-fatal to product verification.
    """
    try:
        from sophyane.creative_episode import (
            build_episode,
            enrich_with_neuron,
            persist_to_xerus,
        )

        episode = build_episode(
            objective=original_request,
            artifact_path=iteration_html,
            screenshot_path=iteration_screenshot,
            iteration=iteration,
            provider_id="nifdu_browser",
            rendered=rendered,
            report=report,
            parent_artifact_sha256=parent_artifact_sha256,
            previous_score=previous_score,
        )

        episode = enrich_with_neuron(
            episode,
            screenshot_path=iteration_screenshot,
        )

        episode_path = (
            workspace
            / ".sophyane"
            / "visual-quality"
            / f"iteration-{iteration}-episode.json"
        )

        episode_path.write_text(
            json.dumps(
                episode.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        stored = persist_to_xerus(
            episode
        )

        xerus_status = (
            "stored"
            if stored.get("ok") is True
            else "unavailable"
        )

        delta_text = (
            ""
            if episode.score_delta is None
            else (
                f"; delta={episode.score_delta:+d}"
            )
        )

        progress(
            "Creative episode: "
            f"iteration {iteration}; "
            + (
                "accepted"
                if episode.accepted
                else "rejected"
            )
            + f"; score={episode.judge_score}"
            + delta_text
            + f"; Neuron={episode.perception_status}"
            + f"; Xerus={xerus_status}"
        )

        if (
            stored.get("ok") is not True
            and stored.get("reason")
        ):
            progress(
                "Creative episode memory advisory failure: "
                + str(stored["reason"])
            )

        return (
            episode.judge_score,
            episode.artifact_sha256,
        )

    except Exception as exc:
        # Memory is advisory and must never alter NIFDU certification.
        progress(
            "Creative episode advisory capture failed: "
            + type(exc).__name__
            + ": "
            + str(exc)
        )

        return (
            int(report.get("score", 0) or 0),
            parent_artifact_sha256,
        )


def _capture_quality_evidence(
    workspace: Path,
    target: Path,
    progress: Callable[[str], None],
):
    from sophyane.browser_runtime_v2 import _server_for
    from sophyane.rendered_evidence import capture_rendered_evidence

    base = _server_for(workspace)
    url = f"{base}/index.html?v={target.stat().st_mtime_ns}"
    rendered = capture_rendered_evidence(url, workspace, progress)
    screenshot = workspace / ".sophyane" / "rendered" / "latest.png"
    if (
        not rendered.available
        or not rendered.ok
        or not screenshot.is_file()
        or screenshot.stat().st_size < 1000
    ):
        raise RuntimeError(
            "rendered screenshot evidence is unavailable; visual quality cannot be certified"
        )
    return rendered, screenshot


def install_browser_partial_recovery() -> None:
    """Replace the one-shot browser path with progress-aware partial recovery."""
    from sophyane import adaptive_execution as adaptive
    from sophyane.html_repair_policy import is_structural_problem

    current = adaptive._one_shot_browser_artifact
    if getattr(current, "_sophyane_partial_recovery", False):
        return

    def recovered(*, ask: Callable[[str], Any], original_request: str,
                  workspace: Path, progress: Callable[[str], None]) -> str | None:
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
            progress("HTML extraction diagnostic: " + _extraction_diagnostic(adaptive, raw))
        if best:
            partial_file.write_text(best, encoding="utf-8")

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
        response_sequence = 1
        seen_repair_states: set[tuple[str, str]] = set()

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

            if repair_base is None:
                break
            if MAX_TOTAL_CHARS > 0 and len(repair_base) >= MAX_TOTAL_CHARS:
                break

            # SOPHYANE_BROWSER_SEMANTIC_NO_PROGRESS_STOP_V1
            #
            # Detect repeated semantic state before spending another provider
            # call. Character growth alone cannot detect a provider returning
            # the same complete HTML with the same validation failure.
            repair_state = _semantic_repair_state(
                repair_base,
                problem,
            )

            if repair_state in seen_repair_states:
                progress(
                    "Stopping semantic repair before another provider call: "
                    f"repeated validation problem after {attempts} "
                    f"completed attempt(s): {problem}"
                )
                break

            seen_repair_states.add(
                repair_state
            )

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

        evidence_glob = f"{workspace}/{RAW_PREFIX}-{run_id}-*.txt"
        if html is None:
            preserved = best or partial
            if preserved:
                partial_file.write_text(preserved, encoding="utf-8")
                progress(f"Preserved incomplete HTML at {partial_file} ({len(preserved)} characters)")
            progress(f"Raw provider evidence preserved in {evidence_glob}")
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

        quality_root = workspace / ".sophyane" / "visual-quality"
        quality_root.mkdir(parents=True, exist_ok=True)
        latest_report: dict[str, Any] | None = None
        best_report: dict[str, Any] | None = None
        best_html: str | None = None
        best_screenshot: Path | None = None
        best_rank: tuple[int, int, int] | None = None

        previous_episode_score: int | None = None
        previous_episode_artifact_sha256 = ""

        for quality_iteration in range(1, QUALITY_LOOPS + 1):
            rendered, screenshot = _capture_quality_evidence(
                workspace,
                target,
                progress,
            )
            html = target.read_text(encoding="utf-8")
            latest_report = _nifdu_visual_judge(
                original_request=original_request,
                html=html,
                screenshot=screenshot,
                rendered=rendered,
                iteration=quality_iteration,
                progress=progress,
            )
            latest_report = _apply_render_quality_gate(
                latest_report,
                rendered,
                original_request,
            )
            latest_report = _reconcile_visual_repair_code(
                latest_report
            )

            iteration_html = quality_root / (
                f"iteration-{quality_iteration}.html"
            )
            iteration_html.write_text(
                html,
                encoding="utf-8",
            )

            iteration_screenshot = quality_root / (
                f"iteration-{quality_iteration}.png"
            )
            iteration_screenshot.write_bytes(
                screenshot.read_bytes()
            )

            (
                previous_episode_score,
                previous_episode_artifact_sha256,
            ) = _record_creative_episode(
                workspace=workspace,
                target=target,
                original_request=original_request,
                rendered=rendered,
                report=latest_report,
                iteration=quality_iteration,
                screenshot=screenshot,
                iteration_html=iteration_html,
                iteration_screenshot=iteration_screenshot,
                previous_score=previous_episode_score,
                parent_artifact_sha256=(
                    previous_episode_artifact_sha256
                ),
                progress=progress,
            )

            candidate_rank = _quality_rank(latest_report)
            candidate_is_best = (
                best_rank is None
                or candidate_rank > best_rank
            )

            if candidate_is_best:
                best_rank = candidate_rank
                best_report = dict(latest_report)
                best_html = html
                best_screenshot = iteration_screenshot

            report_path = quality_root / f"iteration-{quality_iteration}-judge.json"
            report_path.write_text(
                json.dumps(latest_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            progress(
                "NIFDU visual judge: "
                f"{latest_report['score']}/100; "
                f"critical={latest_report['critical_issues']}; "
                f"unmet={latest_report['unmet_requirements']}; "
                + ("ACCEPT" if latest_report["accepted"] else "REPAIR")
            )

            if latest_report["accepted"]:
                break

            if quality_iteration >= QUALITY_LOOPS:
                if best_html is not None:
                    temporary = target.with_suffix(".html.tmp")
                    temporary.write_text(
                        best_html,
                        encoding="utf-8",
                    )
                    temporary.replace(target)
                    progress(
                        "Restored best verified candidate after bounded "
                        "quality-gate failure"
                    )

                progress(
                    "NIFDU visual quality gate failed after "
                    f"{QUALITY_LOOPS} bounded iteration(s); project not certified"
                )
                return None

            repair_html = html
            repair_report = latest_report
            repair_screenshot = screenshot

            if (
                best_rank is not None
                and candidate_rank < best_rank
                and best_html is not None
                and best_report is not None
                and best_screenshot is not None
            ):
                progress(
                    "NIFDU repair candidate regressed; preserving and "
                    "repairing from the best verified candidate"
                )
                repair_html = best_html
                repair_report = best_report
                repair_screenshot = best_screenshot

            repaired = _nifdu_visual_repair(
                adaptive=adaptive,
                original_request=original_request,
                html=repair_html,
                report=repair_report,
                screenshot=repair_screenshot,
                iteration=quality_iteration,
                progress=progress,
            )
            temporary = target.with_suffix(".html.tmp")
            temporary.write_text(repaired, encoding="utf-8")
            temporary.replace(target)
            progress(
                f"NIFDU visual repair wrote {target} "
                f"({target.stat().st_size} bytes)"
            )

        from sophyane import execution_runtime as runtime
        progress("NIFDU visual quality gate passed; opening final demo")
        ok, result = runtime.execute_action(
            {"type": "open_browser"},
            workspace,
            progress,
        )
        if not ok:
            return None

        return (
            "Updated, visually judged, repaired when required, and opened "
            "the provider-generated browser project.\n\n"
            f"Workspace: {workspace}\nFile: index.html\n\nExecution evidence:\n"
            f"- index.html exists ({target.stat().st_size} bytes)\n"
            f"- Recovered with {attempts} continuation attempt(s)\n"
            "- HTML body/script structure verified\n"
            "- JavaScript bracket structure verified\n"
            f"- NIFDU visual quality score: {latest_report['score']}/100\n"
            f"- NIFDU visual critical issues: {latest_report['critical_issues']}\n"
            f"- NIFDU visual unmet requirements: {latest_report['unmet_requirements']}\n"
            f"- Visual judge reports: {quality_root}\n"
            f"- {result}"
        )

    recovered._sophyane_partial_recovery = True  # type: ignore[attr-defined]
    adaptive._one_shot_browser_artifact = recovered
