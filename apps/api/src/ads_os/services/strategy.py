"""Стратегия запуска: с чего начинать и почему.

Экономика отвечает на вопрос «сколько можно платить за лид». Она не отвечает
на следующий вопрос, который специалист задаёт себе всегда: какую стратегию
назначения ставок ставить на старте, сколько ждать до первых выводов и хватит
ли вообще объёма, чтобы автостратегия обучилась.

Ответ здесь считается арифметикой, а не подбирается моделью. Причина простая:
такой ответ можно проверить. Специалист, который видит «12 конверсий в неделю,
этого хватает на обучение», может пересчитать сам и либо согласиться, либо
поправить исходные данные. Ответ от нейросети проверить нечем.

Пороговые числа — ориентиры Яндекс Директа, а не законы природы. Они вынесены
в константы и подписаны: когда платформа поменяет требования, править нужно
будет здесь, а не искать числа по тексту.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from .economics import EconomicsMode

#: Сколько конверсий в неделю нужно автостратегии, чтобы обучиться. Ориентир
#: Директа: ниже этого порога стратегия работает неустойчиво — цена конверсии
#: скачет, а открутка то есть, то нет.
CONVERSIONS_PER_WEEK_FOR_LEARNING = 10

#: Минимум, ниже которого оптимизировать по конверсиям бессмысленно вообще:
#: платформе не на чем учиться, и стратегия превращается в лотерею.
MIN_CONVERSIONS_PER_WEEK = 3

#: Сколько конверсий нужно накопить, чтобы делать выводы о кампании. Меньше —
#: это ещё не результат, а разброс: на двадцати лидах разница между двумя
#: группами объявлений почти всегда случайна.
CONVERSIONS_FOR_DECISION = 30

#: Столько недель тест длиться не должен. Если по расчёту выходит больше —
#: проблема не в терпении, а в том, что объёма нет, и это надо сказать прямо.
MAX_REASONABLE_TEST_WEEKS = 8

#: Недель в месяце. Тот же делитель, что использует Директ в своих отчётах.
WEEKS_PER_MONTH = Decimal("4.33")


class BidStrategy(StrEnum):
    """Стратегия назначения ставок на старте."""

    #: Оплата за клики, ручные ставки. Когда конверсий слишком мало для любой
    #: автоматики.
    MANUAL = "manual"
    #: Максимум кликов с ограничением цены. Набирает трафик и статистику, пока
    #: конверсий не хватает.
    MAX_CLICKS = "max_clicks"
    #: Оплата за конверсии. Платформа берёт деньги только за результат — при
    #: небольшом объёме это самый безопасный способ начать.
    PAY_PER_CONVERSION = "pay_per_conversion"
    #: Максимум конверсий с целевой ценой. Требует потока и обученной цели.
    MAX_CONVERSIONS = "max_conversions"


STRATEGY_LABELS: dict[BidStrategy, str] = {
    BidStrategy.MANUAL: "Ручное управление ставками",
    BidStrategy.MAX_CLICKS: "Максимум кликов с ограничением средней цены",
    BidStrategy.PAY_PER_CONVERSION: "Оплата за конверсии",
    BidStrategy.MAX_CONVERSIONS: "Максимум конверсий с целевой ценой",
}


class PlanStatus(StrEnum):
    """Можно ли запускаться."""

    #: Всё сходится: сайт готов, экономика посчитана, объёма хватает.
    READY = "ready"
    #: Запускаться можно, но с оговорками — обычно объёма мало или часть цифр
    #: приблизительная.
    RISKY = "risky"
    #: Сначала нужно что-то исправить.
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class StrategyInput:
    """Что нужно знать, чтобы предложить план.

    Отдельный тип, а не ссылка на модели: расчёт должен вызываться из теста без
    базы, как и расчёт экономики.
    """

    economics_mode: EconomicsMode
    monthly_budget: Decimal | None = None
    #: Ожидаемое число заявок за месяц — берётся из расчёта экономики, чтобы
    #: одно и то же число не считалось здесь по второму разу и не начало
    #: расходиться с экраном экономики.
    monthly_conversions: Decimal | None = None
    #: Оценка построена на допущении, а не на данных клиента.
    conversions_are_proxy: bool = False
    #: Откуда взято число заявок. Это не оттенок формулировки: ёмкость бюджета
    #: отвечает «на сколько заявок хватит денег при целевой цене», а прогноз —
    #: «сколько заявок будет». На старте реальная цена почти всегда выше
    #: целевой, и планировать по ёмкости значит планировать по лучшему исходу.
    conversions_are_forecast: bool = False
    #: Итог аудита сайта. None означает, что аудит не проводился, и это не то
    #: же самое, что «сайт в порядке».
    site_can_launch: bool | None = None


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    """План запуска."""

    status: PlanStatus
    #: Что мешает стартовать прямо сейчас.
    blockers: tuple[str, ...] = ()
    strategy: BidStrategy | None = None
    strategy_label: str | None = None
    #: Почему предложена именно эта стратегия. Без объяснения совет невозможно
    #: ни принять осознанно, ни оспорить.
    strategy_reason: str | None = None
    weekly_conversions: Decimal | None = None
    #: Хватает ли потока, чтобы автостратегия обучилась.
    learning_ready: bool | None = None
    #: Сколько недель до первых обоснованных выводов.
    test_weeks: int | None = None
    #: Сколько денег уйдёт за это время.
    test_budget: Decimal | None = None
    #: Что стоит сделать помимо самого запуска.
    advice: tuple[str, ...] = field(default_factory=tuple)


def build_plan(data: StrategyInput) -> LaunchPlan:
    """Считает план запуска."""
    blockers: list[str] = []
    advice: list[str] = []

    if data.site_can_launch is False:
        blockers.append(
            "Сайт не готов: в аудите есть критические замечания. Пока они не "
            "исправлены, платный трафик потратится впустую."
        )
    elif data.site_can_launch is None:
        # Не блокирует: проект могли вести и без аудита. Но и молчать об этом
        # нельзя — иначе план выглядит подтверждением, что с сайтом всё хорошо.
        advice.append("Проведите аудит сайта — план построен без учёта его состояния.")

    if data.economics_mode is EconomicsMode.INSUFFICIENT:
        blockers.append(
            "Экономика не заполнена: без бюджета, среднего чека и основной "
            "конверсии рассчитать план запуска нечем."
        )
    elif data.economics_mode is EconomicsMode.LIMITED:
        advice.append(
            "Заполните маржинальность и конверсию из лида в продажу — тогда "
            "план будет считаться по продажам, а не только по заявкам."
        )

    if blockers:
        return LaunchPlan(
            status=PlanStatus.BLOCKED, blockers=tuple(blockers), advice=tuple(advice)
        )

    if data.monthly_conversions is None or data.monthly_conversions <= 0:
        return LaunchPlan(
            status=PlanStatus.BLOCKED,
            blockers=(
                "Неизвестна ожидаемая цена заявки, поэтому неизвестно и сколько "
                "заявок даст бюджет. Заполните экономику полностью.",
            ),
            advice=tuple(advice),
        )

    weekly = (data.monthly_conversions / WEEKS_PER_MONTH).quantize(Decimal("0.1"))

    strategy, reason, learning_ready = _choose_strategy(weekly)

    if not data.conversions_are_forecast:
        advice.append(
            "Число заявок посчитано как ёмкость бюджета: столько получится, если "
            "цена заявки окажется целевой. На старте она обычно выше. Укажите "
            "ожидаемую цену клика и конверсию посадочной — тогда план будет "
            "строиться на прогнозе, а не на лучшем исходе."
        )

    if data.conversions_are_proxy:
        advice.append(
            "Ожидаемое число заявок посчитано по допущению, а не по вашим "
            "данным. Укажите целевую цену лида — и план станет точнее."
        )

    test_weeks = _test_duration(weekly)
    if test_weeks is None:
        advice.append(
            f"При таком объёме на {CONVERSIONS_FOR_DECISION} заявок уйдёт больше "
            f"{MAX_REASONABLE_TEST_WEEKS} недель. Выводы придётся делать по "
            "неполной статистике либо увеличивать бюджет или охват."
        )
        test_budget = None
    else:
        test_budget = (
            (data.monthly_budget / WEEKS_PER_MONTH * test_weeks).quantize(Decimal("0.01"))
            if data.monthly_budget is not None
            else None
        )

    if weekly < MIN_CONVERSIONS_PER_WEEK:
        advice.append(
            "Заявок мало для оптимизации по главной цели. Настройте микроцели — "
            "клик по телефону, отправку формы, глубину просмотра — и обучайте "
            "стратегию на них."
        )

    # Непроверенный сайт не даёт статуса готовности. Выдать «можно запускать» и
    # тут же приписать «план построен без учёта состояния сайта» — значит
    # сказать две противоположные вещи в одном экране. Отсутствие проверки не
    # означает, что с сайтом всё хорошо: оно означает, что мы не смотрели.
    status = (
        PlanStatus.READY
        if (
            learning_ready
            and data.site_can_launch is True
            and data.conversions_are_forecast
            and not data.conversions_are_proxy
            and test_weeks is not None
        )
        else PlanStatus.RISKY
    )

    return LaunchPlan(
        status=status,
        blockers=(),
        strategy=strategy,
        strategy_label=STRATEGY_LABELS[strategy],
        strategy_reason=reason,
        weekly_conversions=weekly,
        learning_ready=learning_ready,
        test_weeks=test_weeks,
        test_budget=test_budget,
        advice=tuple(advice),
    )


def _choose_strategy(weekly: Decimal) -> tuple[BidStrategy, str, bool]:
    """Выбирает стратегию по ожидаемому потоку конверсий."""
    if weekly >= CONVERSIONS_PER_WEEK_FOR_LEARNING:
        return (
            BidStrategy.MAX_CONVERSIONS,
            f"Ожидается около {weekly} заявок в неделю — этого хватает, чтобы "
            f"автостратегия обучилась (нужно от {CONVERSIONS_PER_WEEK_FOR_LEARNING}).",
            True,
        )

    if weekly >= MIN_CONVERSIONS_PER_WEEK:
        return (
            BidStrategy.PAY_PER_CONVERSION,
            f"Ожидается около {weekly} заявок в неделю — меньше "
            f"{CONVERSIONS_PER_WEEK_FOR_LEARNING}, при которых автостратегия "
            "работает устойчиво. Оплата за конверсии безопаснее: деньги "
            "списываются за результат, а не за клики.",
            False,
        )

    return (
        BidStrategy.MAX_CLICKS,
        f"Ожидается около {weekly} заявок в неделю. Оптимизировать по "
        "конверсиям не на чем: платформе нужна статистика, которой пока нет. "
        "Начните с трафика и ограничения средней цены клика.",
        False,
    )


def _test_duration(weekly: Decimal) -> int | None:
    """Сколько недель до обоснованных выводов. None — если слишком долго."""
    if weekly <= 0:
        return None
    weeks = math.ceil(CONVERSIONS_FOR_DECISION / float(weekly))
    return weeks if weeks <= MAX_REASONABLE_TEST_WEEKS else None
