"""Built-in objective coding-contract nodes."""

from __future__ import annotations

from .base import CodingContract
from .descending_sort import DescendingSortContract
from .descending_unique_sort import DescendingUniqueSortContract
from .median import MedianContract
from .sort import SortContract
from .unique_sort import UniqueSortContract


def builtin_coding_contracts(
) -> tuple[CodingContract, ...]:
    """Return built-in contract nodes in deterministic matching order."""
    return (
        MedianContract(),
        SortContract(),
        DescendingSortContract(),
        UniqueSortContract(),
        DescendingUniqueSortContract(),
    )


__all__ = [
    "CodingContract",
    "DescendingSortContract",
    "DescendingUniqueSortContract",
    "MedianContract",
    "SortContract",
    "UniqueSortContract",
    "builtin_coding_contracts",
]
