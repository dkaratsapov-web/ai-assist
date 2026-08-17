"""Кросс-минусовка: чтобы фразы не отбирали показы друг у друга.

Задача, из-за которой сливается бюджет тише всего остального.

Пусть в кампании есть «пластиковые окна» и «пластиковые окна с установкой».
Человек вводит второй запрос — а Директ показывает объявление первой группы,
потому что она тоже подходит. В итоге по дорогому уточнённому запросу
показывается общее объявление с общим текстом, конверсия хуже, а специалист
видит только «что-то не работает»: в отчёте обе фразы получают показы, и по
цифрам всё выглядит нормально.

Лечится добавлением к общей фразе минус-слов из уточнённой. Тогда общая фраза
перестаёт ловить чужие запросы, и каждый запрос уходит туда, куда задумано.

Делается это руками в Коммандере или Key Collector и занимает время, а
пропускается регулярно — потому что на маленьких ядрах эффект незаметен, а на
больших пересечения не удержать в голове.

Основы, а не слова: «окна» и «окон» — одно и то же, и сравнение по буквам
пропустило бы половину пересечений.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from .morphology import stem, tokenize
from .semantics import STOP_WORDS

#: Предел на разбор. Пересечения ищутся по обращённому указателю, а не перебором
#: пар, поэтому предел высокий — он защищает не от сложности, а от случайности:
#: вставленный целиком файл на миллион строк обработается, но результат будет
#: бесполезен, а ждать придётся долго.
MAX_PHRASES = 20_000


@dataclass(frozen=True, slots=True)
class CrossMinus:
    """Что добавить к фразе, чтобы она не перехватывала чужие запросы."""

    phrase: str
    #: Слова, которые нужно отминусовать у этой фразы.
    minus_words: tuple[str, ...]
    #: Чьи запросы она иначе перехватывала бы. Без этого списка совет
    #: невозможно проверить: человек видит «минусуйте установку» и не понимает,
    #: откуда это взялось и что сломается, если послушаться.
    shadows: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Duplicate:
    """Фразы, неразличимые для площадки.

    «Купить пластиковые окна» и «пластиковые окна купить» — это одна и та же
    фраза: Директ не различает порядок слов. Держать обе значит соревноваться с
    самим собой на аукционе и делить статистику надвое.
    """

    phrases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CrossMinusResult:
    items: tuple[CrossMinus, ...]
    duplicates: tuple[Duplicate, ...]
    #: Сколько фраз разобрано. Меньше присланного, если сработал предел.
    analyzed: int


def _key(phrase: str) -> frozenset[str]:
    """Смысловой отпечаток фразы: основы значимых слов.

    Служебные слова выбрасываются: для Директа «окна в дом» и «окна для дома»
    неразличимы, и считать их разными фразами значит выдумывать пересечения
    там, где их нет.
    """
    return frozenset(
        stem(word) for word in tokenize(phrase) if word not in STOP_WORDS and len(word) > 1
    )


def _extra_words(longer: str, base: frozenset[str]) -> list[str]:
    """Слова уточнённой фразы, которых нет в общей.

    Возвращаются исходные слова, а не основы: минус-слово пишется в кампанию
    как есть, и «установк» вместо «установка» Директ не примет.
    """
    seen: dict[str, None] = {}
    for word in tokenize(longer):
        if word in STOP_WORDS or len(word) <= 1:
            continue
        if stem(word) not in base:
            seen.setdefault(word, None)
    return list(seen)


def cross_minus(phrases: Sequence[str]) -> CrossMinusResult:
    """Считает кросс-минусовку для списка фраз.

    Ищет пары, в которых одна фраза целиком содержится в другой по смыслу:
    тогда общая фраза перехватывает запросы уточнённой.

    Перебора всех пар нет — при тысяче фраз это полмиллиона сравнений, а при
    десяти тысячах пятьдесят миллионов. Вместо него обращённый указатель:
    кандидаты на «поглощение» ищутся среди фраз, содержащих самую редкую основу
    исходной. Редкую — потому что она отсекает больше всего лишнего.
    """
    unique: dict[str, None] = {}
    for phrase in phrases:
        cleaned = phrase.strip()
        if cleaned:
            unique.setdefault(cleaned, None)

    ordered = list(unique)[:MAX_PHRASES]

    keys: dict[str, frozenset[str]] = {}
    for phrase in ordered:
        key = _key(phrase)
        if key:
            keys[phrase] = key

    # Фразы с одинаковым отпечатком — дубликаты друг друга, а не пересечение.
    by_key: dict[frozenset[str], list[str]] = defaultdict(list)
    for phrase, key in keys.items():
        by_key[key].append(phrase)

    duplicates = tuple(
        Duplicate(phrases=tuple(group)) for group in by_key.values() if len(group) > 1
    )

    # Обращённый указатель: основа → фразы, в которых она встречается.
    index: dict[str, set[str]] = defaultdict(set)
    for phrase, key in keys.items():
        for part in key:
            index[part].add(phrase)

    items: list[CrossMinus] = []

    for phrase, key in keys.items():
        # Самая редкая основа фразы: кандидатов, содержащих её, меньше всего.
        rarest = min(key, key=lambda part: len(index[part]))

        minus: dict[str, None] = {}
        shadowed: list[str] = []

        for candidate in index[rarest]:
            other = keys[candidate]
            # Строгое вложение: одинаковые отпечатки уже учтены как дубликаты,
            # а фраза не поглощает сама себя.
            if len(other) <= len(key) or not key < other:
                continue

            shadowed.append(candidate)
            for word in _extra_words(candidate, key):
                minus.setdefault(word, None)

        if minus:
            items.append(
                CrossMinus(
                    phrase=phrase,
                    minus_words=tuple(sorted(minus)),
                    # Сортировка нужна для повторяемости: без неё порядок
                    # зависит от обхода множества и меняется между запусками,
                    # а значит и выгрузка каждый раз выглядит другой.
                    shadows=tuple(sorted(shadowed)),
                )
            )

    items.sort(key=lambda item: (-len(item.shadows), item.phrase))

    return CrossMinusResult(
        items=tuple(items),
        duplicates=tuple(sorted(duplicates, key=lambda d: d.phrases[0])),
        analyzed=len(ordered),
    )
