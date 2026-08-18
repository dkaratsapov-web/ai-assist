"""Разбор посадочной страницы моделью.

Правило, по которому здесь всё устроено: **факты добывает код, суждения выносит
модель**. Есть ли на странице цены, форма, политика обработки данных, счётчик
Метрики — это проверяемые факты, и их считает обычный разбор. Он не ошибается и
не выдумывает. А вот «предложение размытое», «главное возражение не закрыто»,
«обещание в объявлении не совпадает с тем, что человек видит на странице» — это
суждения, и здесь код бессилен: список слов-маркеров такое не ловит.

Отсюда две вещи, которые важнее всего в этом модуле.

**Мнение не влияет на балл.** Балл готовности и блокировки запуска считаются
только по фактам. Модель ошибается, и ошибка в её оценке не должна превращаться
в «запускать нельзя» или в лишние баллы. Разбор показывается отдельным блоком и
подписан как мнение.

**Модель получает уже установленные факты.** Иначе она начинает пересказывать
то, что и так проверено, и вдобавок ошибаться в этом: «цен на странице нет»,
когда они есть. Факты передаются в задании, свободный текст страницы — отдельно
и с пометкой, что это данные, а не указания.

Контакты из текста вычищаются: чтобы оценить предложение, телефон не нужен.
Провайдер тут внешний, и всё, что можно ему не отправлять, ему не отправляется.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from selectolax.parser import HTMLParser

from .ai import (
    AiProviderError,
    AiRequest,
    AiTask,
    ProviderRegistry,
    Sensitivity,
    UntrustedContent,
)
from .audit import PageSignals
from .redact import redact

logger = logging.getLogger(__name__)

#: Сколько текста страницы уходит модели. Дальше начинается подвал, каталог и
#: повторы: на суждение о предложении они не влияют, а стоят денег за каждый
#: вызов.
MAX_TEXT_CHARS = 12_000

#: Сколько замечаний оставляем. Список из тридцати пунктов человек не читает —
#: он его закрывает.
MAX_NOTES = 8

_TEXT_LIMIT = 400
_INVISIBLE = ("script", "style", "noscript", "template", "svg")


class Topic(StrEnum):
    """О чём замечание."""

    #: Что именно предлагают и чем это отличается от соседних предложений.
    OFFER = "offer"
    #: Сомнения, с которыми человек приходит: цена, сроки, качество, риск.
    OBJECTIONS = "objections"
    #: Как написано: канцелярит, «мы — динамично развивающаяся компания».
    LANGUAGE = "language"
    #: Совпадает ли обещание рекламы с тем, что человек видит на странице.
    MATCH = "match"
    #: Порядок изложения: до чего человек дойдёт, а до чего не доскроллит.
    STRUCTURE = "structure"


class Grade(StrEnum):
    GOOD = "good"
    WEAK = "weak"
    MISSING = "missing"


class ReviewNote(BaseModel):
    """Одно замечание.

    Обязательно с цитатой: без неё замечание невозможно проверить, и спорить с
    ним человеку придётся вслепую. Пустая цитата допускается ровно для случая
    «этого на странице нет вовсе».
    """

    topic: Topic
    grade: Grade
    what: str = Field(description="Что видно на странице. Одно предложение.")
    fix: str = Field(description="Что с этим сделать. Одно предложение.")
    quote: str = Field(
        description="Точная цитата со страницы. Пустая строка, если речь об отсутствующем."
    )


class SiteReview(BaseModel):
    """Разбор целиком."""

    summary: str = Field(description="Общее впечатление в двух предложениях.")
    strongest: str = Field(description="Самое сильное место страницы.")
    weakest: str = Field(description="Что мешает больше всего.")
    notes: list[ReviewNote]


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """Итог обращения к модели.

    Отказ — это не исключение: разбор моделью дополняет проверку сайта, а не
    заменяет её. Проверка, упавшая из-за недоступной модели, была бы хуже, чем
    проверка без мнения.
    """

    review: SiteReview | None = None
    #: Почему мнения нет. Показывается человеку вместо пустого места.
    reason: str = ""
    confidence: float = 0.0
    model: str = ""
    #: Сколько токенов стоил вызов. Уходит в учёт потребления (v0.4 §13):
    #: разбор моделью — единственная часть проверки сайта, которая стоит денег
    #: за каждый запуск, и не видеть этих расходов нельзя.
    tokens: int = 0

    @property
    def ok(self) -> bool:
        return self.review is not None

    def as_stored(self) -> dict[str, Any]:
        """Вид, в котором разбор ложится в базу и уходит на экран."""
        if self.review is None:
            return {"available": False, "reason": self.reason}

        return {
            "available": True,
            "summary": self.review.summary[:_TEXT_LIMIT],
            "strongest": self.review.strongest[:_TEXT_LIMIT],
            "weakest": self.review.weakest[:_TEXT_LIMIT],
            "confidence": self.confidence,
            "model": self.model,
            "notes": [
                {
                    "topic": note.topic.value,
                    "grade": note.grade.value,
                    "what": note.what[:_TEXT_LIMIT],
                    "fix": note.fix[:_TEXT_LIMIT],
                    "quote": note.quote[:_TEXT_LIMIT],
                }
                for note in self.review.notes[:MAX_NOTES]
            ],
        }


def page_text(html: str) -> str:
    """Видимый текст страницы без скриптов, стилей и контактов."""
    tree = HTMLParser(html)
    for node in tree.css(",".join(_INVISIBLE)):
        node.decompose()
    return redact(tree.text(separator=" ", strip=True))[:MAX_TEXT_CHARS]


def known_facts(signals: PageSignals) -> str:
    """Факты, уже установленные обычным разбором.

    Передаются модели, чтобы она не пересказывала проверенное и не ошибалась в
    нём. Её работа начинается там, где эти факты заканчиваются: не «есть ли
    цена», а «понятно ли из неё, сколько человек заплатит».
    """
    form = f"есть, полей — {signals.max_form_fields}" if signals.forms else "нет"
    lines = [
        f"Заголовок страницы: {signals.title or 'нет'}",
        f"Заголовок H1: {'; '.join(signals.h1) if signals.h1 else 'нет'}",
        f"Цены на странице: {'есть' if signals.prices else 'нет'}",
        f"Форма заявки: {form}",
        f"Кнопок призыва к действию: {signals.cta_buttons}",
        f"Телефон: {'есть' if signals.phones else 'нет'}",
        f"Мессенджеры: {', '.join(signals.messengers) if signals.messengers else 'нет'}",
        f"Отзывы: {'есть' if signals.has_reviews else 'нет'}",
        f"Реквизиты компании: {'есть' if signals.has_company_details else 'нет'}",
        f"Объём текста: {signals.text_length} символов",
    ]
    return "\n".join(lines)


INSTRUCTION = """Ты разбираешь посадочную страницу, на которую будет вести контекстная реклама.

