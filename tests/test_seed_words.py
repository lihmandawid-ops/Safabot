"""Regression test for database/seed_words.py's pronunciation/phonetic
fields (settings-improvements stage section 13). A prior bug had these
two fields swapped for every non-Hebrew entry that set both: the
DB.pronunciation column (the one utils.word_display actually shows to
users) held a raw IPA string like "/ɡoʊ/", and the readable
transliteration ("goh") sat unused in .phonetic instead - meaning every
seeded word showed raw IPA symbols, exactly the "IPA-only" pronunciation
the spec says must not be the norm.
"""
from __future__ import annotations

from database.seed_words import SEED_WORDS


def test_no_seed_entry_has_ipa_in_the_readable_pronunciation_field():
    offenders = [
        f"{entry['language_code']}:{entry['word']}"
        for entry in SEED_WORDS
        if entry.get("pronunciation") and entry["pronunciation"].strip().startswith("/")
    ]
    assert offenders == []


def test_seed_entries_with_phonetic_have_it_look_like_ipa():
    """The inverse check: wherever .phonetic is set, it should be the
    IPA-style value (delimited by slashes), not the readable one."""
    for entry in SEED_WORDS:
        phonetic = entry.get("phonetic")
        if phonetic:
            assert phonetic.strip().startswith("/") and phonetic.strip().endswith("/"), (
                f"{entry['language_code']}:{entry['word']} has a non-IPA-looking .phonetic: {phonetic!r}"
            )


async def test_seeded_word_pronunciation_is_readable_after_seeding(session):
    from database.repositories import words as words_repo
    from database.seed_words import seed_words

    await seed_words(session)
    await session.commit()

    word = await words_repo.find_exact(session, language_code="en", normalized_word="go")
    assert word is not None
    assert word.pronunciation == "goh"
    assert word.phonetic == "/ɡoʊ/"
