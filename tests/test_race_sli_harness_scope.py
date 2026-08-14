from __future__ import annotations

from pathlib import Path

import pytest

from sophyane.sli_harness_orchestrator import (
    is_harness_execution_request,
)


GENERIC_CONSTRUCTION_REQUESTS = (
    (
        "Build an automated indexing daemon that watches local filesystem "
        "directories, chunks documentation or source files, generates "
        "embeddings, updates a local vector store such as Chroma or FAISS, "
        "and executes retrieval validation benchmarks."
    ),
    (
        "Instruct an AI harness to parse incoming raw payload examples or "
        "rough functional descriptions, autonomously derive strict JSON "
        "schemas or OpenAPI specifications, and generate functional backend "
        "mocking stubs or test client scripts."
    ),
    (
        "Create a FastAPI backend with REST endpoints, request validation, "
        "persistent storage, and integration tests."
    ),
)


@pytest.mark.parametrize(
    "case",
    GENERIC_CONSTRUCTION_REQUESTS,
)
def test_generic_software_construction_does_not_take_repair_harness_fast_path(
    case: str,
) -> None:
    """
    Generic software construction belongs to the adaptive race.

    The SLI harness fast path is intentionally bounded to software
    repair/test execution that its deterministic/local coding machinery
    can actually claim.
    """
    assert is_harness_execution_request(case) is False


@pytest.mark.parametrize(
    "case",
    (
        (
            "Repair the existing production code after a pytest "
            "test failure and re-run verification."
        ),
        (
            "Fix the existing Python source file. The pytest tests are "
            "authoritative; inspect the traceback and re-run verification."
        ),
        (
            "Patch the production code to resolve the failing test suite "
            "and run tests again."
        ),
    ),
)
def test_explicit_repair_requests_still_take_harness_fast_path(
    case: str,
) -> None:
    assert is_harness_execution_request(case) is True