Оцени ровно пять вещей, и только их:
1. offer — что именно предлагают и чем это отличается от соседних предложений.
   Не «есть ли оффер», а понятно ли, что человек получит и за сколько.
2. objections — закрыты ли сомнения, с которыми человек приходит: цена, сроки,
   качество, риск потерять деньги.
3. language — как написано. Канцелярит, «динамично развивающаяся компания»,
   обещания без содержания.
4. match — совпадает ли обещание, за которым человек пришёл из рекламы, с тем,
   что он видит первым экраном.
5. structure — порядок изложения: дойдёт ли человек до главного или оно ниже
   трёх экранов.

Правила:
- Перечисленные ниже факты уже проверены кодом. Не пересказывай их и не спорь
  с ними.
- На каждое замечание приводи точную цитату со страницы. Цитату не сочиняй:
  если приводить нечего, оставь поле пустым и поставь grade=missing.
- Не больше восьми замечаний. Лучше три важных, чем восемь любых.
- Пиши по-русски, короткими предложениями, без рекламных оборотов.
- Советов по поисковой оптимизации не давай: страница оценивается для
  человека, а не для поисковика."""

async def review_page(
    html: str,
    signals: PageSignals,
    *,
    registry: ProviderRegistry | None = None,
    url: str = "",
    organization_id: Any = None,
    project_id: Any = None,
) -> ReviewResult:
    """Просит модель разобрать страницу. Никогда не бросает исключений."""
    registry = registry or _registry()
    if registry is None:
        return ReviewResult(reason="Разбор моделью не настроен.")

    # Заглушка выдаёт валидный по схеме, но выдуманный ответ — она для того и
    # сделана. Показать его как мнение модели значит соврать человеку, поэтому
    # разбора при невыбранном провайдере просто нет.
    if registry.resolve(AiTask.WEBSITE_ANALYSIS, Sensitivity.SAFE_PUBLIC).name == "stub":
        return ReviewResult(
            reason="Разбор моделью не подключён: проверка идёт только по фактам."
        )

    text = page_text(html)
    if len(text) < 200:
        # Пустой каркас или страница на скриптах, которую не удалось
        # отрисовать. Просить модель разобрать пустоту — платить за выдумку.
        return ReviewResult(reason="На странице слишком мало текста для разбора.")

    request: AiRequest[SiteReview] = AiRequest(
        task=AiTask.WEBSITE_ANALYSIS,
        # Контакты из текста вычищены, остальное на странице опубликовано
        # самой компанией.
        sensitivity=Sensitivity.SAFE_PUBLIC,
        response_model=SiteReview,
        instruction=f"{INSTRUCTION}\n\nУже проверено кодом:\n{known_facts(signals)}",
        content=(UntrustedContent(source=url or "страница", text=text, source_id=url or None),),
        organization_id=organization_id,
        project_id=project_id,
    )

    try:
        result = await registry.complete(request)
    except AiProviderError as error:
        logger.info("разбор моделью не выполнен", extra={"reason": str(error)[:200]})
        return ReviewResult(reason=_reason(error))
    except Exception as error:
        logger.warning("разбор моделью сорвался", extra={"error": type(error).__name__})
        return ReviewResult(reason="Разбор моделью не выполнен из-за сбоя.")

    return ReviewResult(
        review=result.payload,
        confidence=result.confidence,
        model=result.usage.model,
        tokens=result.usage.total_tokens,
    )


def _registry() -> ProviderRegistry | None:
    """Реестр провайдеров из настроек.

    Ошибка в настройках роняет запуск приложения — так и задумано. Но здесь,
    в фоновой задаче, она означала бы упавшую проверку сайта из-за опечатки в
    переменной окружения, поэтому мнения просто не будет.
    """
    from .ai import build_registry

    try:
        return build_registry()
    except Exception as error:
        logger.warning("провайдер модели не собран", extra={"error": type(error).__name__})
        return None


def _reason(error: AiProviderError) -> str:
    """Причина человеческим языком.

    Текст исключения наружу не уходит (v0.3 §137), но и «что-то пошло не так»
    здесь не годится: не подключённая модель и перегруженная модель требуют
    разных действий, и человек должен понимать, ждать ему или настраивать.
    """
    text = str(error).lower()
    if "ключ" in text:
        return "Разбор моделью не настроен: не принят ключ доступа."
    if "перегружена" in text or "недоступна" in text:
        return "Модель сейчас недоступна. Разбор можно повторить позже."
    return "Разбор моделью не выполнен."
