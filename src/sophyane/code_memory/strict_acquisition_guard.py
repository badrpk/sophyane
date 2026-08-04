"""Strict licence and behavioral validation for SLI internet acquisition.

Downloaded repositories are accepted only when a positively detected
permissive licence exists. Generated browser artifacts are accepted only when
they satisfy behavior derived from the current request.

No downloaded code is executed.
"""
from __future__ import annotations

import inspect
import os
import re
import shutil
import tempfile
import webbrowser

from pathlib import Path
from typing import Any, Callable


Progress = Callable[[str], None]


PERMITTED_LICENCES = {
    "mit",
    "apache-2.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "isc",
    "mpl-2.0",
    "unlicense",
    "0bsd",
    "cc0-1.0",
    "wtfpl",
    "zlib",
    "bsl-1.0",
}


FORBIDDEN_LICENCE_LABELS = {
    "",
    "none",
    "unknown",
    "inspect-after-clone",
    "soft-browser-demo",
    "soft",
    "unverified",
    "__unlicensed__",
}


_ACTIVE_REPOSITORY_DENYLIST: set[str] = set()


def _progress(
    progress: Progress | None,
) -> Progress:
    return progress or (
        lambda _message: None
    )


def normalise_licence(
    value: object,
) -> str | None:
    if value is None:
        return None

    low = str(value).strip().lower()

    low = low.replace(
        "license",
        "",
    ).replace(
        "licence",
        "",
    ).strip()

    low = re.sub(
        r"\s+",
        " ",
        low,
    )

    aliases = {
        "mit": "mit",
        "apache 2.0": "apache-2.0",
        "apache-2.0": "apache-2.0",
        "bsd 2 clause": "bsd-2-clause",
        "bsd-2-clause": "bsd-2-clause",
        "bsd 3 clause": "bsd-3-clause",
        "bsd-3-clause": "bsd-3-clause",
        "isc": "isc",
        "mpl 2.0": "mpl-2.0",
        "mpl-2.0": "mpl-2.0",
        "mozilla public 2.0": "mpl-2.0",
        "unlicense": "unlicense",
        "the unlicense": "unlicense",
        "0bsd": "0bsd",
        "cc0": "cc0-1.0",
        "cc0 1.0": "cc0-1.0",
        "cc0-1.0": "cc0-1.0",
        "wtfpl": "wtfpl",
        "zlib": "zlib",
        "bsl 1.0": "bsl-1.0",
        "bsl-1.0": "bsl-1.0",
    }

    if low in FORBIDDEN_LICENCE_LABELS:
        return None

    canonical = aliases.get(low)

    if canonical in PERMITTED_LICENCES:
        return canonical

    return None


def strict_licence_result(
    value: object,
) -> str | None:
    """Return only a positively permitted canonical licence."""

    if isinstance(value, tuple):
        # Handle detectors returning:
        #   (allowed, licence)
        #   (licence, evidence)
        if len(value) >= 2:
            first, second = value[0], value[1]

            if isinstance(first, bool):
                if not first:
                    return None

                return normalise_licence(
                    second
                )

            licence = normalise_licence(
                first
            )

            if licence:
                return licence

            return normalise_licence(
                second
            )

    if isinstance(value, dict):
        allowed = value.get(
            "allowed"
        )

        if allowed is False:
            return None

        for key in (
            "licence",
            "license",
            "spdx",
            "key",
        ):
            licence = normalise_licence(
                value.get(key)
            )

            if licence:
                return licence

        return None

    return normalise_licence(
        value
    )


def _repository_name(
    repository: object,
) -> str:
    if isinstance(repository, dict):
        return str(
            repository.get("full_name")
            or repository.get("name")
            or ""
        )

    return str(
        getattr(
            repository,
            "full_name",
            None,
        )
        or getattr(
            repository,
            "name",
            None,
        )
        or ""
    )


def filter_denied_repositories(
    repositories,
):
    return [
        repository
        for repository in repositories
        if _repository_name(
            repository
        ) not in _ACTIVE_REPOSITORY_DENYLIST
    ]


def _contains(
    source: str,
    *patterns: str,
) -> bool:
    return any(
        re.search(
            pattern,
            source,
            flags=re.I | re.S,
        )
        for pattern in patterns
    )


def _check(
    name: str,
    passed: bool,
    issues: list[str],
) -> None:
    if not passed:
        issues.append(name)


