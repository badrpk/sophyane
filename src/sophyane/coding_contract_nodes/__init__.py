"""Built-in objective coding-contract nodes."""

from __future__ import annotations

from .base import CodingContract
from .descending_sort import DescendingSortContract
from .median import MedianContract
from .sort import SortContract


def builtin_coding_contracts(
) -> tuple[CodingContract, ...]:
    """Return built-in contract nodes in deterministic matching order."""
    return (
        MedianContract(),
        SortContract(),
        DescendingSortContract(),
    )


__all__ = [
    "CodingContract",
    "DescendingSortContract",
    "MedianContract",
    "SortContract",
    "builtin_coding_contracts",
]
