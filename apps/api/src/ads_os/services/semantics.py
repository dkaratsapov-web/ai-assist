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
from functools import lru_cache

from .cleanup import MARKERS, PHRASES, Reason, foreign_city, reason_for
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

#: Обороты, которые сильнее коммерческих признаков.
#:
#: Обычные информационные слова слабее «купить», и это верно: «какая цена» —
#: всё-таки покупка. Но «какой айфон лучше купить» — не покупка, а выбор: до
#: заявки здесь ещё несколько дней и десяток сравнений. Такая фраза попадала в
#: целевые из-за одного слова «купить», уезжала в группу, и по ней собиралось
#: объявление «Какой айфон лучше купить в — Акции».
#:
#: Здесь перечислены обороты, при которых человек заведомо изучает вопрос, чем
#: бы он ни заканчивался. Совпадение проверяется по вхождению: разбирать падежи
#: в устойчивом обороте незачем.
RESEARCH_PHRASES: tuple[str, ...] = (
    "как выбрать", "какой выбрать", "какая лучше", "какие лучше", "какой лучше",
    "какое лучше", "что лучше", "что выбрать", "чем отличается", "чем отличаются",
    "в чем разница", "в чём разница", "стоит ли", "нужно ли", "можно ли", "правда ли",
    "рейтинг", "топ 10", "топ-10", "обзор", "сравнение", "отзывы",
)

#: «Какой айфон лучше», «какая машинка надёжнее» — вопрос о выборе, в котором
#: между вопросительным словом и признаком сравнения стоит сам товар.
_RESEARCH_RE = re.compile(
    r"\b(?:какой|какая|какое|какие|что|чем)\b.*"
    r"\b(?:лучше|лучший|надежнее|надёжнее|выбрать|отличается|разница)\b"
)

#: Признаки того, что человек ищет не наш товар. Список живёт в `cleanup`: там
#: он разложен по причинам, и каждая находка может объяснить себя. Здесь он
#: остаётся под прежними именами — по ним обращается остальной код.
IRRELEVANT_MARKERS = MARKERS

#: Многословные признаки: по одному слову их не поймать. «Своими руками» —
#: самый частый из них, и он однозначно нецелевой для услуги.
IRRELEVANT_PHRASES = PHRASES


@dataclass(frozen=True, slots=True)
class ParsedKeyword:
    """Одна разобранная строка списка."""

    phrase: str
    #: Частотность из выгрузки, если она была в строке.
    frequency: int | None = None


#: Частотность в выгрузках идёт последним числом строки, отделённым от фразы
#: разделителем колонок.
#:
#: Разделитель обязателен, и это исправление прямой поломки. Раньше годился и
#: один пробел — а значит, любое число на конце фразы считалось частотностью.
#: «какой айфон лучше купить в 2026» превращалось в «какой айфон лучше купить
#: в»: год уезжал в столбец частотности, фраза оставалась с висящим предлогом,
#: из неё получалась группа, а из группы — объявление «Какой айфон лучше
#: купить в — Акции». Так же терялись «айфон 15», «окна 60х80», «масло 5w30».
#:
#: Табуляция, точка с запятой, запятая или два пробела подряд — это колонка
#: наверняка. Один пробел разбирается отдельно, по всему списку сразу.
_TAIL_NUMBER_RE = re.compile(r"(?:[\t;,]\s*|\s{2,})(\d[\d\s ]*)$")


#: Число на конце строки после одного пробела. Само по себе не значит ничего:
#: это и «окна пвх 900», и «купить айфон 15».
_SPACE_TAIL_RE = re.compile(r"(?<=\S)\s(\d[\d\s\u00a0\u202f]*)$")

#: Со скольких строк список считается списком, а не набором фраз.
_MIN_LINES_FOR_COLUMN = 3

#: Какая доля строк должна оканчиваться числом, чтобы признать в нём колонку.
_COLUMN_SHARE = 0.8


