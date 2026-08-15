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
class AdDraft:
    """Черновик одного объявления."""

    #: Группа, для которой собрано объявление.
    cluster: str
    title: str
    title_2: str | None
    text: str
    display_path: str | None
    callouts: tuple[str, ...] = field(default_factory=tuple)
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

    draft = AdDraft(
        cluster=cluster_name,
        title=title,
        title_2=title_2,
        text=text,
        display_path=_display_path(cluster_name),
        callouts=callouts,
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
