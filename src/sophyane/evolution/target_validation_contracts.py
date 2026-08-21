"""Authoritative BADRPK validator contracts.

V2F converts V2E discovery evidence into explicit, HEAD-pinned requirements.

A contract does not make an unavailable validator optional.

PASS requires:

* the target HEAD matches the contract;
* every required validator is still discoverable;
* every required validator is runnable;
* every required validator passes.

Runnable subsets may still execute diagnostically when other required
validators are unavailable, but such a result can never PASS.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .target_validation_topology import (
    ValidationNode,
    ValidationTopology,
)


@dataclass(frozen=True)
class ValidatorRequirement:
    kind: str
    relative_cwd: str


@dataclass(frozen=True)
class TargetValidationContract:
    target_name: str
    source_head: str
    required: tuple[ValidatorRequirement, ...]


@dataclass(frozen=True)
class ResolvedValidationContract:
    contract: TargetValidationContract
    matched: tuple[ValidationNode, ...]
    missing: tuple[ValidatorRequirement, ...]
    unexpected: tuple[ValidationNode, ...]

    @property
    def unavailable(self) -> tuple[ValidationNode, ...]:
        return tuple(
            node
            for node in self.matched
            if not node.runnable
        )

    @property
    def runnable(self) -> tuple[ValidationNode, ...]:
        return tuple(
            node
            for node in self.matched
            if node.runnable
        )


CONTRACTS: dict[str, TargetValidationContract] = {
    "Droidra": TargetValidationContract(
        target_name="Droidra",
        source_head=(
            "44451aa2b6eaec2d07225aa8bf6bdb8ad31e02dc"
        ),
        required=(
            ValidatorRequirement(
                "gradle-test",
                ".",
            ),
        ),
    ),

    "rangoons": TargetValidationContract(
        target_name="rangoons",
        source_head=(
            "2afea347b2b9e84e585bbd0a402647117c79fb53"
        ),
        required=(
            ValidatorRequirement(
                "gradle-test",
                "RangoonsCast/CastApp/android",
            ),
            ValidatorRequirement(
                "python-pytest",
                "RangoonsCore",
            ),
            ValidatorRequirement(
                "cargo-test",
                "RangoonsCore",
            ),
            ValidatorRequirement(
                "npm-test",
                (
                    "RangoonsCore/"
                    "HuobzcoinWallet/"
                    "HuobzcoinWallet"
                ),
            ),
            ValidatorRequirement(
                "cargo-test",
                (
                    "RangoonsCore/"
                    "crates/common_utils"
                ),
            ),
            ValidatorRequirement(
                "npm-test",
                "RangoonsCore/huobz-frontend",
            ),
            ValidatorRequirement(
                "python-pytest",
                "RangoonsLang",
            ),
            ValidatorRequirement(
                "python-pytest",
                "RangoonsLang/core_features",
            ),
            ValidatorRequirement(
                "npm-test",
                "apps/live",
            ),
        ),
    ),

    "xerus": TargetValidationContract(
        target_name="xerus",
        source_head=(
            "77b037987951c8f353ded38a045115a7aa11e30b"
        ),
        required=(
            ValidatorRequirement(
                "python-pytest",
                ".",
            ),
        ),
    ),

    "sophyane": TargetValidationContract(
        target_name="sophyane",
        source_head=(
            "41aa7e84a2c822481e85bd69b27e570795738876"
        ),
        required=(
            ValidatorRequirement(
                "python-pytest",
                ".",
            ),
        ),
    ),

    "shmry": TargetValidationContract(
        target_name="shmry",
        source_head=(
            "c5cd116213cab87a42057cc539b440691907d600"
        ),
        required=(
            ValidatorRequirement(
                "python-pytest",
                ".",
            ),
        ),
    ),

    "Veyron": TargetValidationContract(
        target_name="Veyron",
        source_head=(
            "3ac1b3a01df8b6a54fc8bdd93763e637227201ec"
        ),
        required=(
            ValidatorRequirement(
                "python-pytest",
                ".",
            ),
        ),
    ),
}


def get_validation_contract(
    name: str,
) -> TargetValidationContract:
    try:
        return CONTRACTS[name]
    except KeyError as error:
        raise ValueError(
            f"No authoritative validator contract for {name!r}"
        ) from error


def _relative(
    repo: Path,
    node: ValidationNode,
) -> str:
    path = node.cwd.resolve().relative_to(
        repo.resolve()
    )

    if path == Path("."):
        return "."

    return path.as_posix()


def resolve_contract(
    topology: ValidationTopology,
    contract: TargetValidationContract,
) -> ResolvedValidationContract:
    if topology.target_name != contract.target_name:
        raise ValueError(
            "Topology/contract target mismatch: "
            f"{topology.target_name!r} != "
            f"{contract.target_name!r}"
        )

    indexed = {
        (
            node.kind,
            _relative(
                topology.repo,
                node,
            ),
        ): node
        for node in topology.nodes
    }

    matched: list[ValidationNode] = []
    missing: list[ValidatorRequirement] = []

    required_keys = {
        (
            item.kind,
            item.relative_cwd,
        )
        for item in contract.required
    }

    for requirement in contract.required:
        node = indexed.get(
            (
                requirement.kind,
                requirement.relative_cwd,
            )
        )

        if node is None:
            missing.append(
                requirement
            )
        else:
            matched.append(
                node
            )

    unexpected = tuple(
        node
        for key, node in indexed.items()
        if key not in required_keys
    )

    return ResolvedValidationContract(
        contract=contract,
        matched=tuple(
            matched
        ),
        missing=tuple(
            missing
        ),
        unexpected=unexpected,
    )