def _space_is_column(lines: list[str]) -> bool:
    """Отделён ли столбец частотности одним пробелом.

    Решение принимается по всему списку, а не по строке, и в этом весь смысл.
    По отдельной строке «купить айфон 15» и «окна пвх 900» неразличимы: в обеих
    число стоит на конце после пробела. По списку различимы сразу — в выгрузке
    число есть у каждой строки, в наборе фраз у одной-двух.

    Раньше решение принималось построчно, и система отбирала у фраз их
    собственные числа: модели, размеры, годы.
    """
    rows = [line for line in lines if line.strip()]
    if len(rows) < _MIN_LINES_FOR_COLUMN:
        return False

    with_number = sum(1 for line in rows if _SPACE_TAIL_RE.search(line.strip()))
    return with_number >= len(rows) * _COLUMN_SHARE


#: Слова, на которые фраза заканчиваться не может. Висящий предлог означает,
#: что строку обрезали: живой человек «купить в» не искал.
_DANGLING = frozenset(
    [
        "в", "на", "с", "со", "по", "для", "и", "или", "от", "до", "из", "у", "к", "о", "об",
        "а", "но", "же", "ли", "бы", "не", "при", "под", "над", "за", "без", "про", "как",
        "что", "чем", "это",
    ]
)


def trim_dangling(phrase: str) -> str:
    """Убирает висящие служебные слова с конца фразы.

    Вторая линия обороны. Обрезанные строки приходят не только из разбора
    выгрузки: их приносят чужие файлы и вставка руками. А фраза с предлогом на
    конце портит всё, что стоит дальше по цепочке, — название группы, заголовок
    объявления, отображаемую ссылку.
    """
    words = phrase.split()
    while words and words[-1] in _DANGLING:
        words.pop()
    return " ".join(words)


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
    lines = raw.splitlines()
    space_column = _space_is_column(lines)

    for line in lines:
        line = line.strip()
        if not line:
            continue

        frequency: int | None = None
        match = _TAIL_NUMBER_RE.search(line) or (
            _SPACE_TAIL_RE.search(line) if space_column else None
        )
        if match:
            digits = re.sub(r"\D", "", match.group(1))
            phrase = line[: match.start()].strip(" \t;,")
            # Строка из одних цифр — это частотность без фразы, а не фраза.
            if phrase and digits:
                frequency = int(digits)
                line = phrase

        phrase = trim_dangling(" ".join(line.split()).strip(' "«»').lower())
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
    #: К какому виду мусора отнесена фраза. Одного слова мало: «москва» само по
    #: себе ничего не объясняет, а «другой город» объясняет сразу.
    reason: Reason | None = None


def classify(
    phrase: str,
    *,
    extra_irrelevant: frozenset[str] = frozenset(),
    region: str | None = None,
) -> Classification:
    """Определяет тип запроса.

    Порядок проверок важен. Нецелевые слова сильнее коммерческих: «купить
    диплом» — это не заявка, сколько бы в ней ни было признаков покупки.
    Информационные слабее коммерческих: «какая цена» — это всё-таки покупка.

    Чужой город проверяется первым. Причина в том, что такая фраза чаще всего
    выглядит образцово коммерческой — «купить пластиковые окна в москве», — и
    любая другая проверка признает её целевой раньше, чем дело дойдёт до
    географии. Именно поэтому чужой регион и остаётся в кампаниях дольше всего
    прочего мусора.
    """
    lowered = phrase.lower()

    city = foreign_city(phrase, region)
    if city is not None:
        return Classification(Intent.IRRELEVANT, city, Reason.GEO)

    # Минус-слово из двух слов — обычное дело: «ремонт окон» в проекте про
    # остекление отсекается только целиком. По отдельности «ремонт» и «окон»
    # вырезали бы половину ядра.
    for marker in IRRELEVANT_PHRASES + _multiword(extra_irrelevant):
        if marker in lowered:
            return Classification(
                Intent.IRRELEVANT, marker, reason_for(marker, minus_words=extra_irrelevant)
            )

    words = tokenize(phrase)
    by_stem = _stems(IRRELEVANT_MARKERS | extra_irrelevant)

    for word in words:
        hit = by_stem.get(word) or by_stem.get(stem(word))
        if hit is not None:
            # Показывается слово из фразы, а не из словаря: человек ищет
            # глазами то, что видит перед собой, а не основу «работ».
            return Classification(
                Intent.IRRELEVANT, word, reason_for(hit, minus_words=extra_irrelevant)
            )

    # Изучение вопроса сильнее покупки, но только на устойчивых оборотах.
    # Одиночное слово так проверять нельзя: «какая цена» и «сколько стоит» —
    # это покупка, сколько бы вопросительных слов рядом ни стояло.
    for marker in RESEARCH_PHRASES:
        if marker in lowered:
            return Classification(Intent.INFORMATIONAL, marker)

    if _RESEARCH_RE.search(lowered):
        return Classification(Intent.INFORMATIONAL, "выбор, а не покупка")

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


