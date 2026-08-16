"""Стратегия запуска.

Проверяется то, ради чего модуль существует: совет меняется вместе с объёмом,
а не выдаётся один и тот же всем; неготовый сайт и незаполненная экономика
останавливают план, а не сопровождают его оговоркой мелким шрифтом.
"""

from __future__ import annotations

from decimal import Decimal

from ads_os.services.economics import EconomicsMode
from ads_os.services.strategy import (
    CONVERSIONS_FOR_DECISION,
    BidStrategy,
    LaunchPlan,
    PlanStatus,
    StrategyInput,
    build_plan,
)


def plan_for(
    conversions: str | None,
    *,
    economics_mode: EconomicsMode = EconomicsMode.COMPLETE,
    monthly_budget: Decimal | None = Decimal("100000"),
    conversions_are_proxy: bool = False,
    conversions_are_forecast: bool = True,
    site_can_launch: bool | None = True,
) -> LaunchPlan:
    """План при заданном месячном объёме конверсий и в остальном полных данных."""
    return build_plan(
        StrategyInput(
            economics_mode=economics_mode,
            monthly_budget=monthly_budget,
            monthly_conversions=Decimal(conversions) if conversions is not None else None,
            conversions_are_proxy=conversions_are_proxy,
            conversions_are_forecast=conversions_are_forecast,
            site_can_launch=site_can_launch,
        )
    )


class TestВыборСтратегии:
    def test_большой_поток_даёт_автостратегию(self) -> None:
        # 87 в месяц ≈ 20 в неделю — вдвое выше порога обучения.
        plan = plan_for("87")

        assert plan.strategy is BidStrategy.MAX_CONVERSIONS
        assert plan.learning_ready is True
        assert plan.status is PlanStatus.READY

    def test_средний_поток_даёт_оплату_за_конверсии(self) -> None:
        """Меньше десяти в неделю — автостратегия по конверсиям неустойчива."""
        # 26 в месяц ≈ 6 в неделю.
        plan = plan_for("26")

        assert plan.strategy is BidStrategy.PAY_PER_CONVERSION
        assert plan.learning_ready is False
        # Запускаться можно, но это не «всё хорошо».
        assert plan.status is PlanStatus.RISKY

    def test_малый_поток_уводит_на_клики(self) -> None:
        # 8 в месяц ≈ 1,8 в неделю.
        plan = plan_for("8")

        assert plan.strategy is BidStrategy.MAX_CLICKS

    def test_у_совета_всегда_есть_обоснование(self) -> None:
        """Совет без объяснения нельзя ни принять осознанно, ни оспорить."""
        for conversions in ("87", "26", "8"):
            plan = plan_for(conversions)
            assert plan.strategy_reason
            assert len(plan.strategy_reason) > 40


class TestСрокТеста:
    def test_срок_считается_по_потоку(self) -> None:
        # 87 в месяц ≈ 20 в неделю → 30 конверсий набираются за 2 недели.
        plan = plan_for("87")

        assert plan.test_weeks == 2

    def test_бюджет_теста_пропорционален_сроку(self) -> None:
        plan = plan_for("87", monthly_budget=Decimal("43300"))

        # 43 300 / 4,33 = 10 000 в неделю, две недели → 20 000.
        assert plan.test_budget == Decimal("20000.00")

    def test_слишком_долгий_тест_называется_вслух(self) -> None:
        """Молчаливое «14 недель» выглядело бы как нормальный план."""
        plan = plan_for("4")

        assert plan.test_weeks is None
        assert any("недель" in note for note in plan.advice)

    def test_порог_выводов_не_занижен(self) -> None:
        """Тридцать конверсий — минимум, ниже которого это разброс, а не результат."""
        assert CONVERSIONS_FOR_DECISION >= 30


class TestБлокировки:
    def test_неготовый_сайт_останавливает_план(self) -> None:
        plan = plan_for("87", site_can_launch=False)

        assert plan.status is PlanStatus.BLOCKED
        assert plan.strategy is None
        assert any("сайт" in b.lower() for b in plan.blockers)

    def test_пустая_экономика_останавливает_план(self) -> None:
        plan = plan_for("87", economics_mode=EconomicsMode.INSUFFICIENT)

        assert plan.status is PlanStatus.BLOCKED

    def test_непроверенный_сайт_не_блокирует_но_упоминается(self) -> None:
        """Отсутствие аудита — не то же самое, что успешный аудит."""
        plan = plan_for("87", site_can_launch=None)

        assert plan.status is not PlanStatus.BLOCKED
        assert any("аудит" in note.lower() for note in plan.advice)

    def test_непроверенный_сайт_не_даёт_готовности(self) -> None:
        """Иначе экран говорит «можно запускать» и рядом — «сайт не смотрели».

        Две противоположные вещи в одном месте: человек поверит той, которая
        крупнее, то есть статусу.
        """
        plan = plan_for("87", site_can_launch=None)

        assert plan.status is PlanStatus.RISKY

    def test_без_расчёта_ёмкости_плана_нет(self) -> None:
        plan = plan_for(None)

        assert plan.status is PlanStatus.BLOCKED


class TestЧестностьЦифр:
    def test_приблизительная_ёмкость_снимает_статус_готовности(self) -> None:
        """Иначе допущение выглядело бы как факт о бизнесе клиента."""
        plan = plan_for("87", conversions_are_proxy=True)

        assert plan.status is PlanStatus.RISKY
        assert any("допущени" in note for note in plan.advice)

    def test_неполная_экономика_предлагает_дозаполнить(self) -> None:
        plan = plan_for("87", economics_mode=EconomicsMode.LIMITED)

        assert plan.status is not PlanStatus.BLOCKED
        assert any("маржинальность" in note for note in plan.advice)

    def test_малый_поток_советует_микроцели(self) -> None:
        plan = plan_for("8")

        assert any("микроцели" in note for note in plan.advice)


class TestОткудаЧисло:
    """Ёмкость бюджета и прогноз заявок — разные утверждения.

    Ёмкость отвечает «на сколько заявок хватит денег, если цена окажется
    целевой». Прогноз отвечает «сколько заявок будет». На старте реальная цена
    почти всегда выше целевой, и подавать ёмкость как ожидание значит
    планировать по лучшему из возможных исходов.
    """

    def test_ёмкость_не_даёт_статус_готовности(self) -> None:
        plan = plan_for("87", conversions_are_forecast=False)

        assert plan.status is PlanStatus.RISKY

    def test_ёмкость_объясняется_вслух(self) -> None:
        plan = plan_for("87", conversions_are_forecast=False)

        assert any("ёмкость бюджета" in note for note in plan.advice)
        assert any("цену клика" in note for note in plan.advice)

    def test_прогноз_даёт_статус_готовности(self) -> None:
        plan = plan_for("87", conversions_are_forecast=True)

        assert plan.status is PlanStatus.READY

    def test_прогноз_не_сопровождается_оговоркой_про_ёмкость(self) -> None:
        plan = plan_for("87", conversions_are_forecast=True)

        assert not any("ёмкость бюджета" in note for note in plan.advice)
