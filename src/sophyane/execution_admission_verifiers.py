"""Pure verifier evidence for unified pre-execution admission.

Evidence names in this module are claims about checks actually performed here.
The module has no execution, provider, lease, network, or filesystem mutation
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sophyane.capability_flow_graph import default_capability_graph
from sophyane.execution_admission import ExecutionAdmission


@dataclass(frozen=True)
class AdmissionVerification:
    allowed: bool
    verifier_evidence: frozenset[str]
    reason: str
    workspace: Path | None = None


def _resolved_workspace(
    workspace: str | Path | None,
) -> Path | None:
    if workspace is None:
        return None

    try:
        return Path(workspace).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None


def verify_execution_admission(
    admission: ExecutionAdmission,
    *,
    workspace: str | Path | None,
) -> AdmissionVerification:
    """Verify the admission schema and its workspace boundary declaration."""

    if not isinstance(admission, ExecutionAdmission):
        return AdmissionVerification(
            allowed=False,
            verifier_evidence=frozenset(),
            reason="invalid admission type",
        )

    if (
        not isinstance(admission.runtime_family, str)
        or not admission.runtime_family.strip()
        or not isinstance(admission.policy_capabilities, tuple)
        or not admission.policy_capabilities
        or not all(
            isinstance(item, str) and bool(item.strip())
            for item in admission.policy_capabilities
        )
        or not isinstance(admission.read_only, bool)
        or not isinstance(admission.side_effects, frozenset)
        or not all(
            isinstance(item, str) and bool(item.strip())
            for item in admission.side_effects
        )
    ):
        return AdmissionVerification(
            allowed=False,
            verifier_evidence=frozenset(),
            reason="invalid admission schema",
        )

    graph = default_capability_graph()

    try:
        descriptors = tuple(
            graph.descriptor(capability)
            for capability in admission.policy_capabilities
        )
    except KeyError:
        return AdmissionVerification(
            allowed=False,
            verifier_evidence=frozenset(),
            reason="unknown policy capability",
        )

    declared_effects = frozenset(
        effect
        for descriptor in descriptors
        for effect in descriptor.side_effects
    )

    if not declared_effects.issubset(admission.side_effects):
        return AdmissionVerification(
            allowed=False,
            verifier_evidence=frozenset(),
            reason="admission omits policy side effect",
        )

    if admission.read_only and admission.side_effects:
        return AdmissionVerification(
            allowed=False,
            verifier_evidence=frozenset(),
            reason="read-only admission declares side effects",
        )

    evidence = {"schema"}

    requires_workspace_boundary = any(
        "workspace_boundary" in descriptor.required_verifiers
        for descriptor in descriptors
    )

    resolved = _resolved_workspace(workspace)

    if requires_workspace_boundary:
        if resolved is None:
            return AdmissionVerification(
                allowed=False,
                verifier_evidence=frozenset(evidence),
                reason="workspace boundary requires a valid workspace",
            )

        #
        # The boundary represented here is the canonical root itself.
        # This does not claim that an arbitrary child path is safe. Any
        # executor accepting a child path must still constrain that path
        # beneath this root before touching the filesystem.
        #
        evidence.add("workspace_boundary")

    return AdmissionVerification(
        allowed=True,
        verifier_evidence=frozenset(evidence),
        reason="verified",
        workspace=resolved,
    )


__all__ = [
    "AdmissionVerification",
    "verify_execution_admission",
]