@lru_cache(maxsize=64)
def _stems(markers: frozenset[str]) -> dict[str, str]:
    """Основа → слово словаря. Считается один раз на набор, а не на фразу.

    Разница не косметическая: при двадцати тысячах фраз пересчёт основ словаря
    на каждое слово каждой фразы — это десятки миллионов лишних вызовов, и
    импорт из секунды превращается в минуту.
    """
    index: dict[str, str] = {}
    for marker in markers:
        if " " in marker:
            continue
        index.setdefault(stem(marker), marker)
        index[marker] = marker
    return index


@lru_cache(maxsize=64)
def _multiword(markers: frozenset[str]) -> tuple[str, ...]:
    """Минус-слова из нескольких слов — их ищут по строке целиком."""
    return tuple(sorted((m for m in markers if " " in m), key=lambda item: -len(item)))


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
    """Группирует фразы вокруг общего смыслового ядра.

    Ядро — набор основ без служебных и коммерческих слов. «Купить пластиковые
    окна» и «пластиковые окна цена» имеют одно ядро {пластиков, окн}, и это
    правильно: обе фразы ведут на одну страницу и требуют одного объявления.
    Различие между ними — в тексте объявления, а не в структуре кампании.

    Группы собираются жадно, от самого частого сочетания основ к редким. Такой
    порядок даёт то, что нужно от структуры кампании: крупные группы с общей
    сутью, а не россыпь из одной фразы. Директу для обучения нужен объём, и
    группа из одного ключа его не даёт.

    Сочетание из двух основ предпочитается одиночной: «ремонт окон» — это
    группа, а просто «окн» объединило бы ремонт с остеклением и продажей.
    """
    if not keywords:
        return []

    # Свод беглых гласных считается по всему списку сразу: «окн» и «окон»
    # сводятся только потому, что в этом списке встретились обе формы.
    folding = fold_beglye([s for keyword in keywords for s in _core_stems(keyword.phrase)])

    cores: dict[str, frozenset[str]] = {}
    for keyword in keywords:
        core = frozenset(folding.get(s, s) for s in _core_stems(keyword.phrase))
        if not core:
            # Фраза целиком из служебных и коммерческих слов — «купить
            # недорого». Своего смысла у неё нет, ядром она быть не может.
            core = frozenset(folding.get(stem(w), stem(w)) for w in tokenize(keyword.phrase))
        cores[keyword.phrase] = core

    unassigned = {keyword.phrase: keyword for keyword in keywords}
    clusters: list[Cluster] = []

    while unassigned:
        anchor = _best_anchor(unassigned, cores)
        if anchor is None:
            break

        members = [
            keyword for phrase, keyword in unassigned.items() if anchor <= cores[phrase]
        ]
        for keyword in members:
            del unassigned[keyword.phrase]

        clusters.append(_build(anchor, members))

    if unassigned:
        leftovers = list(unassigned.values())
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


def _best_anchor(
    unassigned: dict[str, ParsedKeyword], cores: dict[str, frozenset[str]]
) -> frozenset[str] | None:
    """Самое весомое сочетание основ среди нераспределённых фраз.

    Перебираются пары основ и одиночные основы. Тройки и длиннее не нужны: они
    описывают всё более узкую группу, а задача обратная — собрать объём.
    """
    weights: dict[frozenset[str], int] = defaultdict(int)
    sizes: dict[frozenset[str], int] = defaultdict(int)

    for phrase, keyword in unassigned.items():
        core = sorted(cores[phrase])
        candidates = [frozenset({s}) for s in core]
        candidates += [
            frozenset({first, second})
            for index, first in enumerate(core)
            for second in core[index + 1 :]
        ]
        for candidate in candidates:
            weights[candidate] += keyword.frequency or 1
            sizes[candidate] += 1

    usable = {
        candidate: weight
        for candidate, weight in weights.items()
        if sizes[candidate] >= MIN_CLUSTER_SIZE
    }
    if not usable:
        return None

    # Пара выигрывает у одиночной основы при прочих равных: «ремонт окон» —
    # это группа, а «окн» смешало бы ремонт, остекление и продажу.
    return max(usable, key=lambda c: (len(c), usable[c], sizes[c]))


