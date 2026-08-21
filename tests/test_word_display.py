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
    defaults = dict(language_code="en", word="appointment", part_of_speech=None, pronunciation=None, phonetic=None, definition=None)
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


def test_format_pronunciation_combines_readable_and_ipa():
    """settings-improvements stage section 13: Word.phonetic (IPA) was
    being written by AI generation but never shown anywhere - it must
    appear alongside the readable Word.pronunciation, not replace it."""
    from types import SimpleNamespace

    from utils.word_display import format_pronunciation

    both = SimpleNamespace(pronunciation="goh", phonetic="/ɡoʊ/")
    assert format_pronunciation(both) == "goh [/ɡoʊ/]"

    readable_only = SimpleNamespace(pronunciation="goh", phonetic=None)
    assert format_pronunciation(readable_only) == "goh"

    ipa_only = SimpleNamespace(pronunciation=None, phonetic="/ɡoʊ/")
    assert format_pronunciation(ipa_only) == "/ɡoʊ/"

    neither = SimpleNamespace(pronunciation=None, phonetic=None)
    assert format_pronunciation(neither) is None


def test_card_shows_combined_pronunciation_and_ipa_when_both_set():
    text = render_word_card_text(_card(pronunciation="uh-POYNT-ment", phonetic="/əˈpɔɪntmənt/"))
    assert "uh-POYNT-ment [/əˈpɔɪntmənt/]" in text


def test_render_conjugation_messages_fits_in_one_message_when_short():
    from utils.word_display import render_conjugation_messages

    word = SimpleNamespace(language_code="en", word="go")
    conjugation = {
        "present": ["I go", "You go", "He/She/It goes", "We go", "You go", "They go"],
        "past": ["I went", "You went", "He/She/It went", "We went", "You went", "They went"],
    }
    messages = render_conjugation_messages(word, conjugation)
    assert len(messages) == 1
    assert "🇬🇧 go" in messages[0]
    assert "Present:" in messages[0]
    assert "Past:" in messages[0]
    assert "I go" in messages[0]
    assert "They went" in messages[0]


def test_render_conjugation_messages_never_forces_english_tense_names():
    from utils.word_display import render_conjugation_messages

    word = SimpleNamespace(language_code="de", word="gehen")
    conjugation = {"Präsens": ["ich gehe"], "Präteritum": ["ich ging"]}
    text = render_conjugation_messages(word, conjugation)[0]
    assert "Präsens:" in text
    assert "Präteritum:" in text


def test_render_conjugation_messages_splits_long_tables_without_cutting_a_block():
    from utils.word_display import render_conjugation_messages

    word = SimpleNamespace(language_code="en", word="go")
    # Ten tenses, each padded well past the per-message safety margin -
    # this must produce more than one message, and every tense name must
    # appear in exactly one of them, never split mid-block.
    conjugation = {f"tense{i}": [f"form {i} number {n}" * 20 for n in range(6)] for i in range(10)}
    messages = render_conjugation_messages(word, conjugation)
    assert len(messages) > 1
    for i in range(10):
        occurrences = sum(1 for m in messages if f"Tense{i}:" in m)
        assert occurrences == 1


def test_card_headers_follow_interface_language():
    from utils.i18n import set_current_language

    set_current_language("en")
    text = render_word_card_text(_card(pronunciation="/əˈpɔɪntmənt/"))
    assert "🔊 Pronunciation:" in text
    assert "/əˈpɔɪntmənt/" in text
    set_current_language("ru")
