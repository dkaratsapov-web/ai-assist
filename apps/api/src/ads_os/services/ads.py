"""Черновики объявлений и проверка их по правилам Директа.

Система не сочиняет рекламный текст. Она делает механическую часть: подставляет
ключевую фразу в заголовок, собирает остальное из фрагментов, найденных на
странице клиента, и проверяет результат по лимитам Директа. Это ровно та
работа, которая занимает часы и не требует ни одной мысли.

Почему текст берётся со страницы, а не сочиняется. Объявление, обещающее то,
чего на сайте нет, — это отказ на модерации в лучшем случае и претензия клиента
в худшем. Взять фразу с самой посадочной страницы означает, что обещание уже
подтверждено тем, куда ведёт клик.

Результат называется черновиком и им является. Итоговый текст пишет специалист:
у него есть контекст, которого нет ни у одного набора правил.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

from .morphology import stem, tokenize

#: Лимиты текстово-графического объявления Яндекс Директа. Вынесены в константы
#: и подписаны: Директ их периодически меняет, и правка должна быть в одном
#: месте, а не в тексте условий по всему модулю.
MAX_TITLE = 56
MAX_TITLE_2 = 30
MAX_TEXT = 81
MAX_DISPLAY_PATH = 20
MAX_CALLOUT = 25

#: Лимиты быстрой ссылки. Директ принимает до четырёх на объявление.
MAX_SITELINK_TITLE = 30
MAX_SITELINKS = 4

#: Сколько уточнений имеет смысл готовить. Больше Директ примет, но в показе
#: участвуют не все, и длинный список только создаёт видимость работы.
MAX_CALLOUTS = 4


class Problem(StrEnum):
    """Что не так с черновиком."""

    TOO_LONG = "too_long"
    #: Слово капсом. Директ такие объявления отклоняет, кроме аббревиатур.
    CAPS = "caps"
    #: Превосходная степень без подтверждения — «самый», «лучший», «№1».
    #: Требует документального подтверждения, иначе отказ на модерации.
    UNPROVEN_SUPERLATIVE = "unproven_superlative"
    #: Нечем заполнить: на странице не нашлось подходящего фрагмента.
    NOTHING_TO_SAY = "nothing_to_say"


@dataclass(frozen=True, slots=True)
class Violation:
    problem: Problem
    field_name: str
    message: str


@dataclass(frozen=True, slots=True)
class Sitelink:
    """Быстрая ссылка: подпись и адрес раздела."""

    title: str
    url: str


@dataclass(frozen=True, slots=True)
class AdDraft:
    """Черновик одного объявления."""

    #: Группа, для которой собрано объявление.
    cluster: str
    title: str
    title_2: str | None
    text: str
    display_path: str | None
    callouts: tuple[str, ...] = field(default_factory=tuple)
    #: Быстрые ссылки на разделы сайта. Занимают место в выдаче и дают попасть
    #: сразу в нужный раздел, а не искать его на посадочной.
    sitelinks: tuple[Sitelink, ...] = field(default_factory=tuple)
    #: Ключевые фразы группы — они и определяют, что показывать.
    keywords: tuple[str, ...] = field(default_factory=tuple)
    violations: tuple[Violation, ...] = field(default_factory=tuple)

    @property
    def is_ready(self) -> bool:
        """Черновик без нарушений. Не «готов к запуску», а «пройдёт модерацию»."""
        return not self.violations


#: Слова, требующие документального подтверждения. Директ отклоняет объявления
#: с ними, если подтверждения нет, — а его почти никогда нет.
#:
#: Сравнение идёт по основе слова, а не по точной форме. Перечислять «самый,
#: самая, самое, самые, самому…» — это гарантированно забыть половину: первая же
#: проверка поймала «самые низкие цены», которых в списке не было.
SUPERLATIVES = ("самый", "лучший", "лидер", "единственный", "гарантированно", "непревзойдённый")

#: Обороты, у которых нет одного корневого слова.
SUPERLATIVE_PHRASES = ("№1", "№ 1", "номер 1", "номер один")


def build_draft(
    *,
    cluster_name: str,
    keywords: tuple[str, ...],
    selling_points: tuple[str, ...],
    region: str | None = None,
    internal_links: tuple[tuple[str, str], ...] = (),
) -> AdDraft:
    """Собирает черновик объявления для одной группы.

    Первый заголовок — сама ключевая фраза. Это не отсутствие фантазии, а
    основной способ поднять релевантность: Директ подсвечивает совпадение с
    запросом жирным, и человек видит в объявлении ровно то, что искал.
    """
    title = _capitalize(cluster_name)
    violations: list[Violation] = []

    if len(title) > MAX_TITLE:
        # Фраза длиннее заголовка встречается: «остекление балконов под ключ
        # недорого в твери». Обрезать её по символам нельзя — получится обрубок,
        # поэтому режем по словам и сообщаем об этом.
        title = _trim_words(title, MAX_TITLE)
        violations.append(
            Violation(
                Problem.TOO_LONG,
                "заголовок",
                f"Ключевая фраза длиннее {MAX_TITLE} символов, заголовок сокращён по словам",
            )
        )

    usable = [point for point in selling_points if len(point) <= MAX_TITLE_2]
    title_2 = usable[0] if usable else None

    text = _build_text(selling_points, region)
    if not text:
        violations.append(
            Violation(
                Problem.NOTHING_TO_SAY,
                "текст",
                "На странице не нашлось, что предложить: нет ни цены, ни срока, "
                "ни гарантии. Текст придётся написать вручную.",
            )
        )
        text = ""

    callouts = tuple(
        point for point in selling_points if len(point) <= MAX_CALLOUT and point != title_2
    )[:MAX_CALLOUTS]

    sitelinks = _sitelinks(internal_links, exclude=cluster_name)

    draft = AdDraft(
        cluster=cluster_name,
        title=title,
        title_2=title_2,
        text=text,
        display_path=_display_path(cluster_name),
        callouts=callouts,
        sitelinks=sitelinks,
        keywords=keywords,
    )

    return replace(draft, violations=tuple(violations) + check(draft))


def check(draft: AdDraft) -> tuple[Violation, ...]:
    """Проверяет черновик по правилам Директа.

    Проверяется то, что проверяемо: длины и слова, из-за которых объявление
    отклоняют. Оценивать, «хорош» ли текст, модуль не берётся — это не вопрос
    правил.
    """
    found: list[Violation] = []

    for value, limit, name in (
        (draft.title, MAX_TITLE, "заголовок"),
        (draft.title_2 or "", MAX_TITLE_2, "второй заголовок"),
        (draft.text, MAX_TEXT, "текст"),
        (draft.display_path or "", MAX_DISPLAY_PATH, "отображаемая ссылка"),
    ):
        if len(value) > limit:
            found.append(
                Violation(
                    Problem.TOO_LONG,
                    name,
                    f"{len(value)} символов вместо {limit} — Директ не примет",
                )
            )

    whole = " ".join(filter(None, (draft.title, draft.title_2, draft.text)))
    lowered = whole.lower()

    banned = {stem(word) for word in SUPERLATIVES}
    flagged = next((word for word in tokenize(whole) if stem(word) in banned), None)
    if flagged is None:
        flagged = next((phrase for phrase in SUPERLATIVE_PHRASES if phrase in lowered), None)

    if flagged is not None:
        found.append(
            Violation(
                Problem.UNPROVEN_SUPERLATIVE,
                "текст",
                f"«{flagged}» требует документального подтверждения — без него отказ",
            )
        )

    for word in whole.split():
        letters = [ch for ch in word if ch.isalpha()]
        # Аббревиатуры из трёх букв и короче — норма: ПВХ, СПб, IT.
        if len(letters) > 3 and all(ch.isupper() for ch in letters):
            found.append(
                Violation(
                    Problem.CAPS,
                    "текст",
                    f"«{word}» набрано заглавными — Директ такое отклоняет",
                )
            )
            break

    return tuple(found)


def _build_text(selling_points: tuple[str, ...], region: str | None) -> str:
    """Собирает текст из фрагментов, пока он помещается в лимит."""
    parts: list[str] = []
    length = 0

    for point in selling_points:
        addition = len(point) + (2 if parts else 0)
        if length + addition > MAX_TEXT:
            continue
        parts.append(point)
        length += addition

    if not parts:
        return ""

    text = ". ".join(parts)

    # Регион дописывается только если помещается целиком. Обрезанный до «в
    # Твер» он хуже, чем его отсутствие.
    if region:
        suffix = f". {region}"
        if len(text) + len(suffix) <= MAX_TEXT:
            text += suffix

    return text


def _display_path(cluster_name: str) -> str | None:
    """Отображаемая ссылка из первого значимого слова группы.

    Она видна человеку в выдаче и должна читаться как раздел сайта. Настоящий
    путь при этом остаётся прежним — Директ показывает эту строку вместо него.
    """
    words = [word for word in cluster_name.split() if len(word) > 3]
    if not words:
        return None

    path = words[0].strip(",.").lower()
    return path[:MAX_DISPLAY_PATH] if path else None


def _capitalize(phrase: str) -> str:
    return phrase[:1].upper() + phrase[1:] if phrase else phrase


def _trim_words(text: str, limit: int) -> str:
    """Обрезает по словам, не по символам: обрубок слова читается как опечатка."""
    words = text.split()
    result: list[str] = []

    for word in words:
        candidate = " ".join([*result, word])
        if len(candidate) > limit:
            break
        result.append(word)

    return " ".join(result) if result else text[:limit]


#: Сколько черновиков готовить на группу. Директу для сравнения нужно минимум
#: два: с одним объявлением тестировать нечего, а автостратегии не на чем
#: учиться. Больше трёх — это уже дробление показов между вариантами, каждый из
#: которых собирает статистику втрое дольше.
DRAFTS_PER_GROUP = 3


def build_variants(
    *,
    cluster_name: str,
    keywords: tuple[str, ...],
    selling_points: tuple[str, ...],
    region: str | None = None,
    internal_links: tuple[tuple[str, str], ...] = (),
) -> tuple[AdDraft, ...]:
    """Собирает несколько черновиков на одну группу.

    Варианты отличаются вторым заголовком и порядком фрагментов в тексте: это
    ровно то, что имеет смысл сравнивать. Менять между вариантами первый
    заголовок нельзя — он повторяет ключевую фразу, и подмена его убила бы
    релевантность, ради которой он таким и сделан.

    Если фрагментов на странице мало, вариантов будет меньше трёх. Это честнее,
    чем собрать три почти одинаковых объявления: тест между ними ничего не
    покажет, а специалист потратит на него недели.
    """
    if not selling_points:
        return (
            build_draft(
                cluster_name=cluster_name,
                keywords=keywords,
                selling_points=(),
                region=region,
                internal_links=internal_links,
            ),
        )

    variants: list[AdDraft] = []
    seen: set[tuple[str | None, str]] = set()

    for shift in range(min(DRAFTS_PER_GROUP, len(selling_points))):
        # Сдвиг переставляет фрагменты по кругу: во втором заголовке оказывается
        # следующий, а текст начинается с него же.
        rotated = selling_points[shift:] + selling_points[:shift]

        draft = build_draft(
            cluster_name=cluster_name,
            keywords=keywords,
            selling_points=rotated,
            region=region,
            internal_links=internal_links,
        )

        key = (draft.title_2, draft.text)
        if key in seen:
            # Совпавший вариант не добавляется: два одинаковых объявления в
            # группе — это не тест, а разделённые пополам показы.
            continue

        seen.add(key)
        variants.append(draft)

    return tuple(variants)


def _sitelinks(links: tuple[tuple[str, str], ...], *, exclude: str) -> tuple[Sitelink, ...]:
    """Отбирает быстрые ссылки для объявления.

    Раздел, совпадающий с темой самой группы, пропускается: вести из объявления
    «Окна ПВХ» в раздел «Окна ПВХ» значит потратить место на ссылку туда же,
    куда ведёт заголовок.
    """
    banned = {stem(word) for word in tokenize(exclude)}
    chosen: list[Sitelink] = []

    for title, url in links:
        if len(title) > MAX_SITELINK_TITLE:
            continue

        words = {stem(word) for word in tokenize(title)}
        if words and words <= banned:
            continue

        chosen.append(Sitelink(title=title, url=url))
        if len(chosen) == MAX_SITELINKS:
            break

    return tuple(chosen)
