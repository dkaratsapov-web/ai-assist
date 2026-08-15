"""Контракты слоя AI.

Обязательная цепочка v0.3 §8: LLM → Structured Output → Validation →
Business Rules → Policy Engine → Action. Прямой путь от модели к внешнему
действию запрещён, поэтому провайдер здесь возвращает не текст, а разобранную и
проверенную структуру.

Разбор ответа регулярными выражениями запрещён отдельным пунктом (v0.3 §9):
любой используемый системой ответ описывается схемой Pydantic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class Sensitivity(StrEnum):
    """Режимы данных из v0.4 §2.3.

    Разделение проходит по содержимому, а не по модулю: один и тот же анализ
    может быть безопасным для сайта и чувствительным для комментария из CRM.
    """

    #: Сайт, конкуренты, семантика, объявления, обезличенная аналитика.
    SAFE_PUBLIC = "safe_public"
    #: Телефоны, почта, ФИО, комментарии CRM, идентификаторы клиентов.
    SENSITIVE = "sensitive"


class AiTask(StrEnum):
    """Задачи, для которых вызывается модель.

    Перечисление нужно не для красоты: маршрутизация по задачам позволяет
    отправлять разные задачи разным провайдерам, а учёт потребления —
    разложить расходы по функциям продукта (v0.3 §64).
    """

    BRIEF_EXTRACTION = "brief_extraction"
    WEBSITE_ANALYSIS = "website_analysis"
    COMPETITOR_EXTRACTION = "competitor_extraction"
    INTENT_CLASSIFICATION = "intent_classification"
    CLUSTERING = "clustering"
    AD_GENERATION = "ad_generation"
    RECOMMENDATION = "recommendation"
    ASSISTANT_ANSWER = "assistant_answer"


@dataclass(frozen=True, slots=True)
class UntrustedContent:
    """Внешний текст, приходящий в запрос.

    Любой внешний текст — сайт клиента, страница конкурента, поисковый запрос,
    комментарий из CRM — считается данными, а не инструкцией для модели
    (v0.3 §98). Отдельный тип нужен, чтобы такой текст было невозможно случайно
    подставить в системную часть запроса: провайдер обязан разметить его как
    недоверенный.
    """

    source: str
    text: str
    #: Идентификатор источника для последующей ссылки в evidence.
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class AiRequest(Generic[PayloadT]):
    task: AiTask
    sensitivity: Sensitivity
    #: Схема ответа. Ответ, не прошедший её, отбрасывается.
    response_model: type[PayloadT]
    #: Инструкция разработчика. Формируется только нами.
    instruction: str
    #: Внешние данные. Инструкциями внутри них система не руководствуется.
    content: tuple[UntrustedContent, ...] = ()
    organization_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    #: Подсказки маршрутизации: предпочтительная модель, температура и прочее.
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AiUsage:
    """Потребление одного вызова — основа UsageEvent (v0.4 §13)."""

    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class AiResult(Generic[PayloadT]):
    """Результат вызова модели.

    Хранится краткое объяснение решения, но не внутренние рассуждения модели:
    это прямой запрет v0.3 §10 и §98.
    """

    payload: PayloadT
    confidence: float
    reasoning_summary: str
    usage: AiUsage
    #: Ссылки на источники, подтверждающие вывод (v0.3 §18).
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence должен лежать в диапазоне от 0 до 1")


class AiProviderError(RuntimeError):
    """Сбой провайдера. Наружу не выходит: обрабатывается вызывающим слоем."""


class SensitiveDataNotAllowedError(AiProviderError):
    """Попытка отправить чувствительные данные туда, где это не разрешено.

    По умолчанию персональные данные внешнему провайдеру не отправляются
    (v0.4 §2.3). Ослабить это может только явное решение по обработке ПДн,
    зафиксированное настройкой организации.
    """