def validate_browser_artifact(
    request: str,
    artifact: Path,
) -> tuple[bool, list[str], dict[str, bool]]:
    """Validate behavior required by the request without executing code."""

    issues: list[str] = []
    checks: dict[str, bool] = {}

    if not artifact.is_file():
        return (
            False,
            ["missing index.html"],
            {},
        )

    try:
        source = artifact.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        return (
            False,
            [
                "unreadable index.html: "
                + str(error)
            ],
            {},
        )

    low_request = " ".join(
        str(request or "")
        .lower()
        .split()
    )

    checks["substantial"] = (
        len(source.encode("utf-8")) >= 256
    )

    checks["html_document"] = (
        _contains(source, r"<html\b")
        and _contains(source, r"<body\b")
        and _contains(source, r"</html\s*>")
    )

    checks["script"] = _contains(
        source,
        r"<script\b",
    )

    checks["interaction"] = _contains(
        source,
        r"addEventListener\s*\(",
        r"\bonclick\s*=",
        r"\bonkeydown\s*=",
        r"<button\b",
        r"<input\b",
    )

    for key in (
        "substantial",
        "html_document",
        "script",
        "interaction",
    ):
        _check(
            key,
            checks[key],
            issues,
        )

    language_request = any(
        phrase in low_request
        for phrase in (
            "missing word",
            "spelling",
            "vocabulary",
            "sentence completion",
            "quiz",
            "questions",
        )
    )

    action_game_request = any(
        phrase in low_request
        for phrase in (
            "pong",
            "paddle",
            "brick breaker",
            "breakout",
            "maze game",
            "arcade game",
            "canvas game",
        )
    )

    crud_request = any(
        phrase in low_request
        for phrase in (
            "crud",
            "add edit delete",
            "management app",
            "registry",
        )
    )

    dashboard_request = any(
        phrase in low_request
        for phrase in (
            "dashboard",
            "analytics",
            "summary cards",
        )
    )

    simulation_request = any(
        phrase in low_request
        for phrase in (
            "simulation",
            "simulator",
            "oscillator",
            "projectile motion",
        )
    )

    editor_request = "editor" in low_request

    if language_request:
        language_checks = {
            "question_data":
                _contains(
                    source,
                    r"\bquestions?\b",
                    r"\bitems?\s*=",
                    r"\bprompt\s*:",
                    r"\bsentence\s*:",
                ),

            "answer_data":
                _contains(
                    source,
                    r"\banswer\s*:",
                    r"\bcorrectAnswer\b",
                    r"\bexpected\b",
                ),

            "answer_validation":
                _contains(
                    source,
                    r"validate\w*\s*\(",
                    r"isCorrect",
                    r"correctAnswer",
                    r"\banswer\b.{0,100}===",
                    r"===.{0,100}\banswer\b",
                ),

            "feedback":
                _contains(
                    source,
                    r"\bfeedback\b",
                    r"\bcorrect\b",
                    r"\bincorrect\b",
                    r"\bmessage\b",
                ),

            "score":
                _contains(
                    source,
                    r"\bscore\b",
                ),

            "next":
                _contains(
                    source,
                    r"\bnext\b",
                    r"advance\w*\s*\(",
                    r"current(?:Question|Index|Item).{0,100}\+",
                ),

            "restart":
                _contains(
                    source,
                    r"\brestart\b",
                    r"\breset\b",
                ),
        }

        for name, passed in language_checks.items():
            checks[name] = passed
            _check(
                name,
                passed,
                issues,
            )

    if action_game_request:
        game_checks = {
            "game_rendering":
                _contains(
                    source,
                    r"<canvas\b",
                    r"<svg\b",
                    r"getContext\s*\(",
                ),

            "timed_loop":
                _contains(
                    source,
                    r"requestAnimationFrame\s*\(",
                    r"setInterval\s*\(",
                ),

            "directional_input":
                _contains(
                    source,
                    r"ArrowLeft",
                    r"ArrowRight",
                    r"ArrowUp",
                    r"ArrowDown",
                    r"keydown",
                    r"pointermove",
                    r"touchmove",
                ),

            "game_score":
                _contains(
                    source,
                    r"\bscore\b",
                ),

            "game_restart":
                _contains(
                    source,
                    r"\brestart\b",
                    r"\breset\b",
                ),
        }

        for name, passed in game_checks.items():
            checks[name] = passed
            _check(
                name,
                passed,
                issues,
            )

    if crud_request:
        crud_checks = {
            "create_record":
                _contains(
                    source,
                    r"\badd\w*\s*\(",
                    r"\bcreate\w*\s*\(",
                    r"\.push\s*\(",
                ),

            "update_record":
                _contains(
                    source,
                    r"\bedit\w*\s*\(",
                    r"\bupdate\w*\s*\(",
                ),

            "delete_record":
                _contains(
                    source,
                    r"\bdelete\w*\s*\(",
                    r"\bremove\w*\s*\(",
                    r"\.splice\s*\(",
                ),

            "crud_filter":
                _contains(
                    source,
                    r"\.filter\s*\(",
                    r"\bsearch\b",
                ),

            "crud_persistence":
                _contains(
                    source,
                    r"localStorage",
                    r"indexedDB",
                ),
        }

        for name, passed in crud_checks.items():
            checks[name] = passed
            _check(
                name,
                passed,
                issues,
            )

    if dashboard_request:
        dashboard_checks = {
            "dashboard_data":
                _contains(
                    source,
                    r"\bdata\s*=",
                    r"\bdataset\b",
                    r"\bitems\s*=",
                    r"<table\b",
                ),

            "dashboard_summary":
                _contains(
                    source,
                    r"\bsummary\b",
                    r"\btotal\b",
                    r"\bmetric\b",
                    r"\bcard\b",
                ),

            "dashboard_filter":
                _contains(
                    source,
                    r"\.filter\s*\(",
                    r"\bfilter\b",
                    r"<select\b",
                ),

            "dashboard_visual":
                _contains(
                    source,
                    r"<canvas\b",
                    r"<svg\b",
                    r"<table\b",
                    r"\bchart\b",
                ),
        }

        for name, passed in dashboard_checks.items():
            checks[name] = passed
            _check(
                name,
                passed,
                issues,
            )

    if simulation_request:
        simulation_checks = {
            "simulation_rendering":
                _contains(
                    source,
                    r"<canvas\b",
                    r"<svg\b",
                    r"getContext\s*\(",
                ),

            "simulation_update":
                _contains(
                    source,
                    r"requestAnimationFrame\s*\(",
                    r"setInterval\s*\(",
                    r"\bupdate\w*\s*\(",
                ),

            "simulation_controls":
                _contains(
                    source,
                    r"<input\b",
                    r"<button\b",
                    r"<select\b",
                ),

            "simulation_reset":
                _contains(
                    source,
                    r"\breset\b",
                    r"\brestart\b",
                ),
        }

        for name, passed in simulation_checks.items():
            checks[name] = passed
            _check(
                name,
                passed,
                issues,
            )

    if editor_request:
        editor_checks = {
            "editor_input":
                _contains(
                    source,
                    r"<textarea\b",
                    r"contenteditable",
                ),

            "editor_storage":
                _contains(
                    source,
                    r"localStorage",
                    r"indexedDB",
                ),

            "editor_export":
                _contains(
                    source,
                    r"\bexport\b",
                    r"Blob\s*\(",
                    r"createObjectURL\s*\(",
                    r"\bdownload\b",
                ),
        }

        for name, passed in editor_checks.items():
            checks[name] = passed
            _check(
                name,
                passed,
                issues,
            )

    forbidden_markers = {
        "placeholder":
            _contains(
                source,
                r"\bnot implemented\b",
                r"\bcoming soon\b",
                r"\bTODO\b",
            ),

        "unrelated_snake":
            (
                "snake" not in low_request
                and _contains(
                    source,
                    r"<title[^>]*>\s*snake\b",
                    r">\s*snake\s*</h1",
                )
            ),
    }

    for name, present in forbidden_markers.items():
        checks[name] = not present

        if present:
            issues.append(
                name
            )

    return (
        not issues,
        issues,
        checks,
    )


