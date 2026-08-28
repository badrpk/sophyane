from __future__ import annotations

from dataclasses import dataclass


_ALLOWED_FAMILIES = frozenset(
    {
        "targeted",
        "regression",
        "security",
        "held_out",
    }
)


@dataclass(
    frozen=True,
    slots=True,
)
class ChallengeRequest:
    family: str
    challenge_id: str
    learned_from_epoch: int
    evaluator_identity: str

    def __post_init__(self) -> None:
        if self.family not in _ALLOWED_FAMILIES:
            raise ValueError(
                "unsupported challenge family: "
                + self.family
            )

        if not self.challenge_id:
            raise ValueError(
                "challenge_id must not be empty"
            )

        if self.learned_from_epoch < 1:
            raise ValueError(
                "learned_from_epoch must be >= 1"
            )

        if not self.evaluator_identity:
            raise ValueError(
                "evaluator_identity must not be empty"
            )


class RedQueenExecutionPolicy:
    """Bounded evaluator-controlled challenge selection.

    The policy may request additional challenge families.

    It cannot:
    - declare a challenge passed/failed;
    - mutate source promotion state;
    - execute arbitrary commands;
    - invent test output.

    A separate trusted executor must map challenge IDs to actual
    executable validation and return real evidence.
    """

    def __init__(
        self,
        *,
        max_requests: int = 4,
    ) -> None:
        if max_requests < 1:
            raise ValueError(
                "max_requests must be >= 1"
            )

        self.max_requests = max_requests

        self._learned: dict[
            str,
            ChallengeRequest,
        ] = {}

    @staticmethod
    def _challenge_id(
        family: str,
    ) -> str:
        return (
            "red-queen::"
            + family
            + "::supplemental-v1"
        )

    def learn(
        self,
        *,
        failures: tuple[str, ...],
        epoch: int,
        evaluator_identity: str,
    ) -> None:
        for raw in failures:
            family = (
                "held_out"
                if raw.startswith("held-out")
                else raw.split(
                    " ",
                    1,
                )[0]
            )

            if family not in _ALLOWED_FAMILIES:
                continue

            if family in self._learned:
                continue

            self._learned[family] = (
                ChallengeRequest(
                    family=family,
                    challenge_id=(
                        self._challenge_id(
                            family
                        )
                    ),
                    learned_from_epoch=epoch,
                    evaluator_identity=(
                        evaluator_identity
                    ),
                )
            )

    def requests(
        self,
    ) -> tuple[ChallengeRequest, ...]:
        ordered = sorted(
            self._learned.values(),
            key=lambda item: (
                item.learned_from_epoch,
                item.family,
                item.challenge_id,
            ),
        )

        return tuple(
            ordered[
                : self.max_requests
            ]
        )

    def learned_families(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            request.family
            for request in self.requests()
        )
