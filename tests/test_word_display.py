"""Tests for utils/word_display.py's card rendering (DeepSeek-integration
spec section 6's exact card layout) and keyboards/dictionary.py's button
list (pronunciation is now inline on the card, not a separate button).
"""
from __future__ import annotations

from types import SimpleNamespace

from keyboards.dictionary import word_card_keyboard
from services.word_service import WordCard
from utils.word_display import render_word_card_text


def _card(**word_fields):
    defaults = dict(language_code="en", word="appointment", part_of_speech=None, pronunciation=None, definition=None)
    defaults.update(word_fields)
    word = SimpleNamespace(**defaults)
    translations = [
        SimpleNamespace(language_code="ru", translation="встреча", usage_note=None),
        SimpleNamespace(language_code="ru", translation="запись", usage_note=None),
    ]
    examples = [SimpleNamespace(example_text="I have an appointment tomorrow.", translation="У меня завтра встреча.")]
    return WordCard(word=word, translations=translations, examples=examples, forms=[])


def test_card_shows_one_line_per_translation():
    text = render_word_card_text(_card())
    assert "🇷🇺 встреча" in text
    assert "🇷🇺 запись" in text


def test_card_shows_part_of_speech_header_and_value():
    text = render_word_card_text(_card(part_of_speech="noun"))
    assert "📚 Часть речи:" in text
    assert "существительное" in text


def test_card_omits_part_of_speech_section_when_unset():
    text = render_word_card_text(_card(part_of_speech=None))
    assert "📚 Часть речи:" not in text


def test_card_shows_pronunciation_header_with_value_or_placeholder():
    with_pron = render_word_card_text(_card(pronunciation="/əˈpɔɪntmənt/"))
    assert "🔊 Произношение:" in with_pron
    assert "/əˈpɔɪntmənt/" in with_pron

    without_pron = render_word_card_text(_card(pronunciation=None))
    assert "🔊 Произношение:" in without_pron
    assert "пока недоступно" in without_pron


def test_card_shows_definition_header_with_value_or_placeholder():
    with_def = render_word_card_text(_card(definition="an arrangement to meet someone"))
    assert "📖 Значение:" in with_def
    assert "an arrangement to meet someone" in with_def

    without_def = render_word_card_text(_card(definition=None))
    assert "📖 Значение:" in without_def
    assert "пока недоступно" in without_def


def test_card_shows_example_with_new_emoji():
    text = render_word_card_text(_card())
    assert "💬 Пример:" in text
    assert "I have an appointment tomorrow." in text


def test_word_card_keyboard_has_no_separate_pronounce_button():
    markup = word_card_keyboard(42)
    all_callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert not any(cb.startswith("card:pronounce:") for cb in all_callbacks)
    assert "card:add:42" in all_callbacks
    assert "card:usage:42" in all_callbacks
    assert "card:forms:42" in all_callbacks


def test_status_label_follows_interface_language_not_always_russian():
    """settings-improvements stage: utils/word_display.py used to hardcode
    _LANG = "ru" for every label (status, part of speech, section
    headers) regardless of who was looking at the card - the same class
    of bug fixed everywhere else in this stage."""
    from utils.i18n import set_current_language
    from utils.word_display import status_label

    set_current_language("ru")
    assert status_label("mastered") == "✅ Выучено"
    set_current_language("en")
    assert status_label("mastered") == "✅ Mastered"
    set_current_language("ru")


def test_card_headers_follow_interface_language():
    from utils.i18n import set_current_language

    set_current_language("en")
    text = render_word_card_text(_card(pronunciation="/əˈpɔɪntmənt/"))
    assert "🔊 Pronunciation:" in text
    assert "/əˈpɔɪntmənt/" in text
    set_current_language("ru")
