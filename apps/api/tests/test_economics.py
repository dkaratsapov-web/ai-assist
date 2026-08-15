"""Тесты Economics Engine.

Проверяется не только арифметика, но и главное свойство модуля: система не
подставляет правдоподобные числа там, где данных нет.
"""

from decimal import Decimal

import pytest

from ads_os.services.economics import (
    Availability,
    EconomicsInput,
    EconomicsMode,
    evaluate,
)

D = Decimal


def full_input(**overrides: object) -> EconomicsInput:
    """Полностью заполненная экономика ремонта техники.

    Средний чек 6000 ₽, маржа 45%, из лида в продажу превращается каждый пятый.
    Числа подобраны так, чтобы результаты считались в уме и проверялись глазами.
    """
    data = {
        "monthly_budget": D("150000"),
        "average_order_value": D("6000"),
        "main_conversion": "lead",
        "margin_percent": D("45"),
        "lead_to_sale_rate": D("0.2"),
    }
    data.update(overrides)
    return EconomicsInput(**data)  # type: ignore[arg-type]


class TestФормулы:
    def test_валовая_прибыль_со_сделки(self) -> None:
        s = evaluate(full_input())
        # 6000 × 45% = 2700
        assert s.gross_profit_per_sale.value == D("2700.00")

    def test_безубыточный_cac_равен_валовой_прибыли(self) -> None:
        s = evaluate(full_input())
        # Потратив на привлечение ровно 2700, выходим в ноль.
        assert s.break_even_cac.value == D("2700.00")

    def test_безубыточный_cpl_учитывает_конверсию(self) -> None:
        s = evaluate(full_input())
        # 2700 × 0.2 = 540
        assert s.break_even_cpl.value == D("540.00")

    def test_безубыточный_roas(self) -> None:
        s = evaluate(full_input())
        # При марже 45% выручка должна превышать расход в 100/45 ≈ 2.2222 раза.
        assert s.break_even_roas.value == D("2.2222")

    def test_целевой_cac_из_заданной_доли(self) -> None:
        s = evaluate(full_input(target_marketing_share=D("0.4")))
        # 2700 × 0.4 = 1080
        assert s.target_cac.value == D("1080.00")
        assert s.target_cac.availability is Availability.AVAILABLE

    def test_целевой_cpl_выводится_из_целевого_cac(self) -> None:
        s = evaluate(full_input(target_marketing_share=D("0.4")))
        # 1080 × 0.2 = 216
        assert s.target_cpl.value == D("216.00")

    def test_ёмкость_бюджета_и_прогноз(self) -> None:
        s = evaluate(full_input(target_cpl=D("500")))
        # 150000 / 500 = 300 лидов, из них 60 продаж, выручка 360 000
        assert s.monthly_leads_capacity.value == D("300.0000")
        assert s.monthly_sales_capacity.value == D("60.0000")
        assert s.projected_revenue.value == D("360000.00")
        # 360000 × 45% − 150000 = 12 000
        assert s.projected_gross_profit.value == D("12000.00")

    def test_явно_заданный_целевой_cac_побеждает_расчётный(self) -> None:
        s = evaluate(full_input(target_cac=D("900")))
        assert s.target_cac.value == D("900.00")
        assert s.target_cac.availability is Availability.AVAILABLE


class TestРежимыПолноты:
    def test_полная_экономика_разрешает_оптимизацию_по_продажам(self) -> None:
        s = evaluate(full_input())
        assert s.mode is EconomicsMode.COMPLETE
        assert s.can_optimize_by_sales is True
        assert s.cta is None

    def test_без_обязательных_полей_ничего_не_считается(self) -> None:
        s = evaluate(EconomicsInput(monthly_budget=D("150000")))
        assert s.mode is EconomicsMode.INSUFFICIENT
        assert s.can_optimize_by_sales is False
        assert "средний чек или ожидаемая ценность" in s.missing_required
        assert "основная конверсия" in s.missing_required
        assert s.cta is not None

    def test_ожидаемая_ценность_заменяет_средний_чек(self) -> None:
        s = evaluate(
            EconomicsInput(
                monthly_budget=D("150000"),
                expected_value=D("6000"),
                main_conversion="lead",
                margin_percent=D("45"),
                lead_to_sale_rate=D("0.2"),
            )
        )
        assert s.mode is EconomicsMode.COMPLETE
        assert s.gross_profit_per_sale.value == D("2700.00")

    def test_проект_не_блокируется_без_рекомендованных_полей(self) -> None:
        """Ключевое требование v0.4 §5: работа продолжается, но честно."""
        s = evaluate(
            EconomicsInput(
                monthly_budget=D("150000"),
                average_order_value=D("6000"),
                main_conversion="lead",
            )
        )
        assert s.mode is EconomicsMode.LIMITED
        assert s.can_optimize_by_sales is False
        assert s.cta == "Заполните экономику, чтобы включить оптимизацию по продажам"


