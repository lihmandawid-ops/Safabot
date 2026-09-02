"""Language table / seeding tests (spec sections 3, 17)."""
from __future__ import annotations

from database.repositories import languages as languages_repo
from database.seed import LANGUAGE_SEED_DATA, seed_languages
from utils.languages import SUPPORTED_LANGUAGES


async def test_seed_languages_creates_all_eight(session):
    # The `session` fixture already calls seed_languages() once during setup.
    active = await languages_repo.get_all_active(session)
    assert {lang.code for lang in active} == {row["code"] for row in LANGUAGE_SEED_DATA}
    assert len(active) == 8


async def test_seed_languages_is_idempotent(session):
    before = await languages_repo.get_all_active(session)
    await seed_languages(session)
    await session.commit()
    after = await languages_repo.get_all_active(session)

    assert len(before) == len(after) == 8


async def test_get_by_code_returns_expected_language(session):
    ru = await languages_repo.get_by_code(session, "ru")
    assert ru is not None
    assert ru.name == "Russian"
    assert ru.native_name == "Русский"


async def test_get_by_code_returns_none_for_unknown_code(session):
    assert await languages_repo.get_by_code(session, "xx") is None


def test_seed_data_matches_keyboard_language_list():
    """Guards against the DB seed list and the keyboards' display list
    (utils/languages.py) drifting apart."""
    seed_codes = {row["code"] for row in LANGUAGE_SEED_DATA}
    display_codes = {lang.code for lang in SUPPORTED_LANGUAGES}
    assert seed_codes == display_codes
