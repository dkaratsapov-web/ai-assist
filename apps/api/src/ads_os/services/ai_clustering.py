"""Группировка фраз моделью.

Расчёт группирует по общим основам слов, и это работает ровно до тех пор, пока
одну вещь называют одними словами. «Пластиковые окна» и «стеклопакеты» для него
разные темы, «остекление балкона» и «застеклить лоджию» — тоже. В кампании это
превращается в две группы вместо одной и в два объявления, конкурирующих за
один и тот же запрос.

Здесь то же самое делает модель, и правило прежнее: **фразы добывает код,
смысл различает модель.** Список приходит из ядра — ни одной новой фразы
модель не придумывает, и придумать не может: в ответ она возвращает номера
строк, а не тексты.

Почему номера, а не тексты. Модель, переписывающая фразы, — это модель,
незаметно правящая ядро: «пластиковые окна пвх» превращается в «пластиковые
окна ПВХ», и в кампанию уезжает запрос, которого никто не искал. С номерами
такое невозможно в принципе.

Результат — предложение, а не приговор. Он показывается рядом с текущей
раскладкой, и человек принимает его целиком, частями или не принимает вовсе.
Автоматически применять нельзя: ошибка модели здесь стоит переделанной
структуры кампании.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from .ai import (
    AiProviderError,
    AiRequest,
    AiTask,
    ProviderRegistry,
    Sensitivity,
    UntrustedContent,
)

logger = logging.getLogger(__name__)

#: Сколько фраз отдаём за один раз. Больше — и ответ перестаёт помещаться в
#: отведённую длину, а обрезанный ответ означает потерянные фразы.
MAX_PHRASES = 300

#: Предел на число групп. Без него модель охотно выдаёт по группе на фразу:
#: формально верно, для кампании бесполезно.
MAX_GROUPS = 40

_NAME_LIMIT = 200


class SuggestedGroup(BaseModel):
    """Одна предложенная группа."""

    name: str = Field(description="Короткое название по сути группы, 2-4 слова.")
    #: Номера строк из присланного списка. Тексты фраз модель не возвращает —
    #: см. заголовок модуля.
    lines: list[int] = Field(description="Номера строк, входящих в группу.")
    reason: str = Field(description="Что общего у этих фраз. Одно предложение.")


class Suggestion(BaseModel):
    groups: list[SuggestedGroup]


@dataclass(frozen=True, slots=True)
class Group:
    """Предложенная группа, уже сопоставленная с настоящими фразами."""

    name: str
    phrases: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Result:
    """Итог обращения к модели.

    Отказ — не исключение: группировка моделью дополняет расчёт, а не заменяет
    его. Существующая раскладка при неудаче остаётся на месте.
    """

    groups: tuple[Group, ...] = field(default_factory=tuple)
    #: Почему предложения нет. Показывается вместо пустого места.
    reason: str = ""
    confidence: float = 0.0
    model: str = ""
    tokens: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.groups)


INSTRUCTION = """Разложи поисковые запросы по группам для контекстной рекламы.

Правило группировки одно: в одной группе оказываются запросы, на которые
отвечает одно и то же объявление и одна и та же страница сайта. Разные слова —
не повод разделять: «пластиковые окна» и «стеклопакеты» это одно, «остекление
балкона» и «застеклить лоджию» — тоже одно.

Разделять нужно там, где различается намерение или товар: продажа и ремонт,
цена и отзывы, разные виды услуги.

Требования к ответу:
- В поле lines указывай только номера строк из присланного списка. Тексты
  запросов не переписывай и новых не добавляй.
