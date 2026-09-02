"""Generic pagination helper (spec section 15: never dump hundreds of words
into one message).

Used by handlers that list many items (My Words in Stage 8, Dictionary
search results, etc.) to slice a sequence into pages and render
"⬅️ Предыдущая / ➡️ Следующая" navigation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, TypeVar

T = TypeVar("T")

PREVIOUS_LABEL = "⬅️ Предыдущая"
NEXT_LABEL = "➡️ Следующая"


@dataclass(frozen=True)
class Page(Sequence[T]):
    items: tuple[T, ...]
    page_number: int
    total_pages: int

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]

    @property
    def has_previous(self) -> bool:
        return self.page_number > 1

    @property
    def has_next(self) -> bool:
        return self.page_number < self.total_pages


def paginate(items: Sequence[T], page_number: int, page_size: int = 10) -> Page[T]:
    """Slice `items` into 1-indexed pages of `page_size` entries."""
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    total_pages = max(1, -(-len(items) // page_size))  # ceil division
    page_number = min(max(page_number, 1), total_pages)
    start = (page_number - 1) * page_size
    end = start + page_size
    return Page(items=tuple(items[start:end]), page_number=page_number, total_pages=total_pages)
