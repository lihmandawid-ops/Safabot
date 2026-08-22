"""🔥 Популярные фразы (native-speaker phrasebook stage, section 17): a
modest, hand-curated starter set of common, natural everyday phrases per
supported learning language - deliberately NOT DeepSeek-generated on
every request (section 26: browsing this list must never cost an API
call), and deliberately small ("создать БАЗОВЫЙ набор", not an
exhaustive one) rather than an attempt at a large phrasebook by hand.

Only `phrase` (in the learning language) and `pronunciation` (Latin-only,
global pronunciation rule) are stored here - NOT a baked-in translation,
since a translation has to match whichever translation_language the
opening user currently has, and that can't be predicted at authoring
time. handlers/phrases.py fetches the translation (and, for consistency,
re-confirms the pronunciation) on demand via the EXISTING
AIService.analyze_text - the same one-call, whole-text translation
"📝 Разбор текста" already uses for arbitrary text - the moment a specific
popular phrase's card is actually opened, never for the list itself.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PopularPhrase:
    phrase: str
    pronunciation: str
    situation: str


POPULAR_PHRASES: dict[str, tuple[PopularPhrase, ...]] = {
    "en": (
        PopularPhrase("How are you doing?", "how ar yoo DOO-ing", "socializing"),
        PopularPhrase("Thanks a lot, I really appreciate it.", "thanks a lot, ay REE-lee uh-PREE-shee-ayt it", "socializing"),
        PopularPhrase("Could you help me with this?", "kud yoo help mee with this", "work"),
        PopularPhrase("How much does this cost?", "how much duz this kost", "shopping"),
        PopularPhrase("Nice to meet you.", "nys too meet yoo", "meeting"),
        PopularPhrase("See you later!", "see yoo LAY-ter", "socializing"),
    ),
    "ru": (
        PopularPhrase("Как дела?", "kak dee-LA", "socializing"),
        PopularPhrase("Спасибо большое, очень ценю.", "spa-SEE-ba bal-SHOye, O-chen tse-NYU", "socializing"),
        PopularPhrase("Не могли бы вы мне помочь?", "nye mag-LEE bih vih mnye pa-MOCH", "work"),
        PopularPhrase("Сколько это стоит?", "SKOL-ka EH-ta STO-it", "shopping"),
        PopularPhrase("Очень приятно познакомиться.", "O-chen pri-YAT-na paz-na-KO-mit-sya", "meeting"),
        PopularPhrase("Увидимся позже!", "u-VEE-dim-sya PO-zhe", "socializing"),
    ),
    "de": (
        PopularPhrase("Wie geht's dir?", "vee gayts deer", "socializing"),
        PopularPhrase("Vielen Dank, das weiß ich wirklich zu schätzen.", "FEE-len dank, das vys ikh VEERK-likh tsoo SHET-sen", "socializing"),
        PopularPhrase("Könntest du mir dabei helfen?", "KURN-test doo meer da-BY HEL-fen", "work"),
        PopularPhrase("Wie viel kostet das?", "vee feel KOS-tet das", "shopping"),
        PopularPhrase("Freut mich, dich kennenzulernen.", "froyt mikh dikh KEN-en-tsoo-LER-nen", "meeting"),
        PopularPhrase("Bis später!", "bis SHPAY-ter", "socializing"),
    ),
    "es": (
        PopularPhrase("¿Cómo estás?", "KO-mo es-TAS", "socializing"),
        PopularPhrase("Muchas gracias, te lo agradezco de verdad.", "MOO-chas GRA-syas, te lo a-gra-DES-ko de ver-DAD", "socializing"),
        PopularPhrase("¿Podrías ayudarme con esto?", "po-DREE-as a-yoo-DAR-me kon ES-to", "work"),
        PopularPhrase("¿Cuánto cuesta esto?", "KWAN-to KWES-ta ES-to", "shopping"),
        PopularPhrase("Mucho gusto en conocerte.", "MOO-cho GOOS-to en ko-no-SER-te", "meeting"),
        PopularPhrase("¡Nos vemos luego!", "nos VE-mos LWE-go", "socializing"),
    ),
    "fr": (
        PopularPhrase("Comment ça va ?", "ko-MAHN sa VA", "socializing"),
        PopularPhrase("Merci beaucoup, j'apprécie vraiment.", "mer-SEE bo-KOO, zha-pray-SEE vray-MAHN", "socializing"),
        PopularPhrase("Tu pourrais m'aider avec ça ?", "tu poo-REH meh-DAY a-VEK sa", "work"),
        PopularPhrase("Combien ça coûte ?", "kom-BYEN sa KOOT", "shopping"),
        PopularPhrase("Enchanté de vous rencontrer.", "ahn-shahn-TAY duh voo rahn-kon-TRAY", "meeting"),
        PopularPhrase("À plus tard !", "a plu TAR", "socializing"),
    ),
    "it": (
        PopularPhrase("Come stai?", "KO-me STAI", "socializing"),
        PopularPhrase("Grazie mille, lo apprezzo davvero.", "GRA-tsye MEEL-le, lo a-PRET-tso da-VE-ro", "socializing"),
        PopularPhrase("Potresti aiutarmi con questo?", "po-TRES-ti a-yoo-TAR-mi kon KWES-to", "work"),
        PopularPhrase("Quanto costa questo?", "KWAN-to KOS-ta KWES-to", "shopping"),
        PopularPhrase("Piacere di conoscerti.", "pya-CHE-re di ko-NO-sher-ti", "meeting"),
        PopularPhrase("Ci vediamo dopo!", "chi ve-DYA-mo DO-po", "socializing"),
    ),
    "uk": (
        PopularPhrase("Як справи?", "yak SPRA-vy", "socializing"),
        PopularPhrase("Дуже дякую, я справді це ціную.", "DOO-zhe DYA-koo-yu, ya SPRAV-di tse tsi-NOO-yu", "socializing"),
        PopularPhrase("Могли б ви мені допомогти?", "moh-LY b vy me-NI do-po-moh-TY", "work"),
        PopularPhrase("Скільки це коштує?", "SKIL-ky tse KOSH-too-ye", "shopping"),
        PopularPhrase("Приємно познайомитися.", "pry-YEM-no poz-na-YO-my-ty-sya", "meeting"),
        PopularPhrase("Побачимось пізніше!", "po-BA-chy-mos piz-NI-she", "socializing"),
    ),
    "he": (
        PopularPhrase("מה נשמע?", "ma nish-MA", "socializing"),
        PopularPhrase("תודה רבה, אני ממש מעריך את זה.", "to-DA ra-BA, a-NI ma-MASH ma-a-REEKH et ZE", "socializing"),
        PopularPhrase("תוכל לעזור לי עם זה?", "too-CHAL la-a-ZOR li im ZE", "work"),
        PopularPhrase("כמה זה עולה?", "KA-ma ze o-LE", "shopping"),
        PopularPhrase("נעים מאוד להכיר אותך.", "na-EEM me-OD le-ha-KEER ot-KHA", "meeting"),
        PopularPhrase("נתראה אחר כך!", "nit-ra-E a-KHAR kakh", "socializing"),
    ),
}


def get_popular_phrases(language_code: str) -> tuple[PopularPhrase, ...]:
    return POPULAR_PHRASES.get(language_code, ())