@dataclass(frozen=True, slots=True)
class MinusWordSuggestion:
    """Предложение добавить слово в минус-список."""

    word: str
    #: Сколько фраз оно уводит в нецелевые. Без числа непонятно, стоит ли
    #: решение внимания: слово из одной фразы и слово из двухсот — разные вещи.
    phrases: int
    examples: tuple[str, ...] = field(default_factory=tuple)
    reason: Reason | None = None


def suggest_minus_words(
    keywords: list[ParsedKeyword],
    *,
    extra_irrelevant: frozenset[str] = frozenset(),
    region: str | None = None,
) -> list[MinusWordSuggestion]:
    """Собирает слова, из-за которых фразы признаны нецелевыми.

    Это готовый минус-список: его остаётся проверить и перенести в кампанию.
    Собирать его вручную по тысяче фраз — самая механическая часть работы
    специалиста, и именно её имеет смысл снимать.

    Города сюда не попадают. Минусовать их по одному бессмысленно: городов в
    выгрузке десятки, и правильное решение — не минус-слово, а регион показа.
    """
    counts: dict[str, list[str]] = defaultdict(list)
    reasons: dict[str, Reason | None] = {}

    for keyword in keywords:
        result = classify(keyword.phrase, extra_irrelevant=extra_irrelevant, region=region)
        if result.intent is not Intent.IRRELEVANT or not result.trigger:
            continue
        if result.reason is Reason.GEO:
            continue
        counts[result.trigger].append(keyword.phrase)
        reasons[result.trigger] = result.reason

    suggestions = [
        MinusWordSuggestion(
            word=word,
            phrases=len(phrases),
            examples=tuple(phrases[:3]),
            reason=reasons.get(word),
        )
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


@dataclass(frozen=True, slots=True)
class LandingPage:
    """Проверенная страница сайта, на которую можно вести группу фраз."""

    url: str
    #: Заголовок страницы. По нему и происходит сопоставление: адрес обычно на
    #: латинице, а фразы на русском, и сравнивать их нечем.
    title: str | None = None


def match_landing(core: tuple[str, ...], pages: list[LandingPage], *, fallback: str) -> str:
    """Подбирает посадочную под группу фраз.

    Ведёт по совпадению основ ядра группы с заголовком страницы. Реклама по
    запросу «остекление балконов», приводящая на главную, — это оплаченный клик,
    после которого человек ищет балконы сам. Мы сами называем это ошибкой в
    аудите, и делать её в собственных объявлениях тем более незачем.

    При отсутствии совпадения возвращается главная страница. Вести на случайную
    подходящую «хоть немного» хуже, чем на главную: с главной человек хотя бы
    попадает в понятное место.
    """
    if not core:
        return fallback

    # Беглая гласная сводится по ядру и заголовкам разом: «ремонт окон» в
    # заголовке даёт основу «окон», а в ядре группы стоит «окн», и без свода
    # страница «Ремонт окон» не находилась бы по группе про ремонт окон.
    everything = list(core) + [
        stem(word) for page in pages if page.title for word in tokenize(page.title)
    ]
    folding = fold_beglye(everything)
    folded_core = {folding.get(item, item) for item in core}

    best_url = fallback
    best_score = 0

    for page in pages:
        if not page.title:
            continue

        title_stems = {
            folding.get(stem(word), stem(word)) for word in tokenize(page.title)
        }
        score = len(folded_core & title_stems)

        # Строгое «больше»: при равном совпадении остаётся первая найденная, а
        # порядок страниц задан осмысленно — главная идёт первой.
        if score > best_score:
            best_score = score
            best_url = page.url

    return best_url
