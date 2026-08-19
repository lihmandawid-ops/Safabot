"""Spaced-repetition algorithm tests (spec section 32, with special
attention called out for repetition_service per that same section).

Skipped until services/repetition_service.py is implemented in Stage 7 -
see DEVELOPMENT RULES (spec section 34) and the interval ladder documented
in services/repetition_service.py. Kept here as a checklist so the next
stage knows exactly what to cover.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Repetition algorithm arrives in Stage 7 (Repetition).")


def test_again_shortens_the_interval_and_resets_progress():
    ...


def test_hard_increases_the_interval_slightly():
    ...


def test_good_advances_one_ladder_step():
    ...


def test_easy_advances_more_than_one_ladder_step():
    ...


def test_mastered_is_reached_after_the_final_ladder_step():
    ...


def test_next_review_date_is_computed_from_the_new_interval():
    ...