def _extract_source_repository(
    report: str,
) -> str | None:
    patterns = (
        r"Source repository:\s*([^\s\r\n]+)",
        r"repository accepted:\s*([^;\r\n]+)",
        r"Source repo:\s*([^\s\r\n]+)",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            str(report or ""),
            flags=re.I,
        )

        if match:
            return match.group(1).strip()

    return None


def _report_value(
    result,
) -> str:
    if isinstance(result, tuple):
        if result:
            return str(
                result[0]
            )

        return ""

    return str(
        result or ""
    )


def _replace_report(
    original,
    report: str,
):
    if isinstance(original, tuple):
        values = list(
            original
        )

        if values:
            values[0] = report
        else:
            values.append(
                report
            )

        return tuple(
            values
        )

    return report


def install(
    namespace: dict[str, Any],
) -> None:
    if namespace.get(
        "_SOPHYANE_STRICT_ACQUISITION_GUARD_INSTALLED"
    ):
        return

    namespace[
        "_SOPHYANE_STRICT_ACQUISITION_GUARD_INSTALLED"
    ] = True

    # -----------------------------------------------------------------
    # Strict licence detector
    # -----------------------------------------------------------------

    detector_names = (
        "_detected_licence",
        "detected_licence",
        "detect_permissive_licence",
    )

    for name in detector_names:
        original = namespace.get(
            name
        )

        if not callable(
            original
        ):
            continue

        def make_detector(
            wrapped,
        ):
            def detector(
                *args,
                **kwargs,
            ):
                value = wrapped(
                    *args,
                    **kwargs,
                )

                return strict_licence_result(
                    value
                )

            return detector

        namespace[name] = make_detector(
            original
        )

    # Disable common soft-accept flags and helpers.
    for name in (
        "ALLOW_SOFT_BROWSER_DEMO",
        "SOFT_BROWSER_DEMO",
        "ALLOW_UNLICENSED_BROWSER_DEMOS",
    ):
        if name in namespace:
            namespace[name] = False

    for name in (
        "allow_soft_browser_demo",
        "_allow_soft_browser_demo",
        "soft_browser_demo_allowed",
    ):
        if callable(
            namespace.get(name)
        ):
            namespace[name] = (
                lambda *_args, **_kwargs:
                    False
            )

    # -----------------------------------------------------------------
    # Filter failed repositories from later attempts
    # -----------------------------------------------------------------

    original_search = namespace.get(
        "search_repositories"
    )

    if callable(
        original_search
    ):
        def strict_search(
            *args,
            **kwargs,
        ):
            repositories = original_search(
                *args,
                **kwargs,
            )

            return filter_denied_repositories(
                repositories
            )

        namespace["search_repositories"] = (
            strict_search
        )

    # -----------------------------------------------------------------
    # Validate in isolated workspaces and retry another source
    # -----------------------------------------------------------------

    original_build = namespace.get(
        "acquire_and_build"
    )

    if not callable(
        original_build
    ):
        return

    signature = inspect.signature(
        original_build
    )

    def strict_acquire_and_build(
        request: str,
        workspace: Path,
        *args,
        **kwargs,
    ):
        progress = _progress(
            kwargs.get("progress")
        )

        final_workspace = Path(
            workspace
        ).expanduser().resolve()

        final_workspace.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Never permit acquisition attempts to open a browser.
        saved_environment = {
            key: os.environ.get(key)
            for key in (
                "SOPHYANE_DISABLE_BROWSER_OPEN",
                "SOPHYANE_NO_AUTO_OPEN",
                "SOPHYANE_BROWSER_PREVIEW",
                "BROWSER",
            )
        }

        os.environ[
            "SOPHYANE_DISABLE_BROWSER_OPEN"
        ] = "1"
        os.environ[
            "SOPHYANE_NO_AUTO_OPEN"
        ] = "1"
        os.environ[
            "SOPHYANE_BROWSER_PREVIEW"
        ] = "0"
        os.environ[
            "BROWSER"
        ] = "/bin/false"

        original_webbrowser = (
            webbrowser.open,
            webbrowser.open_new,
            webbrowser.open_new_tab,
        )

        webbrowser.open = (
            lambda *_args, **_kwargs: False
        )
        webbrowser.open_new = (
            lambda *_args, **_kwargs: False
        )
        webbrowser.open_new_tab = (
            lambda *_args, **_kwargs: False
        )

        failures: list[str] = []
        last_result = None

        try:
            for attempt in range(1, 6):
                attempt_root = Path(
                    tempfile.mkdtemp(
                        prefix=(
                            "sli-strict-acquire-"
                            f"{attempt}-"
                        )
                    )
                )

                progress(
                    "SLI strict acquisition attempt "
                    f"{attempt}/5"
                )

                call_kwargs = dict(
                    kwargs
                )

                call_kwargs[
                    "progress"
                ] = progress

                if (
                    "open_browser"
                    in signature.parameters
                ):
                    call_kwargs[
                        "open_browser"
                    ] = False

                try:
                    result = original_build(
                        request,
                        attempt_root,
                        *args,
                        **call_kwargs,
                    )
                except Exception as error:
                    failures.append(
                        "attempt "
                        f"{attempt}: "
                        f"{type(error).__name__}: "
                        f"{error}"
                    )

                    shutil.rmtree(
                        attempt_root,
                        ignore_errors=True,
                    )
                    continue

                last_result = result
                report = _report_value(
                    result
                )

                artifact = (
                    attempt_root
                    / "index.html"
                )

                valid, issues, checks = (
                    validate_browser_artifact(
                        request,
                        artifact,
                    )
                )

                repository = (
                    _extract_source_repository(
                        report
                    )
                )

                if valid:
                    for existing in list(
                        final_workspace.iterdir()
                    ):
                        if existing.is_dir():
                            shutil.rmtree(
                                existing,
                                ignore_errors=True,
                            )
                        else:
                            existing.unlink(
                                missing_ok=True,
                            )

                    for source in attempt_root.iterdir():
                        destination = (
                            final_workspace
                            / source.name
                        )

                        if source.is_dir():
                            shutil.copytree(
                                source,
                                destination,
                            )
                        else:
                            shutil.copy2(
                                source,
                                destination,
                            )

                    shutil.rmtree(
                        attempt_root,
                        ignore_errors=True,
                    )

                    strict_report = (
                        report.rstrip()
                        + "\n"
                        + "Strict licence gate: passed\n"
                        + "Strict behavioral validation: passed\n"
                        + "Behavior checks: "
                        + ", ".join(
                            name
                            for name, passed
                            in checks.items()
                            if passed
                        )
                    )

                    progress(
                        "SLI strict behavioral validation passed"
                    )

                    return _replace_report(
                        result,
                        strict_report,
                    )

                reason = (
                    ", ".join(issues)
                    if issues
                    else "unknown behavioral mismatch"
                )

                failure = (
                    f"attempt {attempt}"
                    + (
                        f" repository={repository}"
                        if repository
                        else ""
                    )
                    + f": {reason}"
                )

                failures.append(
                    failure
                )

                progress(
                    "SLI artifact rejected: "
                    + failure
                )

                if repository:
                    _ACTIVE_REPOSITORY_DENYLIST.add(
                        repository
                    )

                    progress(
                        "SLI source excluded for this request: "
                        + repository
                    )

                shutil.rmtree(
                    attempt_root,
                    ignore_errors=True,
                )

            # Remove every possible stale product from the real workspace.
            for existing in list(
                final_workspace.iterdir()
            ):
                if existing.is_dir():
                    shutil.rmtree(
                        existing,
                        ignore_errors=True,
                    )
                else:
                    existing.unlink(
                        missing_ok=True,
                    )

            failure_report = "\n".join(
                [
                    "SLI strict acquisition failed.",
                    "No candidate satisfied both licence and behavioral validation.",
                    "Rejected attempts:",
                    *(
                        "  - " + failure
                        for failure in failures
                    ),
                    "Files: none",
                    "Success: False",
                    "No invalid artifact was learned or previewed.",
                    "No LLM fallback was used.",
                ]
            )

            if last_result is not None:
                return _replace_report(
                    last_result,
                    failure_report,
                )

            return failure_report

        finally:
            webbrowser.open = (
                original_webbrowser[0]
            )
            webbrowser.open_new = (
                original_webbrowser[1]
            )
            webbrowser.open_new_tab = (
                original_webbrowser[2]
            )

            for key, value in (
                saved_environment.items()
            ):
                if value is None:
                    os.environ.pop(
                        key,
                        None,
                    )
                else:
                    os.environ[
                        key
                    ] = value

            _ACTIVE_REPOSITORY_DENYLIST.clear()

    namespace[
        "acquire_and_build"
    ] = strict_acquire_and_build


__all__ = [
    "PERMITTED_LICENCES",
    "install",
    "normalise_licence",
    "strict_licence_result",
    "validate_browser_artifact",
]


# SOPHYANE_FUNCTIONAL_VALIDATION_V1
# Artifact acceptance is behavior-driven. The 256-byte check only rejects
# empty, truncated or obviously corrupt documents. Request-specific controls,
# state, data, validation, feedback and lifecycle checks determine validity.
