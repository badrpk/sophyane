"""Short-lived least-privilege capability leases."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
import time


@dataclass(frozen=True)
class CapabilityLease:
    lease_id: str
    capability: str
    scope: str
    issued_at: float
    expires_at: float
    max_uses: int


@dataclass
class _LeaseState:
    lease: CapabilityLease
    uses: int = 0
    revoked: bool = False


class CapabilityLeaseManager:
    def __init__(
        self,
        *,
        clock=None,
    ) -> None:
        self._clock = (
            clock
            if clock is not None
            else time.monotonic
        )

        self._leases: dict[
            str,
            _LeaseState,
        ] = {}

    def issue(
        self,
        *,
        capability: str,
        scope: str,
        ttl_seconds: float = 30.0,
        max_uses: int = 1,
    ) -> CapabilityLease:
        ttl = max(
            0.1,
            min(
                300.0,
                float(
                    ttl_seconds
                ),
            ),
        )

        uses = max(
            1,
            min(
                100,
                int(
                    max_uses
                ),
            ),
        )

        now = float(
            self._clock()
        )

        lease = CapabilityLease(
            lease_id=secrets.token_hex(
                12
            ),
            capability=str(
                capability
            ),
            scope=str(
                scope
            ),
            issued_at=now,
            expires_at=(
                now
                + ttl
            ),
            max_uses=uses,
        )

        self._leases[
            lease.lease_id
        ] = _LeaseState(
            lease=lease
        )

        return lease

    def authorize(
        self,
        lease_id: str,
        *,
        capability: str,
        scope: str,
        consume: bool = True,
    ) -> bool:
        state = self._leases.get(
            lease_id
        )

        if state is None:
            return False

        lease = state.lease

        if state.revoked:
            return False

        if (
            float(
                self._clock()
            )
            > lease.expires_at
        ):
            return False

        if (
            lease.capability
            != capability
        ):
            return False

        if lease.scope != scope:
            return False

        if state.uses >= lease.max_uses:
            return False

        if consume:
            state.uses += 1

        return True

    def revoke(
        self,
        lease_id: str,
    ) -> None:
        state = self._leases.get(
            lease_id
        )

        if state is not None:
            state.revoked = True

    def remaining_uses(
        self,
        lease_id: str,
    ) -> int:
        state = self._leases.get(
            lease_id
        )

        if state is None:
            return 0

        return max(
            0,
            state.lease.max_uses
            - state.uses,
        )


__all__ = [
    "CapabilityLease",
    "CapabilityLeaseManager",
]
