"""Canonical executable authority shared by RSI mutation boundaries."""
from enum import Enum

from sophyane.intelligence_authority import SOURCE_MUTATION_PROVIDERS

CODING_PROVIDER_ORDER = SOURCE_MUTATION_PROVIDERS
ORDINARY_MUTATION_PROVIDER_ORDER = (
    "codex_cli",
    "nifdu_browser",
    "local_gguf",
)


class Operation(str, Enum):
    READ_ONLY_OPERATION = "read_only"
    ORDINARY_WORKSPACE_MUTATION = "ordinary_workspace_mutation"
    SOPHYANE_SOURCE_MUTATION = "source_mutation"
    CANDIDATE_TEST_MUTATION = "test_mutation"
    PROMOTION_OPERATION = "promotion"
    ROLLBACK_OPERATION = "rollback"
    POLICY_MUTATION = "policy_mutation"
    JOURNAL_MUTATION = "journal_mutation"


class AuthorityViolation(PermissionError):
    """Terminal authority failure, never a provider availability failure."""


def require(provider: str, operation: Operation) -> None:
    if not isinstance(operation, Operation):
        raise AuthorityViolation("Unknown operation capability")
    if operation is Operation.ORDINARY_WORKSPACE_MUTATION:
        if provider in ORDINARY_MUTATION_PROVIDER_ORDER:
            return
    elif provider in CODING_PROVIDER_ORDER:
        return
    elif provider == "local_gguf" and operation is Operation.READ_ONLY_OPERATION:
        return
    raise AuthorityViolation(f"{provider!r} has no authority for {operation.value}")


def verify_mutation_authority(provider: str) -> bool:
    try:
        require(provider, Operation.SOPHYANE_SOURCE_MUTATION)
    except AuthorityViolation:
        return False
    return True
