"""Unit tests for the primitives behind My Words' numbering/pagination/
bulk-selection (spec section 22): utils.text.parse_number_list and
utils.pagination.paginate. handlers/words.py builds position->id mapping
on top of these two functions - see its module docstring."""
from __future__ import annotations

import pytest

from utils.pagination import paginate
from utils.text import parse_number_list


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("3", [3]),
        ("2,5,7", [2, 5, 7]),
        ("2, 5, 7", [2, 5, 7]),
        ("2 5 7", [2, 5, 7]),
        ("2,  5   7", [2, 5, 7]),
        ("  4  ", [4]),
    ],
)
def test_parse_number_list_accepts_comma_and_space_separators(raw, expected):
    assert parse_number_list(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "abc", "2,abc,3", "-1", "0", "1,-2"])
def test_parse_number_list_rejects_invalid_input(raw):
    with pytest.raises(ValueError):
        parse_number_list(raw)


def test_paginate_slices_pages_of_the_requested_size():
    items = list(range(1, 26))  # 25 items
    page1 = paginate(items, 1, page_size=10)
    page3 = paginate(items, 3, page_size=10)

    assert page1.items == tuple(range(1, 11))
    assert page1.has_previous is False
    assert page1.has_next is True

    assert page3.items == tuple(range(21, 26))
    assert page3.total_pages == 3
    assert page3.has_previous is True
    assert page3.has_next is False


def test_paginate_clamps_out_of_range_page_numbers():
    items = list(range(1, 6))
    assert paginate(items, 99, page_size=10).page_number == 1
    assert paginate(items, 0, page_size=10).page_number == 1


def test_paginate_empty_list_returns_one_empty_page():
    page = paginate([], 1, page_size=10)
    assert page.items == ()
    assert page.total_pages == 1
    assert page.has_previous is False
    assert page.has_next is False


def test_numbering_maps_position_to_item_within_a_page_not_globally():
    """Simulates what handlers/words.py does: cache page.items as
    position -> id, and resolving position 3 must mean the 3rd item of
    THIS page, not the 3rd item overall."""
    items = [f"word-{i}" for i in range(1, 26)]
    page2 = paginate(items, 2, page_size=10)

    ids_on_page = list(page2.items)
    position = 3
    assert ids_on_page[position - 1] == "word-13"  # page 2 starts at item 11
