import json
from pathlib import Path

import pytest

from sophyane.capability_manager import (
    Capability,
    CapabilityManager,
    default_capability_manager,
)


def capability(
    name: str,
    supports: set[str],
    *,
    priority: int = 50,
    enabled: bool = True,
    provider: str = "",
) -> Capability:
    return Capability(
        name=name,
        description=f"{name} capability",
        supports=frozenset(supports),
        priority=priority,
        enabled=enabled,
        provider=provider,
    )


def test_register_and_discover_capability() -> None:
    manager = CapabilityManager()
    manager.register(capability("Browser", {"HTML", "CSS"}))

    stored = manager.get(" browser ")

    assert stored is not None
    assert stored.name == "browser"
    assert stored.supports == frozenset({"html", "css"})


def test_duplicate_registration_requires_replace() -> None:
    manager = CapabilityManager()
    manager.register(capability("python", {"python"}))

    with pytest.raises(ValueError):
        manager.register(capability("python", {"testing"}))

    manager.register(
        capability("python", {"python", "testing"}),
        replace=True,
    )

    assert manager.get("python").supports == frozenset(
        {"python", "testing"}
    )


def test_selection_prefers_complete_high_priority_match() -> None:
    manager = CapabilityManager()
    manager.register(
        capability(
            "basic-browser",
            {"html", "css"},
            priority=40,
        )
    )
    manager.register(
        capability(
            "advanced-browser",
            {"html", "css", "javascript"},
            priority=90,
        )
    )

    match = manager.select({"html", "css"})

    assert match is not None
    assert match.capability.name == "advanced-browser"
    assert match.missing == frozenset()


def test_disabled_capability_is_not_selected() -> None:
    manager = CapabilityManager()
    manager.register(
        capability(
            "browser",
            {"html"},
            priority=100,
            enabled=False,
        )
    )
    manager.register(
        capability(
            "fallback",
            {"html"},
            priority=10,
        )
    )

    match = manager.select({"html"})

    assert match is not None
    assert match.capability.name == "fallback"


def test_capability_can_be_enabled_and_disabled() -> None:
    manager = CapabilityManager()
    manager.register(capability("browser", {"html"}))

    manager.set_enabled("browser", False)
    assert manager.get("browser").enabled is False

    manager.set_enabled("browser", True)
    assert manager.get("browser").enabled is True


def test_provider_filtering() -> None:
    manager = CapabilityManager()
    manager.register(
        capability(
            "local-python",
            {"python"},
            priority=70,
            provider="local",
        )
    )
    manager.register(
        capability(
            "gemini-python",
            {"python"},
            priority=90,
            provider="gemini",
        )
    )

    match = manager.select({"python"}, provider="local")

    assert match is not None
    assert match.capability.name == "local-python"


def test_handler_invocation() -> None:
    manager = CapabilityManager()
    manager.register(
        capability("adder", {"calculation"}),
        handler=lambda left, right: left + right,
    )

    assert manager.invoke("adder", 2, 3) == 5


def test_disabled_handler_cannot_run() -> None:
    manager = CapabilityManager()
    manager.register(
        capability(
            "dangerous",
            {"shell"},
            enabled=False,
        ),
        handler=lambda: "ran",
    )

    with pytest.raises(RuntimeError, match="disabled"):
        manager.invoke("dangerous")


def test_registry_round_trip(tmp_path: Path) -> None:
    manager = CapabilityManager()
    manager.register(
        capability(
            "browser",
            {"html", "css"},
            priority=90,
            provider="gemini",
        )
    )

    path = manager.save(tmp_path / "capabilities.json")
    loaded = CapabilityManager.load(path)

    restored = loaded.get("browser")

    assert restored is not None
    assert restored.priority == 90
    assert restored.provider == "gemini"
    assert restored.supports == frozenset({"html", "css"})

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1


def test_default_catalogue_selects_browser() -> None:
    manager = default_capability_manager()
    match = manager.select({"html", "javascript"})

    assert match is not None
    assert match.capability.name == "browser"


def test_partial_matching_can_be_requested() -> None:
    manager = CapabilityManager()
    manager.register(
        capability(
            "browser",
            {"html", "css"},
        )
    )

    assert manager.select(
        {"html", "javascript"},
        require_all=True,
    ) is None

    match = manager.select(
        {"html", "javascript"},
        require_all=False,
    )

    assert match is not None
    assert match.matched == frozenset({"html"})
    assert match.missing == frozenset({"javascript"})
