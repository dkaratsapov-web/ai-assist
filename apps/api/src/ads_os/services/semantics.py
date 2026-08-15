"""Семантика: разбор списка фраз, отсев нецелевых, группировка.

Модуль намеренно не ходит в Wordstat. Источник фраз — вставленный список: так
он работает и сегодня, без доступа к API Директа, и не изменится, когда доступ
появится. Автоматический сбор станет ещё одним источником для того же разбора,
а не заменой ему.

Все решения здесь — предложения, а не приговоры. Отнесение фразы к нецелевым
специалист меняет одним нажатием: словарь не знает ни ниши, ни клиента, и
ошибётся в обе стороны. Ценность не в том, что система решает за человека, а в
том, что она разбирает тысячу фраз за секунду и оставляет на проверку десятки.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum

from .morphology import fold_beglye, stem, tokenize


class Intent(StrEnum):
    """К чему относится запрос."""

    #: Человек хочет купить. Основа кампании.
    COMMERCIAL = "commercial"
    #: Человек изучает вопрос. Иногда полезен, но конверсия ниже, и в одну
    #: кампанию с коммерческими такие фразы не ставят.
    INFORMATIONAL = "informational"
    #: Человек ищет не то, что мы продаём. Деньги на него тратить нельзя.
    IRRELEVANT = "irrelevant"


INTENT_LABELS: dict[Intent, str] = {
    Intent.COMMERCIAL: "целевой",
    Intent.INFORMATIONAL: "информационный",
    Intent.IRRELEVANT: "нецелевой",
}

#: Служебные слова. В группировке не участвуют: по предлогу «для» объединяются
#: фразы, не имеющие между собой ничего общего.
STOP_WORDS = frozenset(
    [
        "в", "на", "с", "со", "по", "для", "и", "или", "от", "до", "из", "у", "к", "о", "об",
        "а", "но", "же", "ли", "бы", "не", "при", "под", "над", "за", "без", "про", "это",
        "как", "где", "когда", "что", "чем", "чего", "кто", "вы", "мы", "я", "он", "она", "они",
        "его", "её", "их", "мой", "моя", "мои", "наш", "наша", "наши",
    ]
)

#: Признаки готовности купить.
COMMERCIAL_MARKERS = frozenset(
    [
        "купить", "заказать", "заказ", "цена", "цены", "ценам", "стоимость", "стоит", "прайс",
        "сколько", "недорого", "дешево", "дешевый", "дешёвый", "услуга", "услуги", "оформить",
        "оптом", "доставка", "срочно", "круглосуточно", "рядом", "ближайший",
    ]
)

#: Признаки изучения вопроса, а не покупки.
INFORMATIONAL_MARKERS = frozenset(
    [
        "как", "что", "почему", "зачем", "чем", "отличается", "отличие", "инструкция", "схема",
        "чертеж", "чертёж", "принцип", "устройство", "отзыв", "отзывы", "рейтинг", "лучший",
        "топ", "сравнение", "обзор", "обзоры", "выбрать", "какой", "значит", "такое", "виды",
        "classification",
    ]
)

#: Признаки того, что человек ищет не наш товар. Список начальный: каждая ниша
#: добавляет свои, поэтому он расширяется на уровне проекта.
IRRELEVANT_MARKERS = frozenset(
    [
        "бесплатно", "бесплатный", "даром", "скачать", "торрент", "онлайн", "смотреть",
        "вакансия", "вакансии", "работа", "резюме", "зарплата", "обучение", "курсы", "училище",
        "реферат", "курсовая", "диплом", "гост", "снип", "бу", "подержанный", "самому",
        "самостоятельно", "своими", "руками", "порно", "игра", "игры", "мем", "прикол",
    ]
)

#: Многословные признаки: по одному слову их не поймать. «Своими руками» —
#: самый частый из них, и он однозначно нецелевой для услуги.
IRRELEVANT_PHRASES = ("своими руками", "сделать самому", "своими силами")


@dataclass(frozen=True, slots=True)
class ParsedKeyword:
    """Одна разобранная строка списка."""

    phrase: str
    #: Частотность из выгрузки, если она была в строке.
    frequency: int | None = None


#: Частотность в выгрузках Вордстата и Key Collector идёт последним числом в
#: строке, отделённым табуляцией, точкой с запятой или пробелами.
_TAIL_NUMBER_RE = re.compile(r"[\t;,]?\s*(\d[\d\s ]*)$")


def parse_list(raw: str) -> list[ParsedKeyword]:
    """Разбирает вставленный список фраз.

    Понимает и «фраза<таб>1200», и «фраза;1200», и просто «фраза». Формат не
    спрашивается у пользователя: выгрузки Вордстата, Key Collector и ручной
    список отличаются разделителем, и требовать выбрать нужный — значит
    заставить человека разбираться в том, в чём разбираться не должен.

    Повторы схлопываются: у одной фразы остаётся наибольшая известная
    частотность. Ноль при этом не считается известной величиной — в выгрузках
    он чаще означает «не измеряли», чем «никто не ищет».
    """
    best: dict[str, ParsedKeyword] = {}

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        frequency: int | None = None
        match = _TAIL_NUMBER_RE.search(line)
        if match:
            digits = re.sub(r"\D", "", match.group(1))
            phrase = line[: match.start()].strip(" \t;,")
            # Строка из одних цифр — это частотность без фразы, а не фраза.
            if phrase and digits:
                frequency = int(digits)
                line = phrase

        phrase = " ".join(line.split()).strip(' "«»').lower()
        # Строка из одних цифр — это остаток выгрузки, а не запрос: искать
        # «1200» никто не будет.
        if not phrase or not tokenize(phrase) or all(ch.isdigit() for ch in phrase if ch != " "):
            continue

        existing = best.get(phrase)
        if existing is None or (frequency or 0) > (existing.frequency or 0):
            best[phrase] = ParsedKeyword(phrase=phrase, frequency=frequency or None)

    return list(best.values())


@dataclass(frozen=True, slots=True)
class Classification:
    intent: Intent
    #: Слово, из-за которого принято решение. Показывается человеку: без него
    #: непонятно, что именно нужно поправить, чтобы решение изменилось.
    trigger: str | None = None


def classify(phrase: str, *, extra_irrelevant: frozenset[str] = frozenset()) -> Classification:
    """Определяет тип запроса.

    Порядок проверок важен. Нецелевые слова сильнее коммерческих: «купить
    диплом» — это не заявка, сколько бы в ней ни было признаков покупки.
    Информационные слабее коммерческих: «какая цена» — это всё-таки покупка.
    """
    lowered = phrase.lower()

    for marker in IRRELEVANT_PHRASES:
        if marker in lowered:
            return Classification(Intent.IRRELEVANT, marker)

    words = tokenize(phrase)

    irrelevant = IRRELEVANT_MARKERS | extra_irrelevant
    for word in words:
        if word in irrelevant or stem(word) in {stem(m) for m in irrelevant}:
            return Classification(Intent.IRRELEVANT, word)

    for word in words:
        if word in COMMERCIAL_MARKERS or stem(word) in {stem(m) for m in COMMERCIAL_MARKERS}:
            return Classification(Intent.COMMERCIAL, word)

    for word in words:
        if word in INFORMATIONAL_MARKERS:
            return Classification(Intent.INFORMATIONAL, word)

    # Ни одного признака. Такие фразы — основная масса списка: «пластиковые окна
    # тверь» не содержит слова «купить», но приводит покупателей. Считать их
    # нецелевыми по умолчанию значило бы выбросить ядро семантики.
    return Classification(Intent.COMMERCIAL, None)


@dataclass(frozen=True, slots=True)
class Cluster:
    """Группа фраз, которые можно вести на одну посадочную с одним объявлением."""

    #: Самая частотная фраза группы. Служит названием: искусственно собранное
    #: имя вроде «ремонт+окн» человек не читает.
    name: str
    #: Общие основы, по которым фразы и объединились. Это и есть объяснение
    #: группировки — без него человек не может ни проверить её, ни поправить.
    core: tuple[str, ...]
    phrases: tuple[str, ...]
    total_frequency: int


#: Меньше этого числа фраз — не группа, а остаток. Такие фразы сводятся в одну
#: общую группу, чтобы не плодить кампании из одного ключа.
MIN_CLUSTER_SIZE = 2


def cluster(keywords: list[ParsedKeyword]) -> list[Cluster]:
    """Группирует фразы по совпадающему смысловому ядру.

    Ядро — набор основ без служебных и коммерческих слов. «Купить пластиковые
    окна» и «пластиковые окна цена» имеют одно ядро {пластиков, окн}, и это
    правильно: обе фразы ведут на одну страницу и требуют одного объявления.
    Различие между ними — в тексте объявления, а не в структуре кампании.

    Затем частные группы вливаются в общие: ядро {ремонт, окн, пвх} поглощается
    ядром {ремонт, окн}, если последнее крупнее. Иначе структура распадается на
    десятки групп по одной фразе, а Директу для обучения нужен объём.
    """
    # Свод беглых гласных считается по всему списку сразу: «окн» и «окон»
    # сводятся только потому, что в этом списке встретились обе формы.
    folding = fold_beglye([s for keyword in keywords for s in _core_stems(keyword.phrase)])

    by_core: dict[frozenset[str], list[ParsedKeyword]] = defaultdict(list)

    for keyword in keywords:
        core = frozenset(folding.get(s, s) for s in _core_stems(keyword.phrase))
        if not core:
            # Фраза целиком из служебных и коммерческих слов — «купить
            # недорого». Своего смысла у неё нет, ядром она быть не может.
            core = frozenset(stem(w) for w in tokenize(keyword.phrase))
        by_core[core].append(keyword)

    groups = {core: list(items) for core, items in by_core.items()}

    # От крупных к мелким: частное вливается в общее, а не наоборот.
    order = sorted(groups, key=lambda c: (-_weight(groups[c]), len(c)))

    merged: dict[frozenset[str], list[ParsedKeyword]] = {}
    for core in order:
        target = next(
            (existing for existing in merged if existing < core),
            None,
        )
        if target is not None:
            merged[target].extend(groups[core])
        else:
            merged[core] = list(groups[core])

    clusters = [
        _build(core, items) for core, items in merged.items() if len(items) >= MIN_CLUSTER_SIZE
    ]
    leftovers = [
        item
        for items in merged.values()
        if len(items) < MIN_CLUSTER_SIZE
        for item in items
    ]

    if leftovers:
        clusters.append(
            Cluster(
                name="Остальные фразы",
                core=(),
                phrases=tuple(item.phrase for item in leftovers),
                total_frequency=sum(item.frequency or 0 for item in leftovers),
            )
        )

    clusters.sort(key=lambda c: (-c.total_frequency, -len(c.phrases), c.name))
    return clusters


@dataclass(frozen=True, slots=True)
class MinusWordSuggestion:
    """Предложение добавить слово в минус-список."""

    word: str
    #: Сколько фраз оно уводит в нецелевые. Без числа непонятно, стоит ли
    #: решение внимания: слово из одной фразы и слово из двухсот — разные вещи.
    phrases: int
    examples: tuple[str, ...] = field(default_factory=tuple)


def suggest_minus_words(
    keywords: list[ParsedKeyword], *, extra_irrelevant: frozenset[str] = frozenset()
) -> list[MinusWordSuggestion]:
    """Собирает слова, из-за которых фразы признаны нецелевыми.

    Это готовый минус-список: его остаётся проверить и перенести в кампанию.
    Собирать его вручную по тысяче фраз — самая механическая часть работы
    специалиста, и именно её имеет смысл снимать.
    """
    counts: dict[str, list[str]] = defaultdict(list)

    for keyword in keywords:
        result = classify(keyword.phrase, extra_irrelevant=extra_irrelevant)
        if result.intent is Intent.IRRELEVANT and result.trigger:
            counts[result.trigger].append(keyword.phrase)

    suggestions = [
        MinusWordSuggestion(word=word, phrases=len(phrases), examples=tuple(phrases[:3]))
        for word, phrases in counts.items()
    ]
    suggestions.sort(key=lambda s: (-s.phrases, s.word))
    return suggestions


def _core_stems(phrase: str) -> frozenset[str]:
    """Смысловое ядро фразы: основы без служебных и коммерческих слов."""
    ignored = {stem(w) for w in STOP_WORDS | COMMERCIAL_MARKERS}
    return frozenset(
        stem(word)
        for word in tokenize(phrase)
        if word not in STOP_WORDS and stem(word) not in ignored and not word.isdigit()
    )


def _weight(items: list[ParsedKeyword]) -> int:
    """Вес группы: сначала суммарная частотность, при её отсутствии — размер."""
    total = sum(item.frequency or 0 for item in items)
    return total if total else len(items)


def _build(core: frozenset[str], items: list[ParsedKeyword]) -> Cluster:
    leader = max(items, key=lambda item: (item.frequency or 0, -len(item.phrase)))
    return Cluster(
        name=leader.phrase,
        core=tuple(sorted(core)),
        phrases=tuple(item.phrase for item in items),
        total_frequency=sum(item.frequency or 0 for item in items),
    )