- Каждая строка должна попасть ровно в одну группу. Ничего не теряй.
- Название группы — 2-4 слова по сути, без слов «группа», «запросы», «ключи».
- Групп из одной строки избегай: объявление на один запрос не собирают.
- Не больше сорока групп."""


async def suggest(
    phrases: list[str],
    *,
    registry: ProviderRegistry | None = None,
    organization_id: Any = None,
    project_id: Any = None,
) -> Result:
    """Просит модель разложить фразы. Никогда не бросает исключений."""
    registry = registry or _registry()
    if registry is None:
        return Result(reason="Группировка моделью не настроена.")

    # Заглушка выдаёт валидный по схеме, но выдуманный ответ. Предложить его
    # как раскладку значило бы предложить человеку перестроить кампанию по
    # случайным числам.
    if registry.resolve(AiTask.CLUSTERING, Sensitivity.SAFE_PUBLIC).name == "stub":
        return Result(reason="Группировка моделью не подключена.")

    items = [text for text in phrases if text.strip()][:MAX_PHRASES]
    if len(items) < 2:
        return Result(reason="Для группировки нужно хотя бы две фразы.")

    numbered = "\n".join(f"{index}. {text}" for index, text in enumerate(items, start=1))

    request: AiRequest[Suggestion] = AiRequest(
        task=AiTask.CLUSTERING,
        # Поисковые запросы — публичные данные: их вводят в поиск миллионы
        # человек, и персонального в них нет.
        sensitivity=Sensitivity.SAFE_PUBLIC,
        response_model=Suggestion,
        instruction=INSTRUCTION,
        content=(UntrustedContent(source="запросы", text=numbered),),
        organization_id=organization_id,
        project_id=project_id,
    )

    try:
        result = await registry.complete(request)
    except AiProviderError as error:
        logger.info("группировка моделью не выполнена", extra={"reason": str(error)[:200]})
        return Result(reason=_reason(error))
    except Exception as error:
        logger.warning("группировка моделью сорвалась", extra={"error": type(error).__name__})
        return Result(reason="Группировка моделью не выполнена из-за сбоя.")

    return Result(
        groups=_resolve(result.payload, items),
        confidence=result.confidence,
        model=result.usage.model,
        tokens=result.usage.total_tokens,
    )


def _resolve(suggestion: Suggestion, items: list[str]) -> tuple[Group, ...]:
    """Переводит номера строк обратно во фразы.

    Здесь же чинятся две ошибки, которые модель делает регулярно и которые
    иначе испортили бы ядро: несуществующий номер и одна фраза в двух группах.
    Первое молча выбрасывается, второе достаётся первой группе — а всё, что не
    попало никуда, возвращается отдельной группой, чтобы фразы не пропали.
    """
    used: set[int] = set()
    groups: list[Group] = []

    for group in suggestion.groups[:MAX_GROUPS]:
        phrases: list[str] = []
        for line in group.lines:
            index = line - 1
            if 0 <= index < len(items) and index not in used:
                used.add(index)
                phrases.append(items[index])

        name = " ".join(group.name.split())[:_NAME_LIMIT]
        if phrases and name:
            groups.append(Group(name=name, phrases=tuple(phrases), reason=group.reason[:300]))

    # Потерянные фразы. Модель обещает не терять ничего, но обещание — не
    # гарантия, а фраза, исчезнувшая из раскладки, исчезла бы и из кампании.
    missing = [text for index, text in enumerate(items) if index not in used]
    if missing:
        groups.append(
            Group(
                name="Не разложено моделью",
                phrases=tuple(missing),
                reason="Эти фразы модель не отнесла ни к одной группе. Разложите их сами.",
            )
        )

    return tuple(groups)


def _registry() -> ProviderRegistry | None:
    from .ai import build_registry

    try:
        return build_registry()
    except Exception as error:
        logger.warning("провайдер модели не собран", extra={"error": type(error).__name__})
        return None


def _reason(error: AiProviderError) -> str:
    text = str(error).lower()
    if "ключ" in text:
        return "Группировка моделью не настроена: не принят ключ доступа."
    if "перегружена" in text or "недоступна" in text:
        return "Модель сейчас недоступна. Попробуйте позже."
    return "Группировка моделью не выполнена."