class TestЧестностьЗначений:
    def test_без_маржи_cac_не_появляется_ни_в_каком_виде(self) -> None:
        """Правдоподобное число здесь опаснее пробела: на него будут опираться."""
        s = evaluate(
            EconomicsInput(
                monthly_budget=D("150000"),
                average_order_value=D("6000"),
                main_conversion="lead",
                lead_to_sale_rate=D("0.2"),
            )
        )
        for metric in (s.break_even_cac, s.target_cac, s.gross_profit_per_sale, s.target_roas):
            assert metric.availability is Availability.UNAVAILABLE
            assert metric.value is None
            assert metric.reason == "укажите маржинальность"

    def test_без_конверсии_недоступны_метрики_уровня_лида(self) -> None:
        s = evaluate(
            EconomicsInput(
                monthly_budget=D("150000"),
                average_order_value=D("6000"),
                main_conversion="lead",
                margin_percent=D("45"),
            )
        )
        # CAC посчитать можно — он не зависит от конверсии в продажу.
        assert s.break_even_cac.value == D("2700.00")
        # А CPL и ёмкость бюджета — нельзя.
        assert s.break_even_cpl.availability is Availability.UNAVAILABLE
        assert s.monthly_sales_capacity.availability is Availability.UNAVAILABLE

    def test_расчётный_целевой_cac_помечается_ориентировочным(self) -> None:
        """Доля прибыли на привлечение — наше допущение, а не факт о бизнесе."""
        s = evaluate(full_input())
        assert s.target_cac.availability is Availability.PROXY
        assert s.target_cac.reason is not None
        assert "допущение" in s.target_cac.reason

    def test_ориентировочность_наследуется_производными(self) -> None:
        s = evaluate(full_input())
        for metric in (s.target_cpl, s.target_roas, s.monthly_leads_capacity, s.projected_revenue):
            assert metric.availability is Availability.PROXY


class TestКраевыеСлучаи:
    def test_нулевая_маржа_не_даёт_окупаемости(self) -> None:
        s = evaluate(full_input(margin_percent=D("0")))
        assert s.gross_profit_per_sale.value == D("0.00")
        assert s.break_even_roas.availability is Availability.UNAVAILABLE

    def test_конверсия_сто_процентов(self) -> None:
        s = evaluate(full_input(lead_to_sale_rate=D("1")))
        # Каждый лид становится продажей: CPL совпадает с CAC.
        assert s.break_even_cpl.value == s.break_even_cac.value

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("monthly_budget", D("-1")),
            ("average_order_value", D("0")),
            ("target_cac", D("-100")),
        ],
    )
    def test_неположительные_суммы_отклоняются(self, field: str, value: Decimal) -> None:
        with pytest.raises(ValueError, match="больше нуля"):
            full_input(**{field: value})

    @pytest.mark.parametrize("value", [D("-1"), D("101")])
    def test_маржа_вне_диапазона_отклоняется(self, value: Decimal) -> None:
        with pytest.raises(ValueError, match="от 0 до 100"):
            full_input(margin_percent=value)

    @pytest.mark.parametrize("value", [D("0"), D("1.5")])
    def test_конверсия_вне_диапазона_отклоняется(self, value: Decimal) -> None:
        with pytest.raises(ValueError, match="от 0 до 1"):
            full_input(lead_to_sale_rate=value)


class TestПрогнозЗаявок:
    """Бюджет → клики → заявки. Не то же самое, что ёмкость бюджета."""

    def test_прогноз_считается_по_цене_клика_и_конверсии(self) -> None:
        result = evaluate(
            EconomicsInput(
                monthly_budget=Decimal("150000"),
                average_order_value=Decimal("38000"),
                main_conversion="lead",
                expected_cpc=Decimal("50"),
                site_conversion_rate=Decimal("0.03"),
            )
        )

        # 150 000 / 50 = 3000 кликов, 3 % от них — 90 заявок.
        assert result.expected_monthly_clicks.value == Decimal("3000.0000")
        assert result.expected_monthly_leads.value == Decimal("90.0000")

    def test_прогноз_расходится_с_ёмкостью_бюджета(self) -> None:
        """Ради этого расхождения всё и делалось: числа разные, и это видно."""
        result = evaluate(
            EconomicsInput(
                monthly_budget=Decimal("150000"),
                average_order_value=Decimal("38000"),
                main_conversion="lead",
                margin_percent=Decimal("35"),
                lead_to_sale_rate=Decimal("0.22"),
                target_cpl=Decimal("900"),
                expected_cpc=Decimal("45"),
                site_conversion_rate=Decimal("0.03"),
            )
        )

        assert result.monthly_leads_capacity.value is not None
        assert result.expected_monthly_leads.value is not None
        assert result.expected_monthly_leads.value < result.monthly_leads_capacity.value

    def test_без_цены_клика_прогноза_нет(self) -> None:
        """Отсутствие прогноза честнее, чем прогноз из воздуха."""
        result = evaluate(
            EconomicsInput(
                monthly_budget=Decimal("150000"),
                average_order_value=Decimal("38000"),
                main_conversion="lead",
                site_conversion_rate=Decimal("0.03"),
            )
        )

        assert result.expected_monthly_leads.value is None
        assert result.expected_monthly_leads.reason is not None
        assert "цену клика" in result.expected_monthly_leads.reason

    def test_без_конверсии_сайта_прогноза_нет(self) -> None:
        result = evaluate(
            EconomicsInput(
                monthly_budget=Decimal("150000"),
                average_order_value=Decimal("38000"),
                main_conversion="lead",
                expected_cpc=Decimal("50"),
            )
        )

        assert result.expected_monthly_leads.value is None
        assert result.expected_monthly_clicks.value is not None

    def test_недостающие_поля_прогноза_перечислены(self) -> None:
        result = evaluate(
            EconomicsInput(
                monthly_budget=Decimal("150000"),
                average_order_value=Decimal("38000"),
                main_conversion="lead",
            )
        )

        assert "ожидаемая цена клика" in result.missing_forecast
        assert "конверсия посадочной страницы" in result.missing_forecast

    def test_неверная_конверсия_отклоняется(self) -> None:
        with pytest.raises(ValueError, match="site_conversion_rate"):
            EconomicsInput(monthly_budget=Decimal("1000"), site_conversion_rate=Decimal("1.5"))
