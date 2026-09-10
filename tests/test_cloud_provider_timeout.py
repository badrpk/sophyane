from __future__ import annotations

from types import SimpleNamespace

from sophyane.runtime_cloud_timeout_patch import install_cloud_timeout_patch


def test_cloud_provider_defaults_to_120_seconds(monkeypatch):
    seen: list[int] = []

    class FakeTUI:
        @property
        def small_local(self):
            return False

        def call_provider(self, message: str, *, timeout: int = 60):
            seen.append(timeout)
            return message

    module = SimpleNamespace(ObservableTUI=FakeTUI)
    install_cloud_timeout_patch(module)

    assert FakeTUI().call_provider("build") == "build"
    assert seen == [120]


def test_local_provider_remains_at_60_seconds():
    seen: list[int] = []

    class FakeTUI:
        @property
        def small_local(self):
            return True

        def call_provider(self, message: str, *, timeout: int = 60):
            seen.append(timeout)
            return message

    module = SimpleNamespace(ObservableTUI=FakeTUI)
    install_cloud_timeout_patch(module)

    FakeTUI().call_provider("build")
    assert seen == [60]


def test_explicit_timeout_is_preserved():
    seen: list[int] = []

    class FakeTUI:
        @property
        def small_local(self):
            return False

        def call_provider(self, message: str, *, timeout: int = 60):
            seen.append(timeout)
            return message

    module = SimpleNamespace(ObservableTUI=FakeTUI)
    install_cloud_timeout_patch(module)

    FakeTUI().call_provider("build", timeout=30)
    assert seen == [30]


def test_nifdu_browser_defaults_to_600_seconds():
    seen: list[int] = []

    class FakeTUI:
        config = {"provider": "nifdu_browser"}

        @property
        def small_local(self):
            return False

        def call_provider(self, message: str, *, timeout: int = 60):
            seen.append(timeout)
            return message

    module = SimpleNamespace(ObservableTUI=FakeTUI)
    install_cloud_timeout_patch(module)

    assert FakeTUI().call_provider("build") == "build"
    assert seen == [600]


def test_nifdu_session_provider_overrides_generic_config(monkeypatch):
    seen: list[int] = []

    monkeypatch.setenv("SOPHYANE_SESSION_PROVIDER", "nifdu_browser")
    monkeypatch.setenv("SOPHYANE_SESSION_MODE", "nifdu_llm")

    class FakeTUI:
        config = {"provider": "generic"}

        @property
        def small_local(self):
            return False

        def call_provider(self, message: str, *, timeout: int = 60):
            seen.append(timeout)
            return message

    module = SimpleNamespace(ObservableTUI=FakeTUI)
    install_cloud_timeout_patch(module)

    assert FakeTUI().call_provider("build") == "build"
    assert seen == [600]


def test_explicit_timeout_still_beats_nifdu_session(monkeypatch):
    seen: list[int] = []

    monkeypatch.setenv("SOPHYANE_SESSION_PROVIDER", "nifdu_browser")
    monkeypatch.setenv("SOPHYANE_SESSION_MODE", "nifdu_llm")

    class FakeTUI:
        config = {"provider": "generic"}

        @property
        def small_local(self):
            return False

        def call_provider(self, message: str, *, timeout: int = 60):
            seen.append(timeout)
            return message

    module = SimpleNamespace(ObservableTUI=FakeTUI)
    install_cloud_timeout_patch(module)

    FakeTUI().call_provider("build", timeout=37)
    assert seen == [37]


def test_local_compare_profile_defaults_to_180_seconds(monkeypatch):
    seen: list[int] = []

    monkeypatch.setenv(
        "SOPHYANE_LOCAL_PROFILE",
        "compare",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_MODE",
        "local_llm",
    )
    monkeypatch.setenv(
        "SOPHYANE_SESSION_PROVIDER",
        "local_gguf",
    )

    class FakeTUI:
        config = {"provider": "local_gguf"}

        @property
        def small_local(self):
            return True

        def call_provider(self, message: str, *, timeout: int = 60):
            seen.append(timeout)
            return message

    module = SimpleNamespace(
        ObservableTUI=FakeTUI
    )

    install_cloud_timeout_patch(module)

    assert (
        FakeTUI().call_provider("compare")
        == "compare"
    )
    assert seen == [180]


def test_explicit_timeout_still_beats_local_compare_profile(
    monkeypatch,
):
    seen: list[int] = []

    monkeypatch.setenv(
        "SOPHYANE_LOCAL_PROFILE",
        "compare",
    )

    class FakeTUI:
        config = {"provider": "local_gguf"}

        @property
        def small_local(self):
            return True

        def call_provider(self, message: str, *, timeout: int = 60):
            seen.append(timeout)
            return message

    module = SimpleNamespace(
        ObservableTUI=FakeTUI
    )

    install_cloud_timeout_patch(module)

    FakeTUI().call_provider(
        "compare",
        timeout=47,
    )

    assert seen == [47]
