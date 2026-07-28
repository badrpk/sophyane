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
