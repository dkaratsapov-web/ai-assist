"""Контракт рекламной площадки.

Отдельный слой между продуктом и Яндекс Директом нужен не ради абстрактной
чистоты. Причины конкретные:

Первая — до прохождения проверок безопасности (v0.3 §114) продукт обязан
работать на заглушке, даже если токен уже получен (v0.4 §2.1). Без общего
контракта «работать на заглушке» означало бы «половина кода закомментирована».

Вторая — у Директа платный по расходу баллов API и жёсткие суточные лимиты.
Код, который дёргает его напрямую откуда попало, невозможно ни посчитать, ни
ограничить. Здесь же расход виден в одном месте.

Третья — ошибки площадки должны попадать к человеку словами, а не кодами.
«Ошибка 152» ничего не говорит; «закончились баллы API на сегодня, следующая
попытка после полуночи по Москве» говорит, что делать.

Типы здесь намеренно свои, а не отражение полей Директа один в один: продукту
нужно то, что он показывает и считает, а не всё, что отдаёт площадка.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable


class AdPlatformError(Exception):
    """Площадка не смогла выполнить запрос.

    Несёт человеческую формулировку: слой выше показывает `message` как есть.
    """

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        detail: str | None = None,
        request_id: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail = detail
        self.request_id = request_id
        #: Имеет ли смысл повторить тот же запрос позже без изменений.
        self.retryable = retryable


class AuthError(AdPlatformError):
    """Токен не принят или у него нет прав на этого рекламодателя."""


class QuotaError(AdPlatformError):
    """Закончились баллы API или превышен лимит запросов.

    Отдельный тип, потому что реакция принципиально другая: не «поправьте
    данные», а «подождите». Повторять немедленно бессмысленно и вредно — это
    ускоряет исчерпание суточного лимита.
    """


class CampaignState(StrEnum):
    """Состояние кампании в терминах продукта.

    Директ различает `State` (архивная, включённая, остановленная) и `Status`
    (принята, отклонена, на модерации). Для наших экранов важен один вопрос —
    крутится или нет, — поэтому состояния сведены к тому, что видно человеку.
    """

    RUNNING = "running"
    STOPPED = "stopped"
    ON_MODERATION = "on_moderation"
    REJECTED = "rejected"
    DRAFT = "draft"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class Advertiser:
    """Рекламодатель, доступный по нашему токену.

    В схеме представителя токен один, а рекламодателей много: каждый запрос
    указывает нужного заголовком. Логин здесь — то, что подставляется в этот
    заголовок.
    """

    login: str
    name: str
    currency: str
    #: Может ли представитель менять кампании, а не только читать их.
    can_edit: bool = False


@dataclass(frozen=True, slots=True)
class Campaign:
    """Кампания у рекламодателя."""

    id: int
    name: str
    state: CampaignState
    daily_budget: Decimal | None = None
    #: Причина отклонения модерацией. Пусто у всех остальных состояний.
    reject_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DailyStats:
    """Расход и результат за один день по одной кампании.

    Показов и кликов достаточно для наших экранов; глубина разреза (по фразам,
    по регионам) добавляется тогда, когда появится экран, который её покажет.
    Просить у площадки больше, чем показываем, значит тратить баллы впустую.
    """

    campaign_id: int
    on_date: date
    impressions: int
    clicks: int
    cost: Decimal
    conversions: int | None = None


@dataclass(frozen=True, slots=True)
class Usage:
    """Сколько баллов API израсходовано.

    Директ возвращает это заголовком на каждый ответ. Значение сохраняется и
    показывается: узнать об исчерпании лимита в момент, когда он уже исчерпан,
    поздно — работа встаёт до полуночи по Москве.
    """

    spent: int = 0
    rest: int = 0
    limit: int = 0

    @property
    def is_low(self) -> bool:
        """Осталось меньше десятой части суточного лимита."""
        return self.limit > 0 and self.rest * 10 < self.limit


@dataclass(slots=True)
class PlatformResponse:
    """Ответ площадки вместе с расходом баллов."""

    advertisers: tuple[Advertiser, ...] = ()
    campaigns: tuple[Campaign, ...] = ()
    stats: tuple[DailyStats, ...] = ()
    usage: Usage = field(default_factory=Usage)


@runtime_checkable
class AdPlatform(Protocol):
    """Что продукт умеет спрашивать у рекламной площадки.

    Только чтение. Публикация кампаний и правка ставок сюда не входят
    намеренно: их нельзя проверить, не имея настоящего аккаунта, а метод,
    который никто ни разу не выполнил, — это не готовая функция, а обещание.
    Они добавятся вместе с доступом и вместе с проверкой на живых данных.
    """

    #: Имя для журналов и экрана настроек: видно, на чём именно всё работает.
    name: str

    #: Работает ли адаптер с настоящими деньгами. Продукт обязан показывать это
    #: человеку, а не выяснять по косвенным признакам.
    is_live: bool

    async def advertisers(self) -> PlatformResponse:
        """Кто доступен по нашему токену."""
        ...

    async def campaigns(self, advertiser_login: str) -> PlatformResponse:
        """Кампании одного рекламодателя."""
        ...

    async def daily_stats(
        self, advertiser_login: str, *, since: date, until: date
    ) -> PlatformResponse:
        """Расход по дням за период."""
        ...
