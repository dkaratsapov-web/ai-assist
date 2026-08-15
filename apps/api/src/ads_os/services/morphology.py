"""Приведение русских слов к основе.

Нужно для семантики: «ремонт айфона», «ремонта айфон» и «ремонту айфонов» — это
одна и та же фраза с точки зрения группировки. Без приведения к основе они
попали бы в три разные группы, и кластеризация потеряла бы смысл.

Реализован алгоритм Портера для русского языка (Snowball). Выбор в пользу него,
а не библиотеки морфологии, сделан осознанно:

* полноценный морфологический разбор тянет за собой словарь на десятки мегабайт
  и заметное время старта — в воркере, который обрабатывает список фраз, это
  цена без отдачи;
* стеммер детерминирован и не зависит от версии словаря: одна и та же фраза
  через год даст ту же основу, и сохранённые кластеры не «поедут»;
* для группировки нужна не грамматическая правильность, а устойчивость. Основа
  «ремонт» от слова «ремонта» здесь равноценна лемме.

Стеммер ошибается на редких словах и на омонимии — это известное свойство
алгоритма, а не дефект реализации. Для кластеризации рекламных фраз, где
преобладают простые существительные и прилагательные, точности достаточно.
"""

from __future__ import annotations

import re

VOWELS = "аеиоуыэюя"

#: Совершенные деепричастия, требующие предшествующей «а» или «я».
_PERFECTIVE_GERUND_1 = ("вшись", "вши", "в")
_PERFECTIVE_GERUND_2 = ("ывшись", "ившись", "ывши", "ивши", "ыв", "ив")

_ADJECTIVE = (
    "ими", "ыми", "его", "ого", "ему", "ому", "ее", "ие", "ые", "ое", "ей",
    "ий", "ый", "ой", "ем", "им", "ым", "ом", "их", "ых", "ую", "юю", "ая",
    "яя", "ою", "ею",
)

_PARTICIPLE_1 = ("ющ", "нн", "вш", "ем", "щ")
_PARTICIPLE_2 = ("ующ", "ивш", "ывш")

_REFLEXIVE = ("ся", "сь")

_VERB_1 = (
    "ешь", "нно", "ете", "йте", "ла", "на", "ли", "ем", "ло", "но", "ет",
    "ют", "ны", "ть", "й", "л", "н",
)
_VERB_2 = (
    "ейте", "уйте", "ила", "ыла", "ена", "ите", "или", "ыли", "ило", "ыло",
    "ено", "ует", "уют", "ены", "ить", "ыть", "ишь", "ей", "уй", "ил", "ыл",
    "им", "ым", "ен", "ят", "ит", "ыт", "ую", "ю",
)

_NOUN = (
    "иями", "ями", "ами", "иях", "ией", "иям", "ием", "ях", "ах", "ов",
    "ев", "ие", "ье", "еи", "ии", "ей", "ой", "ий", "ям", "ем", "ам", "ом",
    "ию", "ью", "ия", "ья", "а", "е", "и", "й", "о", "у", "ы", "ь", "ю", "я",
)

_SUPERLATIVE = ("ейше", "ейш")
_DERIVATIONAL = ("ость", "ост")


def stem(word: str) -> str:
    """Возвращает основу слова.

    Слова короче четырёх букв не обрабатываются: у них нечего отсекать, а
    попытка отсечения превращает «дом» в «д» и склеивает несвязанные фразы.
    """
    word = word.lower().replace("ё", "е")

    if len(word) < 4 or not any(ch in VOWELS for ch in word):
        return word

    rv_start = _rv_start(word)
    r2_start = _r2_start(word)

    stem_word = word

    # ── Шаг 1 ──────────────────────────────────────────────────────────────
    removed = _remove_gerund(stem_word, rv_start)
    if removed is not None:
        stem_word = removed
    else:
        stem_word = _remove_first(stem_word, rv_start, _REFLEXIVE) or stem_word

        for remover in (_remove_adjectival, _remove_verb, _remove_noun):
            removed = remover(stem_word, rv_start)
            if removed is not None:
                stem_word = removed
                break

    # ── Шаг 2: отсечение «и» ───────────────────────────────────────────────
    stem_word = _remove_first(stem_word, rv_start, ("и",)) or stem_word

    # ── Шаг 3: словообразовательный суффикс в R2 ───────────────────────────
    stem_word = _remove_first(stem_word, r2_start, _DERIVATIONAL) or stem_word

    # ── Шаг 4 ──────────────────────────────────────────────────────────────
    if stem_word.endswith("нн"):
        stem_word = stem_word[:-1]
    else:
        shortened = _remove_first(stem_word, rv_start, _SUPERLATIVE)
        if shortened is not None:
            stem_word = shortened[:-1] if shortened.endswith("нн") else shortened
        elif stem_word.endswith("ь"):
            stem_word = stem_word[:-1]

    return stem_word


_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """Разбивает текст на слова.

    Латиница и цифры сохраняются как есть: «iphone 14» и «ssd 512» — обычные
    части рекламных фраз, и приводить их к русской основе нечего.
    """
    return [token.lower().replace("ё", "е") for token in _WORD_RE.findall(text)]


