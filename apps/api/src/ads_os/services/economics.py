"""Economics Engine.

Чистый расчёт экономики проекта. Никакой базы, никакой сети: те же входные
данные всегда дают тот же результат, поэтому модуль полностью покрывается
модульными тестами и служит опорой для всех последующих рекомендаций (v0.3 §19).

Главная идея модуля — не формулы, а честность. Система обязана различать три
разных ситуации: величина посчитана по данным клиента, величина посчитана с
нашим допущением, величина не может быть посчитана вовсе. Правдоподобное число
на месте третьего случая хуже пробела: на него будут опираться при решениях о
деньгах (v0.4 §5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

#: Доля валовой прибыли, которую по умолчанию считаем допустимой к трате на
#: привлечение, если клиент не задал целевой CAC. Значение спорное и потому
#: помечает производные метрики как ориентировочные.
DEFAULT_MARKETING_SHARE = Decimal("0.5")

_MONEY = Decimal("0.01")
_RATE = Decimal("0.0001")


class Availability(StrEnum):
    """Насколько можно доверять значению.

    Совпадает с состояниями карточки KPI в интерфейсе — одно и то же понятие не
    должно называться по-разному на разных концах системы.
    """

    AVAILABLE = "available"
    PROXY = "proxy"
    UNAVAILABLE = "unavailable"


class EconomicsMode(StrEnum):
    """Полнота экономики (v0.4 §5)."""

    #: Заполнено всё: доступна оптимизация по продажам, CAC и марже.
    COMPLETE = "complete"
    #: Обязательное заполнено, рекомендованное — нет. Проект ведётся, но
    #: достоверны только CPL и конверсии.
    LIMITED = "limited"
    #: Нет обязательных данных: считать нечего.
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, slots=True)
class Metric:
    """Значение метрики вместе с оценкой его достоверности."""

    value: Decimal | None
    availability: Availability
    #: Что нужно заполнить, чтобы значение стало достоверным.
    reason: str | None = None

    @classmethod
    def available(cls, value: Decimal) -> Metric:
        return cls(value=value, availability=Availability.AVAILABLE)

    @classmethod
    def proxy(cls, value: Decimal, reason: str) -> Metric:
        return cls(value=value, availability=Availability.PROXY, reason=reason)

    @classmethod
    def unavailable(cls, reason: str) -> Metric:
        return cls(value=None, availability=Availability.UNAVAILABLE, reason=reason)


@dataclass(frozen=True, slots=True)
class EconomicsInput:
    """Входные данные расчёта.

    Отдельный тип, а не модель БД: расчёт не должен зависеть от способа
    хранения, иначе его нельзя будет вызвать из фоновой задачи или прогнать в
    тесте без базы.
    """

    monthly_budget: Decimal | None = None
    average_order_value: Decimal | None = None
    expected_value: Decimal | None = None
    main_conversion: str | None = None

    margin_percent: Decimal | None = None
    lead_to_sale_rate: Decimal | None = None
    target_cac: Decimal | None = None
    target_cpl: Decimal | None = None
    target_marketing_share: Decimal | None = None
    #: Ожидаемая цена клика и конверсия посадочной. Только вместе они дают
    #: настоящий прогноз заявок: без них известна лишь ёмкость бюджета.
    expected_cpc: Decimal | None = None
    site_conversion_rate: Decimal | None = None

    def __post_init__(self) -> None:
        _require_positive("monthly_budget", self.monthly_budget)
        _require_positive("average_order_value", self.average_order_value)
        _require_positive("expected_value", self.expected_value)
        _require_positive("target_cac", self.target_cac)
        _require_positive("target_cpl", self.target_cpl)
        _require_positive("expected_cpc", self.expected_cpc)

        if self.site_conversion_rate is not None and not (
            Decimal(0) < self.site_conversion_rate <= Decimal(1)
        ):
            raise ValueError("site_conversion_rate должен лежать в диапазоне от 0 до 1")

        if self.margin_percent is not None and not (
            Decimal(0) <= self.margin_percent <= Decimal(100)
        ):
            raise ValueError("margin_percent должен лежать в диапазоне от 0 до 100")

        if self.lead_to_sale_rate is not None and not (
            Decimal(0) < self.lead_to_sale_rate <= Decimal(1)
        ):
            raise ValueError("lead_to_sale_rate должен лежать в диапазоне от 0 до 1")

        if self.target_marketing_share is not None and not (
            Decimal(0) < self.target_marketing_share <= Decimal(1)
        ):
            raise ValueError("target_marketing_share должен лежать в диапазоне от 0 до 1")

    @property
    def order_value(self) -> Decimal | None:
        """Средний чек либо заменяющая его ожидаемая ценность (v0.4 §5)."""
        return self.average_order_value or self.expected_value


@dataclass(frozen=True, slots=True)
class EconomicsSummary:
    mode: EconomicsMode
    #: Незаполненные обязательные поля — без них проект не считается вовсе.
    missing_required: list[str] = field(default_factory=list)
    #: Незаполненные рекомендованные поля — без них недоступна часть метрик.
    missing_recommended: list[str] = field(default_factory=list)
    #: Незаполненные поля прогноза. Без них известна только ёмкость бюджета.
    missing_forecast: list[str] = field(default_factory=list)

    gross_profit_per_sale: Metric = Metric.unavailable("нет данных")
    break_even_cac: Metric = Metric.unavailable("нет данных")
    break_even_cpl: Metric = Metric.unavailable("нет данных")
    break_even_roas: Metric = Metric.unavailable("нет данных")
    target_cac: Metric = Metric.unavailable("нет данных")
    target_cpl: Metric = Metric.unavailable("нет данных")
    target_roas: Metric = Metric.unavailable("нет данных")
    monthly_leads_capacity: Metric = Metric.unavailable("нет данных")
    #: Сколько заявок ожидается на самом деле: бюджет → клики → заявки.
    #:
    #: Отличается от ёмкости бюджета принципиально. Ёмкость отвечает «на сколько
    #: заявок хватит денег, если цена окажется целевой»; прогноз — «сколько
    #: заявок будет при известной цене клика и конверсии сайта». На старте цена
    #: почти всегда выше целевой, и путать эти два числа значит планировать по
    #: лучшему из возможных исходов.
    expected_monthly_clicks: Metric = Metric.unavailable("нет данных")
    expected_monthly_leads: Metric = Metric.unavailable("нет данных")
    monthly_sales_capacity: Metric = Metric.unavailable("нет данных")
    projected_revenue: Metric = Metric.unavailable("нет данных")
    projected_gross_profit: Metric = Metric.unavailable("нет данных")

    @property
    def can_optimize_by_sales(self) -> bool:
        """Можно ли оптимизировать по продажам, а не только по стоимости лида.

        Это и есть главная продуктовая цель (v0.3 §2), и она недостижима, пока
        неизвестны маржа и конверсия из лида в продажу.
        """
        return self.mode is EconomicsMode.COMPLETE

    @property
    def cta(self) -> str | None:
        """Подсказка пользователю, что заполнить (v0.4 §5)."""
        if self.mode is EconomicsMode.INSUFFICIENT:
            return "Заполните бюджет, средний чек и основную конверсию, чтобы начать расчёты"
        if self.mode is EconomicsMode.LIMITED:
            return "Заполните экономику, чтобы включить оптимизацию по продажам"
        return None


REQUIRED_FIELDS = ("monthly_budget", "order_value", "main_conversion")
RECOMMENDED_FIELDS = ("margin_percent", "lead_to_sale_rate")

#: Поля, без которых нет настоящего прогноза заявок. В обязательные они не
#: вынесены намеренно: проект без них ведётся, просто вместо прогноза остаётся
#: ёмкость бюджета — и она честно так и называется.
FORECAST_FIELDS = ("expected_cpc", "site_conversion_rate")

_FIELD_LABELS = {
    "monthly_budget": "месячный бюджет",
    "order_value": "средний чек или ожидаемая ценность",
    "main_conversion": "основная конверсия",
    "margin_percent": "маржинальность",
    "lead_to_sale_rate": "конверсия из лида в продажу",
    "expected_cpc": "ожидаемая цена клика",
    "site_conversion_rate": "конверсия посадочной страницы",
}


def evaluate(data: EconomicsInput) -> EconomicsSummary:
    """Считает экономику проекта и достоверность каждой величины."""
    missing_required = [f for f in REQUIRED_FIELDS if getattr(data, f, None) is None]
    missing_recommended = [f for f in RECOMMENDED_FIELDS if getattr(data, f, None) is None]
    missing_forecast = [f for f in FORECAST_FIELDS if getattr(data, f, None) is None]

    if missing_required:
        return EconomicsSummary(
            mode=EconomicsMode.INSUFFICIENT,
            missing_required=[_FIELD_LABELS[f] for f in missing_required],
            missing_recommended=[_FIELD_LABELS[f] for f in missing_recommended],
            missing_forecast=[_FIELD_LABELS[f] for f in missing_forecast],
        )

    mode = EconomicsMode.LIMITED if missing_recommended else EconomicsMode.COMPLETE

    order_value = data.order_value
    assert order_value is not None  # гарантировано проверкой обязательных полей
    budget = data.monthly_budget
    assert budget is not None

    margin = data.margin_percent
    lead_to_sale = data.lead_to_sale_rate

    no_margin = "укажите маржинальность"
    no_conversion = "укажите конверсию из лида в продажу"

    # ── Валовая прибыль и безубыточность ───────────────────────────────────
    if margin is None:
        gross_profit = Metric.unavailable(no_margin)
        break_even_cac = Metric.unavailable(no_margin)
        break_even_roas = Metric.unavailable(no_margin)
    else:
        profit = _money(order_value * margin / Decimal(100))
        gross_profit = Metric.available(profit)
        # Тратя на привлечение ровно валовую прибыль, выходим в ноль: это и есть
        # предельно допустимый CAC.
        break_even_cac = Metric.available(profit)
        break_even_roas = (
            Metric.available(_rate(Decimal(100) / margin))
            if margin > 0
            else Metric.unavailable("при нулевой марже окупаемость недостижима")
        )

    # ── Целевой CAC ────────────────────────────────────────────────────────
    if data.target_cac is not None:
        target_cac = Metric.available(_money(data.target_cac))
    elif gross_profit.value is not None:
        share = data.target_marketing_share or DEFAULT_MARKETING_SHARE
        derived = _money(gross_profit.value * share)
        if data.target_marketing_share is not None:
            target_cac = Metric.available(derived)
        else:
            # Доля прибыли, уходящая на привлечение, — наше допущение, а не
            # факт о бизнесе клиента. Помечаем значение ориентировочным.
            share_percent = int(DEFAULT_MARKETING_SHARE * 100)
            target_cac = Metric.proxy(
                derived,
                f"принято допущение: на привлечение уходит {share_percent}% валовой прибыли",
            )
    else:
        target_cac = Metric.unavailable(no_margin)

    # ── Стоимость лида ─────────────────────────────────────────────────────
    if data.target_cpl is not None:
        target_cpl = Metric.available(_money(data.target_cpl))
    elif target_cac.value is not None and lead_to_sale is not None:
        target_cpl = Metric(
            value=_money(target_cac.value * lead_to_sale),
            availability=target_cac.availability,
            reason=target_cac.reason,
        )
    else:
        target_cpl = Metric.unavailable(no_conversion if margin is not None else no_margin)

    if break_even_cac.value is not None and lead_to_sale is not None:
        break_even_cpl = Metric.available(_money(break_even_cac.value * lead_to_sale))
    else:
        break_even_cpl = Metric.unavailable(no_conversion if margin is not None else no_margin)

    # ── Целевой ROAS ───────────────────────────────────────────────────────
    if target_cac.value is not None and target_cac.value > 0:
        target_roas = Metric(
            value=_rate(order_value / target_cac.value),
            availability=target_cac.availability,
            reason=target_cac.reason,
        )
    else:
        target_roas = Metric.unavailable(no_margin)

    # ── Ёмкость бюджета ────────────────────────────────────────────────────
    if target_cpl.value is not None and target_cpl.value > 0:
        leads = _rate(budget / target_cpl.value)
        leads_capacity = Metric(
            value=leads, availability=target_cpl.availability, reason=target_cpl.reason
        )
    else:
        leads_capacity = Metric.unavailable(target_cpl.reason or no_conversion)

    if leads_capacity.value is not None and lead_to_sale is not None:
        sales = _rate(leads_capacity.value * lead_to_sale)
        sales_capacity = Metric(
            value=sales, availability=leads_capacity.availability, reason=leads_capacity.reason
        )
    else:
        sales_capacity = Metric.unavailable(no_conversion)

    # ── Ожидаемый поток: бюджет → клики → заявки ───────────────────────────
    no_cpc = "укажите ожидаемую цену клика"
    no_site_conversion = "укажите конверсию посадочной страницы"

    if data.expected_cpc is not None and data.expected_cpc > 0:
        clicks = _rate(budget / data.expected_cpc)
        expected_clicks = Metric.available(clicks)
    else:
        expected_clicks = Metric.unavailable(no_cpc)

    if expected_clicks.value is not None and data.site_conversion_rate is not None:
        expected_leads = Metric.available(_rate(expected_clicks.value * data.site_conversion_rate))
    else:
        expected_leads = Metric.unavailable(
            no_site_conversion if expected_clicks.value is not None else no_cpc
        )

    # ── Прогноз ────────────────────────────────────────────────────────────
    if sales_capacity.value is not None:
        revenue = _money(sales_capacity.value * order_value)
        projected_revenue = Metric(
            value=revenue, availability=sales_capacity.availability, reason=sales_capacity.reason
        )
    else:
        projected_revenue = Metric.unavailable(no_conversion)

    if projected_revenue.value is not None and margin is not None:
        profit_total = _money(projected_revenue.value * margin / Decimal(100) - budget)
        projected_gross_profit = Metric(
            value=profit_total,
            availability=projected_revenue.availability,
            reason=projected_revenue.reason,
        )
    else:
        projected_gross_profit = Metric.unavailable(no_margin)

    return EconomicsSummary(
        mode=mode,
        missing_required=[],
        missing_recommended=[_FIELD_LABELS[f] for f in missing_recommended],
        missing_forecast=[_FIELD_LABELS[f] for f in missing_forecast],
        gross_profit_per_sale=gross_profit,
        break_even_cac=break_even_cac,
        break_even_cpl=break_even_cpl,
        break_even_roas=break_even_roas,
        target_cac=target_cac,
        target_cpl=target_cpl,
        target_roas=target_roas,
        monthly_leads_capacity=leads_capacity,
        expected_monthly_clicks=expected_clicks,
        expected_monthly_leads=expected_leads,
        monthly_sales_capacity=sales_capacity,
        projected_revenue=projected_revenue,
        projected_gross_profit=projected_gross_profit,
    )


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _rate(value: Decimal) -> Decimal:
    return value.quantize(_RATE, rounding=ROUND_HALF_UP)


def _require_positive(name: str, value: Decimal | None) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{name} должен быть больше нуля")
