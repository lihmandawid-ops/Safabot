"""Shared-dictionary tests: Word creation, search, cross-language
isolation, translations, verb forms (spec section 22)."""
from __future__ import annotations

from database.repositories import words as words_repo
from services import word_service


async def _make_word(session, *, language_code="en", word="improve", **fields):
    created, _ = await word_service.get_or_create_word(session, language_code=language_code, word=word, **fields)
    return created


async def test_create_word_persists_expected_fields(session):
    word = await _make_word(
        session, word="improve", part_of_speech="verb", is_verb=True, difficulty="intermediate", category="education"
    )
    await session.commit()

    fetched = await words_repo.find_exact(session, language_code="en", normalized_word="improve")
    assert fetched is not None
    assert fetched.word == "improve"
    assert fetched.part_of_speech == "verb"
    assert fetched.is_verb is True
    assert fetched.category == "education"


async def test_get_or_create_word_does_not_duplicate(session):
    first, created_first = await word_service.get_or_create_word(session, language_code="en", word="Improve")
    second, created_second = await word_service.get_or_create_word(session, language_code="en", word="improve")

    assert created_first is True
    assert created_second is False
    assert first.id == second.id


async def test_same_word_text_in_different_languages_does_not_collide(session):
    """Section 1's explicit example: "gehen" in German vs a same-spelled
    row in another language must be independent rows."""
    de_word, _ = await word_service.get_or_create_word(session, language_code="de", word="gehen")
    en_word, _ = await word_service.get_or_create_word(session, language_code="en", word="gehen")

    assert de_word.id != en_word.id
    assert de_word.language_code == "de"
    assert en_word.language_code == "en"

    found_in_de = await words_repo.find_exact(session, language_code="de", normalized_word="gehen")
    found_in_en = await words_repo.find_exact(session, language_code="en", normalized_word="gehen")
    assert found_in_de.id == de_word.id
    assert found_in_en.id == en_word.id


async def test_search_exact_match_takes_priority(session):
    await _make_word(session, language_code="en", word="go")
    await _make_word(session, language_code="en", word="going")

    results = await word_service.search_words(session, language_code="en", query="go")
    assert len(results) == 1
    assert results[0].word == "go"


async def test_search_partial_match_when_no_exact(session):
    await _make_word(session, language_code="en", word="improve")
    await _make_word(session, language_code="en", word="improvement")

    results = await word_service.search_words(session, language_code="en", query="improv")
    assert {w.word for w in results} == {"improve", "improvement"}


async def test_search_is_scoped_to_language(session):
    await _make_word(session, language_code="en", word="gehen")
    await _make_word(session, language_code="de", word="gehen")

    en_results = await word_service.search_words(session, language_code="en", query="gehen")
    assert len(en_results) == 1
    assert en_results[0].language_code == "en"


async def test_search_returns_nothing_for_blank_query(session):
    assert await word_service.search_words(session, language_code="en", query="   ") == []


async def test_word_can_have_multiple_translations(session):
    word = await _make_word(session, language_code="en", word="appointment")
    await words_repo.add_translation(session, word_id=word.id, language_code="ru", translation="встреча")
    await words_repo.add_translation(session, word_id=word.id, language_code="ru", translation="запись")
    await session.commit()

    card = await word_service.get_word_card(session, word_id=word.id, translation_language="ru")
    assert {t.translation for t in card.translations} == {"встреча", "запись"}


async def test_get_word_card_filters_translations_by_language(session):
    word = await _make_word(session, language_code="en", word="go")
    await words_repo.add_translation(session, word_id=word.id, language_code="ru", translation="идти")
    await words_repo.add_translation(session, word_id=word.id, language_code="de", translation="gehen")

    card = await word_service.get_word_card(session, word_id=word.id, translation_language="ru")
    assert [t.translation for t in card.translations] == ["идти"]


async def test_word_card_definition_is_per_translation_language(session):
    """Root cause of "перевод и пояснение не меняются после смены языка
    интерфейса": Word.definition is a single column shared by every user
    studying that word - build_word_card must prefer the definition
    attached to the matching WordTranslation row, never the shared
    Word-level one, once a per-language definition exists."""
    word = await _make_word(session, language_code="en", word="go", definition="EN shared legacy definition")
    await words_repo.add_translation(
        session, word_id=word.id, language_code="ru", translation="идти", definition="Значение по-русски",
    )
    await words_repo.add_translation(
        session, word_id=word.id, language_code="de", translation="gehen",  # no per-language definition yet
    )

    ru_card = await word_service.get_word_card(session, word_id=word.id, translation_language="ru")
    assert ru_card.definition == "Значение по-русски"

    # No per-language definition for "de" yet - falls back to the legacy
    # shared Word.definition rather than showing nothing.
    de_card = await word_service.get_word_card(session, word_id=word.id, translation_language="de")
    assert de_card.definition == "EN shared legacy definition"


async def test_get_verb_forms(session):
    word = await _make_word(session, language_code="en", word="go", is_verb=True)
    await words_repo.add_form(session, word_id=word.id, form_type="past", form="went")
    await words_repo.add_form(session, word_id=word.id, form_type="gerund", form="going")
    await session.commit()

    forms = await words_repo.get_verb_forms(session, word.id)
    assert {f.form for f in forms} == {"went", "going"}


async def test_word_examples(session):
    word = await _make_word(session, language_code="en", word="go")
    await words_repo.add_example(session, word_id=word.id, example_text="I go to school.", translation="Я иду в школу.")
    await session.commit()

    card = await word_service.get_word_card(session, word_id=word.id)
    assert card.examples[0].example_text == "I go to school."
