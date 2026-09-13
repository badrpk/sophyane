"""Persistent provider availability observations for bounded Mode-6 routing."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


_STATE_VERSION = 1

_RESET_TIME_RE = re.compile(
    r"(?:try\s+again\s+at|reset\s+at)"
    r"\s+"
    r"(?P<hour>\d{1,2})"
    r":"
    r"(?P<minute>\d{2})"
    r"\s*"
    r"(?P<ampm>[ap]\.?m\.?)",
    re.IGNORECASE,
)


def _now() -> datetime:
    return datetime.now().astimezone()


def state_path() -> Path:
    explicit = os.environ.get(
        "SOPHYANE_PROVIDER_AVAILABILITY_FILE",
        "",
    ).strip()

    if explicit:
        return Path(explicit).expanduser()

    state_home = os.environ.get(
        "XDG_STATE_HOME",
        "",
    ).strip()

    if state_home:
        return (
            Path(state_home).expanduser()
            / "sophyane"
            / "provider_availability.json"
        )

    return (
        Path.home()
        / ".local"
        / "state"
        / "sophyane"
        / "provider_availability.json"
    )


def _empty_state() -> dict[str, Any]:
    return {
        "version": _STATE_VERSION,
        "providers": {},
    }


def _load() -> dict[str, Any]:
    path = state_path()

    try:
        parsed = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )
    except (
        FileNotFoundError,
        OSError,
        ValueError,
        TypeError,
    ):
        return _empty_state()

    if not isinstance(parsed, dict):
        return _empty_state()

    providers = parsed.get(
        "providers"
    )

    if not isinstance(
        providers,
        dict,
    ):
        providers = {}

    return {
        "version": _STATE_VERSION,
        "providers": providers,
    }


def _save(state: dict[str, Any]) -> None:
    path = state_path()

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    os.replace(
        temporary,
        path,
    )


def _parse_retry_at(
    message: str,
    *,
    now: datetime,
) -> datetime | None:
    text = (
        str(message or "")
        .replace("\u202f", " ")
        .replace("\u00a0", " ")
    )

    match = _RESET_TIME_RE.search(
        text
    )

    if not match:
        return None

    hour = int(
        match.group("hour")
    )
    minute = int(
        match.group("minute")
    )

    if not (
        1 <= hour <= 12
        and 0 <= minute <= 59
    ):
        return None

    ampm = (
        match.group("ampm")
        .replace(".", "")
        .casefold()
    )

    if ampm == "pm" and hour != 12:
        hour += 12

    if ampm == "am" and hour == 12:
        hour = 0

    candidate = now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )

    if candidate <= now:
        candidate += timedelta(
            days=1
        )

    return candidate


def record_availability_failure(
    provider: str,
    error: BaseException,
    *,
    now: datetime | None = None,
) -> None:
    provider = str(
        provider or ""
    ).strip()

    if not provider:
        return

    now = now or _now()

    message = str(
        error
    )

    folded = message.casefold()

    quota = any(
        marker in folded
        for marker in (
            "usage limit",
            "quota",
            "too many requests",
            "http 429",
            "status 429",
        )
    )

    retry_at = (
        _parse_retry_at(
            message,
            now=now,
        )
        if quota
        else None
    )

    # Unknown quota reset times are not invented. They remain eligible for a
    # future bounded probe rather than receiving a fabricated clock time.
    if retry_at is None:
        return

    state = _load()

    state["providers"][
        provider
    ] = {
        "failure_class": (
            "quota"
            if quota
            else "availability"
        ),
        "observed_at": now.isoformat(),
        "retry_at": retry_at.isoformat(),
        "message": message[:2000],
    }

    _save(
        state
    )


def provider_block_info(
    provider: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    provider = str(
        provider or ""
    ).strip()

    if not provider:
        return None

    from sophyane.intelligence_authority import provider_intelligence_status

    if provider_intelligence_status(provider) == "PROVIDER_DISABLED":
        return {"failure_class": "policy_disabled", "status": "PROVIDER_DISABLED"}

    now = now or _now()

    state = _load()

    entry = state.get(
        "providers",
        {},
    ).get(
        provider
    )

    if not isinstance(
        entry,
        dict,
    ):
        return None

    retry_text = str(
        entry.get(
            "retry_at",
            "",
        )
        or ""
    )

    if not retry_text:
        return None

    try:
        retry_at = datetime.fromisoformat(
            retry_text
        )
    except ValueError:
        return None

    if retry_at.tzinfo is None:
        return None

    if now >= retry_at:
        return None

    return dict(
        entry
    )


def provider_available(
    provider: str,
    *,
    now: datetime | None = None,
) -> bool:
    return (
        provider_block_info(
            provider,
            now=now,
        )
        is None
    )


def record_provider_success(
    provider: str,
) -> None:
    provider = str(
        provider or ""
    ).strip()

    if not provider:
        return

    state = _load()

    providers = state.get(
        "providers",
        {},
    )

    if provider not in providers:
        return

    providers.pop(
        provider,
        None,
    )

    _save(
        state
    )
