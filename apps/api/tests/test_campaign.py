"""Структура кампании и проверки перед выгрузкой.

Смысл проверок один: вопросы должны задаваться до Коммандера, а не после
запуска. Правка в Директе стоит дороже всего остального в этой работе.
"""

from __future__ import annotations

import pytest

from ads_os.services import campaign
from ads_os.services.campaign import Phrase, Severity


def row(
    phrase: str,
    group: str | None = "Окна",
    frequency: int | None = 100,
    manual: bool = False,
    irrelevant: bool = False,
) -> tuple[str, str | None, int | None, bool, bool]:
    return (phrase, group, frequency, manual, irrelevant)


def keys(checks: list[campaign.Check]) -> set[str]:
    return {check.key for check in checks}


class TestСтруктура:
    def test_фразы_собираются_по_группам(self) -> None:
        groups, orphans = campaign.structure(
            [row("окна тверь"), row("окна пвх"), row("балкон", group="Балконы")]
        )

        assert {g.name for g in groups} == {"Окна", "Балконы"}
        assert orphans == []

    def test_фразы_без_группы_отдельно(self) -> None:
        """В кампанию они не уедут, и увидеть это надо до выгрузки."""
        groups, orphans = campaign.structure([row("окна тверь"), row("сирота", group=None)])

        assert [item.phrase for item in orphans] == ["сирота"]
        assert len(groups) == 1

    def test_нецелевые_не_попадают_никуда(self) -> None:
        groups, orphans = campaign.structure([row("окна вакансии", irrelevant=True)])

        assert groups == []
        assert orphans == []

    def test_крупные_группы_идут_первыми(self) -> None:
        """С них начинают работу, и они же решают структуру кампании."""
        groups, _ = campaign.structure(
            [
                row("мало", group="Мелкая", frequency=10),
                row("много", group="Крупная", frequency=900),
            ]
        )

        assert [g.name for g in groups] == ["Крупная", "Мелкая"]

    def test_частые_фразы_внутри_группы_сверху(self) -> None:
        groups, _ = campaign.structure(
            [row("редкая", frequency=10), row("частая", frequency=900)]
        )

        assert [p.phrase for p in groups[0].phrases] == ["частая", "редкая"]

    def test_ручная_группа_помечена(self) -> None:
        groups, _ = campaign.structure([row("окна тверь", manual=True)])

        assert groups[0].manual is True


class TestПроверки:
    def test_без_групп_выгружать_нечего(self) -> None:
        found = campaign.checks([], [])

        assert keys(found) == {"no_groups"}
        assert campaign.can_export(found) is False

    def test_фразы_без_группы_блокируют(self) -> None:
        """Молча выгрузить кампанию без части фраз — значит отдать неполную
        работу и не сказать об этом."""
        groups, orphans = campaign.structure(
            [row("окна тверь"), row("окна пвх"), row("сирота", group=None)]
        )

        found = campaign.checks(groups, orphans, minus_words=3)

        assert "ungrouped" in keys(found)
        assert campaign.can_export(found) is False

    def test_группа_из_одной_фразы_это_предупреждение(self) -> None:
        """Автостратегии нужен объём: по одной фразе статистика не набирается."""
        groups, orphans = campaign.structure([row("окна тверь")])

        found = campaign.checks(groups, orphans, minus_words=3)

        assert "thin_groups" in keys(found)
        # Предупреждение, а не запрет: специалист может знать про свой случай
        # больше, чем проверка.
        assert campaign.can_export(found) is True

    def test_слишком_крупная_группа_замечается(self) -> None:
        groups, orphans = campaign.structure(
            [row(f"фраза {i}") for i in range(campaign.MAX_PHRASES_IN_GROUP + 5)]
        )

        found = campaign.checks(groups, orphans, minus_words=3)

        assert "fat_groups" in keys(found)

    def test_фразы_без_частотности_замечаются(self) -> None:
        """По ним нельзя оценить охват и спланировать бюджет."""
        groups, orphans = campaign.structure(
            [row("окна тверь"), row("окна пвх", frequency=None)]
        )

        found = campaign.checks(groups, orphans, minus_words=3)

        assert "no_frequency" in keys(found)

    def test_кампания_без_минус_слов_замечается(self) -> None:
        groups, orphans = campaign.structure([row("окна тверь"), row("окна пвх")])

        found = campaign.checks(groups, orphans, minus_words=0)

        assert "no_minus_words" in keys(found)

    def test_проект_без_сайта_блокирует(self) -> None:
        """Без адреса ссылки объявлений будут пустыми."""
        groups, orphans = campaign.structure([row("окна тверь"), row("окна пвх")])

        found = campaign.checks(groups, orphans, minus_words=3, has_landing=False)

        assert "no_landing" in keys(found)
        assert campaign.can_export(found) is False

    def test_замечания_к_объявлениям_не_блокируют(self) -> None:
        """Они попадут в файл отдельным столбцом: молча выбросить группу с
        длинным заголовком значило бы отдать неполную кампанию."""
        groups, orphans = campaign.structure([row("окна тверь"), row("окна пвх")])

        found = campaign.checks(
            groups, orphans, minus_words=3, ad_warnings=("Окна: заголовок длиннее 56",)
        )

        assert "ad_warnings" in keys(found)
        assert campaign.can_export(found) is True

    def test_у_каждого_замечания_есть_действие(self) -> None:
        """Замечание без действия — это упрёк, а не помощь."""
        groups, orphans = campaign.structure(
            [row("окна тверь"), row("сирота", group=None), row("без числа", frequency=None)]
        )

        found = campaign.checks(groups, orphans, minus_words=0, has_landing=False)

        assert found
        assert all(check.action for check in found)

    def test_примеров_не_больше_предела(self) -> None:
        """Замечание должно читаться за секунду, а не разбираться."""
        groups, orphans = campaign.structure(
            [row(f"сирота {i}", group=None) for i in range(50)]
            + [row("окна тверь"), row("окна пвх")]
        )

        found = campaign.checks(groups, orphans, minus_words=3)
        ungrouped = next(check for check in found if check.key == "ungrouped")

        assert len(ungrouped.examples) <= campaign.MAX_EXAMPLES
        assert ungrouped.count == 50


@pytest.mark.parametrize("severity", list(Severity))
def test_каждая_степень_названа(severity: Severity) -> None:
    assert severity.value.isascii()


def test_частотность_группы_складывается() -> None:
    group = campaign.Group(
        name="Окна", phrases=(Phrase("а", 100), Phrase("б", 50), Phrase("в", None))
    )

    assert group.total_frequency == 150