def stems(text: str) -> list[str]:
    """Основы всех слов текста, в порядке появления."""
    return [stem(token) for token in tokenize(text)]


def _rv_start(word: str) -> int:
    """Начало области RV — позиция сразу после первой гласной."""
    for index, char in enumerate(word):
        if char in VOWELS:
            return index + 1
    return len(word)


def _r2_start(word: str) -> int:
    """Начало области R2 по определению Snowball."""
    r1 = _region_after(word, 0)
    return _region_after(word, r1)


def _region_after(word: str, start: int) -> int:
    """Позиция после первой пары «гласная + согласная», начиная со start."""
    index = start
    while index < len(word) and word[index] not in VOWELS:
        index += 1
    while index < len(word) and word[index] in VOWELS:
        index += 1
    return index + 1 if index < len(word) else len(word)


def _remove_first(word: str, region: int, endings: tuple[str, ...]) -> str | None:
    """Отсекает первое подошедшее окончание, если оно целиком лежит в области.

    Окончания перебираются от длинных к коротким: иначе «ившись» потеряло бы
    только «сь», и следующий шаг работал бы с обломком.
    """
    for ending in sorted(endings, key=len, reverse=True):
        if word.endswith(ending) and len(word) - len(ending) >= region:
            return word[: -len(ending)]
    return None


def _remove_gerund(word: str, rv: int) -> str | None:
    """Совершенное деепричастие.

    Первая группа окончаний отсекается только после «а» или «я» — это часть
    алгоритма, а не оптимизация: без проверки «выв» в слове «вывод» приняли бы
    за деепричастие.
    """
    for ending in sorted(_PERFECTIVE_GERUND_1, key=len, reverse=True):
        if word.endswith(ending):
            base = word[: -len(ending)]
            if len(base) >= rv and base and base[-1] in "ая":
                return base

    return _remove_first(word, rv, _PERFECTIVE_GERUND_2)


def _remove_adjectival(word: str, rv: int) -> str | None:
    """Прилагательное, возможно с причастным суффиксом перед ним."""
    without_adjective = _remove_first(word, rv, _ADJECTIVE)
    if without_adjective is None:
        return None

    for ending in sorted(_PARTICIPLE_2, key=len, reverse=True):
        if without_adjective.endswith(ending) and len(without_adjective) - len(ending) >= rv:
            return without_adjective[: -len(ending)]

    for ending in sorted(_PARTICIPLE_1, key=len, reverse=True):
        if without_adjective.endswith(ending):
            base = without_adjective[: -len(ending)]
            if len(base) >= rv and base and base[-1] in "ая":
                return base

    return without_adjective


def _remove_verb(word: str, rv: int) -> str | None:
    for ending in sorted(_VERB_1, key=len, reverse=True):
        if word.endswith(ending):
            base = word[: -len(ending)]
            if len(base) >= rv and base and base[-1] in "ая":
                return base

    return _remove_first(word, rv, _VERB_2)


def _remove_noun(word: str, rv: int) -> str | None:
    return _remove_first(word, rv, _NOUN)


def _devoweled(word: str) -> str:
    """Ключ слова без беглой гласной в предпоследней позиции.

    «окон» → «окн», «потолок» → «потолк». Правило намеренно узкое: гласная
    убирается только между двумя согласными в самом конце основы. Более широкое
    правило превращало бы «ремонт» в «ремнт» и склеивало бы несвязанные слова.
    """
    if len(word) < 3:
        return word

    vowel, before, after = word[-2], word[-3], word[-1]
    if vowel in "ое" and before not in VOWELS and after not in VOWELS:
        return word[:-2] + after

    return word


def fold_beglye(all_stems: list[str]) -> dict[str, str]:
    """Сводит основы, различающиеся только беглой гласной.

    Алгоритм Портера беглую гласную не обрабатывает: «окно» даёт основу «окн»,
    а «окон» — «окон», и фразы «ремонт окон» и «ремонта окна» расходятся по
    разным группам. Для рекламы это не мелочь: «окно», «потолок», «замок» —
    ровно те слова, вокруг которых собираются кампании.

    Словарь исключений здесь не нужен и был бы хуже: он покрывал бы только те
    слова, которые кто-то вспомнил. Вместо этого основы сводятся только при
    наличии свидетельства в самом списке — если в нём встретились обе формы.
    Одинокая основа не трогается, сколько бы гласных в ней ни было.
    """
    by_key: dict[str, set[str]] = {}
    for value in all_stems:
        by_key.setdefault(_devoweled(value), set()).add(value)

    folded: dict[str, str] = {}
    for key, variants in by_key.items():
        if len(variants) < 2:
            continue
        # Каноническая форма — короткая: именно её даёт основной падеж
        # («окн» от «окна»), и именно она чаще встречается в списке.
        canonical = min(variants, key=lambda v: (len(v), v))
        for variant in variants:
            folded[variant] = canonical
        del key

    return folded
