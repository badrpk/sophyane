

# SOPHYANE_TEST_PROVIDER_AVAILABILITY_ISOLATION_V1
#
# Provider availability is intentionally persistent in production, but pytest
# must never read or mutate the user's real runtime state. Every test receives
# an independent temporary availability file. Tests that explicitly override
# SOPHYANE_PROVIDER_AVAILABILITY_FILE remain free to do so.
import pytest


@pytest.fixture(autouse=True)
def _isolate_provider_availability_state(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "SOPHYANE_PROVIDER_AVAILABILITY_FILE",
        str(tmp_path / "provider_availability.json"),
    )




# SOPHYANE_TEST_TRANSIENT_SESSION_ENV_ISOLATION_V1
#
# Startup/session selection intentionally mutates process environment in
# production. Tests share one process, so transient authority must never leak
# between unrelated cases or arrive from the invoking shell.
import os


_TRANSIENT_SOPHYANE_TEST_KEYS = (
    "SOPHYANE_SESSION_MODE",
    "SOPHYANE_SESSION_PROVIDER",
    "SOPHYANE_SESSION_MODEL",
    "SOPHYANE_SESSION_TIMEOUT",
    "SOPHYANE_SLI_GRAPH",
    "SOPHYANE_SLI_ONLY",
    "SOPHYANE_SLI_CONTINUOUS",
    "SOPHYANE_TOPIC_LEARNING",
    "SOPHYANE_LOCAL_ONLY",
    "SOPHYANE_DISABLE_CLOUD_FALLBACK",
)


@pytest.fixture(autouse=True)
def _isolate_transient_sophyane_session_environment(
    monkeypatch,
):
    for key in _TRANSIENT_SOPHYANE_TEST_KEYS:
        monkeypatch.delenv(
            key,
            raising=False,
        )

    yield

    # Production code sometimes mutates os.environ directly rather than
    # through monkeypatch. Remove that state before the next test.
    for key in _TRANSIENT_SOPHYANE_TEST_KEYS:
        os.environ.pop(
            key,
            None,
        )
