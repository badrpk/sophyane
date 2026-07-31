"""Central CapabilityRegistry for Sophyane request routing.

Priority model
--------------
Specs are sorted by ascending ``priority`` (then capability_id).
**Lower number wins.** Use the Priority tier constants so new entries
do not invent magic numbers.

    Priority.CRITICAL_GAP   (10)  unavailable external integrations
    Priority.LOCAL_DETERMINISTIC (40)  filesystem, etc.
    Priority.LOCAL_TOOLS    (50)  shell / browser / python
    Priority.FALLBACK_CHAT  (1000) general chat only

Matching rules
--------------
1. Walk specs in priority order.
2. First matcher that returns True owns the request.
3. If that capability is unavailable → route ``gap`` + message.
4. ``general_chat`` must remain the last registered matcher.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable


class Priority:
    """Named tiers — lower value = earlier match."""

    CRITICAL_GAP = 10
    EXTERNAL_GAP = 20
    ACCOUNT_API_GAP = 25
    LOCAL_DETERMINISTIC = 40
    LOCAL_TOOLS = 50
    FALLBACK_CHAT = 1000


@dataclass(frozen=True)
class CapabilityMatch:
    capability_id: str
    route: str  # chat | execution | gap | filesystem
    available: bool
    priority: int
    message: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class CapabilitySpec:
    capability_id: str
    title: str
    route: str
    available: bool
    priority: int
    match: Callable[[str], bool]
    gap_message: str | None = None
    tags: tuple[str, ...] = ()


def _norm(message: str) -> str:
    return " ".join(str(message or "").lower().split())


class CapabilityRegistry:
    def __init__(self) -> None:
        self._specs: list[CapabilitySpec] = []

    def register(self, spec: CapabilitySpec) -> None:
        self._specs = [s for s in self._specs if s.capability_id != spec.capability_id]
        self._specs.append(spec)
        self._sort()

    def _sort(self) -> None:
        # Stable: priority ASC, then id for determinism.
        self._specs.sort(key=lambda s: (int(s.priority), s.capability_id))

    def resolve(self, message: str) -> CapabilityMatch | None:
        text = _norm(message)
        if not text:
            return None

        for spec in self._specs:
            try:
                matched = bool(spec.match(text))
            except Exception:
                continue
            if not matched:
                continue

            if not spec.available:
                return CapabilityMatch(
                    capability_id=spec.capability_id,
                    route="gap",
                    available=False,
                    priority=spec.priority,
                    message=spec.gap_message
                    or f"{spec.title} is not configured in this session.",
                    meta={"tags": list(spec.tags), "tier": _tier_name(spec.priority)},
                )

            # general_chat is last-resort only: if we matched it, still return it
            return CapabilityMatch(
                capability_id=spec.capability_id,
                route=spec.route,
                available=True,
                priority=spec.priority,
                message=None,
                meta={"tags": list(spec.tags), "tier": _tier_name(spec.priority)},
            )
        return None

    def list_capabilities(self) -> list[dict[str, Any]]:
        return [
            {
                "id": s.capability_id,
                "title": s.title,
                "route": s.route,
                "available": s.available,
                "priority": s.priority,
                "tier": _tier_name(s.priority),
                "tags": list(s.tags),
            }
            for s in self._specs
        ]


def _tier_name(priority: int) -> str:
    if priority <= Priority.CRITICAL_GAP:
        return "critical_gap"
    if priority <= Priority.EXTERNAL_GAP:
        return "external_gap"
    if priority <= Priority.ACCOUNT_API_GAP:
        return "account_api_gap"
    if priority <= Priority.LOCAL_DETERMINISTIC:
        return "local_deterministic"
    if priority <= Priority.LOCAL_TOOLS:
        return "local_tools"
    return "fallback_chat"


_REGISTRY: CapabilityRegistry | None = None


def get_registry() -> CapabilityRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = CapabilityRegistry()
        _register_defaults(_REGISTRY)
    return _REGISTRY


def resolve_capability(message: str) -> CapabilityMatch | None:
    return get_registry().resolve(message)


def gap_or_direct_reply(message: str) -> str | None:
    hit = resolve_capability(message)
    if hit is not None and not hit.available and hit.message:
        return hit.message
    return None


def route_for_message(message: str, default: str = "chat") -> str:
    hit = resolve_capability(message)
    if hit is None:
        return default
    if not hit.available or hit.route in {"gap", "chat"}:
        return "chat"
    if hit.route == "filesystem":
        return "execution"
    return hit.route


def is_execution_capability(message: str) -> bool | None:
    """True/False if registry decides; None if only general_chat matched."""
    hit = resolve_capability(message)
    if hit is None:
        return None
    if hit.capability_id == "general_chat":
        return None  # let TUI/brain keep their own heuristics
    if not hit.available:
        return False
    return hit.route in {"execution", "filesystem"}


# ----- match helpers -----

def _re(*parts: str) -> re.Pattern[str]:
    return re.compile("|".join(parts), re.I)


_EMAIL = _re(
    r"\bemail\b", r"\be-mail\b", r"\binbox\b", r"\bgmail\b", r"\boutlook\b",
    r"\bimap\b", r"\bsmtp\b", r"\blast\s+mail\b", r"\bmy\s+mail\b",
)
_EMAIL_CUES = (
    "last", "latest", "recent", "show", "read", "open", "check",
    "what", "fetch", "get", "inbox", "unread",
)
_CALENDAR = _re(r"\bcalendar\b", r"\bschedule\b", r"\bmeeting\b", r"\bappointment\b")
_TELEGRAM = _re(r"\btelegram\b")
_SLACK = _re(r"\bslack\b")
_GITHUB = _re(r"\bgithub\b", r"\bpull request\b", r"\bprs?\b", r"\bgist\b")
_DISCORD = _re(r"\bdiscord\b")
_WHATSAPP = _re(r"\bwhatsapp\b")
_BROWSER = _re(r"\bbrowser\b", r"\bopen\s+url\b", r"\bhttp://", r"\bhttps://")
_SHELL = _re(r"\bshell\b", r"\bbash\b", r"\brun\s+command\b", r"\bterminal\b")
_PYTHON = _re(r"\bpython\b", r"\bpip\b", r"\bpytest\b", r"\bvenv\b")
_FS_LIST = _re(r"\blist\s+(folders?|directories)\b", r"\bshow\s+(folders?|directories)\b")
_FS_COUNT = _re(r"\b(count|how many|number of)\s+(folders?|directories)\b")
_FS_HOME = _re(r"\bhome\s+directory\b", r"\bmy\s+home\b")


def _match_email(text: str) -> bool:
    """Gap only when user asks about email AND IMAP connector cannot handle it."""
    text = " ".join(str(text or "").lower().split())
    if not text:
        return False
    if any(
        p in text
        for p in (
            "send email",
            "send an email",
            "compose email",
            "draft an email",
            "email to ",
            "mail to ",
        )
    ) or ("send" in text and "email" in text):
        return False
    if not _EMAIL.search(text):
        return False
    cues = any(c in text for c in _EMAIL_CUES) or "my email" in text or "my e-mail" in text
    if not cues:
        return False
    try:
        from sophyane.connectors.runtime import resolve_connector_op
        match = resolve_connector_op(text)
        if match is not None and match.available:
            return False
    except Exception:
        pass
    return True



def _match_fs(text: str) -> bool:
    if _FS_LIST.search(text) or _FS_COUNT.search(text):
        return True
    return bool(
        _FS_HOME.search(text)
        and any(x in text for x in ("list", "count", "folders", "directories"))
    )


def _register_defaults(reg: CapabilityRegistry) -> None:
    gaps = (
        (
            "email",
            "Email inbox",
            Priority.CRITICAL_GAP,
            _match_email,
            "I cannot read your email inbox from this session.\n\n"
            "No email integration is configured (IMAP/Gmail/Outlook API).\n\n"
            "Options:\n"
            "1. Paste the message (or subject/body) here for summary or reply help.\n"
            "2. Point me at a local export in the workspace (.eml / .mbox / .txt).\n"
            "3. Ask me to scaffold a local IMAP or Gmail read-only script.\n\n"
            "I will not enter the software-build loop for inbox access without a connector.",
        ),
        (
            "calendar",
            "Calendar",
            Priority.EXTERNAL_GAP,
            lambda t: bool(_CALENDAR.search(t)),
            "Calendar access is not configured in this session. Paste event details "
            "or ask to scaffold a Google/Outlook calendar connector.",
        ),
        (
            "telegram",
            "Telegram",
            Priority.EXTERNAL_GAP,
            lambda t: bool(_TELEGRAM.search(t)),
            "Telegram is not connected. Paste the message text or ask to scaffold a bot/API client.",
        ),
        (
            "slack",
            "Slack",
            Priority.EXTERNAL_GAP,
            lambda t: bool(_SLACK.search(t)),
            "Slack is not connected. Paste the thread text or ask to scaffold a Slack API client.",
        ),
        (
            "discord",
            "Discord",
            Priority.EXTERNAL_GAP,
            lambda t: bool(_DISCORD.search(t)),
            "Discord is not connected in this session.",
        ),
        (
            "whatsapp",
            "WhatsApp",
            Priority.EXTERNAL_GAP,
            lambda t: bool(_WHATSAPP.search(t)),
            "WhatsApp is not connected in this session.",
        ),
        (
            "github_remote",
            "GitHub account API",
            Priority.ACCOUNT_API_GAP,
            lambda t: bool(_GITHUB.search(t))
            and any(x in t for x in ("my pr", "my issues", "notifications", "review request")),
            "GitHub account API access is not configured. Use local git in the workspace, "
            "or provide a token/integration later.",
        ),
    )
    for cid, title, pri, matcher, msg in gaps:
        reg.register(
            CapabilitySpec(
                capability_id=cid,
                title=title,
                route="gap",
                available=False,
                priority=pri,
                match=matcher,
                gap_message=msg,
                tags=("external", "integration"),
            )
        )

    reg.register(
        CapabilitySpec(
            capability_id="filesystem",
            title="Filesystem inspection",
            route="filesystem",
            available=True,
            priority=Priority.LOCAL_DETERMINISTIC,
            match=_match_fs,
            tags=("local", "deterministic"),
        )
    )
    reg.register(
        CapabilitySpec(
            capability_id="shell",
            title="Constrained shell",
            route="execution",
            available=True,
            priority=Priority.LOCAL_TOOLS,
            match=lambda t: bool(_SHELL.search(t)),
            tags=("local",),
        )
    )
    reg.register(
        CapabilitySpec(
            capability_id="browser",
            title="Browser / URL",
            route="execution",
            available=True,
            priority=Priority.LOCAL_TOOLS,
            match=lambda t: bool(_BROWSER.search(t)),
            tags=("local",),
        )
    )
    reg.register(
        CapabilitySpec(
            capability_id="python",
            title="Python tooling",
            route="execution",
            available=True,
            priority=Priority.LOCAL_TOOLS,
            match=lambda t: bool(_PYTHON.search(t))
            and any(x in t for x in ("run", "install", "test", "script", "module")),
            tags=("local",),
        )
    )
    reg.register(
        CapabilitySpec(
            capability_id="email_send",
            title="Outbound email",
            route="gap",
            available=False,
            priority=Priority.CRITICAL_GAP,
            match=lambda t: (
                "send email" in t
                or "send an email" in t
                or ("send" in t and "email" in t and " to " in t)
                or "compose email" in t
                or "draft an email" in t
            ),
            gap_message=(
                "I cannot send email from this session.\n\n"
                "Outbound SMTP is not configured (read-only IMAP only).\n\n"
                "Options:\n"
                "1. I can draft the message text here for you to paste into Gmail.\n"
                "2. Ask to scaffold a local SMTP send script (you supply SMTP secrets).\n"
                "3. For Saudia tickets, check saudia.com or the app for ISB → SFO flexible dates.\n"
            ),
        )
    )
    # Must be last: catch-all. is_execution_capability ignores this id.
    reg.register(
        CapabilitySpec(
            capability_id="general_chat",
            title="General chat",
            route="chat",
            available=True,
            priority=Priority.FALLBACK_CHAT,
            match=lambda t: len(t) > 0,
            tags=("chat",),
        )
    )


def reset_registry_for_tests() -> CapabilityRegistry:
    """Rebuild singleton (unit tests only)."""
    global _REGISTRY
    _REGISTRY = CapabilityRegistry()
    _register_defaults(_REGISTRY)
    return _REGISTRY

# native_status registered via ensure_native_status_capability()
