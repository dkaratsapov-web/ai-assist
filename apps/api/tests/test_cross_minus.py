"""Кросс-минусовка.

Проверяется то, ради чего она нужна: общая фраза перестаёт перехватывать
запросы уточнённой, совет можно проверить, а повторный запуск даёт тот же
результат.
"""

from __future__ import annotations

from ads_os.services.cross_minus import cross_minus


def minus_for(result, phrase: str) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
    item = next((i for i in result.items if i.phrase == phrase), None)
    return item.minus_words if item else ()


class TestПоглощение:
    def test_общая_фраза_получает_минус_слова_уточнённой(self) -> None:
        result = cross_minus(["пластиковые окна", "пластиковые окна с установкой"])

        assert minus_for(result, "пластиковые окна") == ("установкой",)

    def test_уточнённая_фраза_ничего_не_получает(self) -> None:
        """Она и так ловит только свои запросы — минусовать ей нечего."""
        result = cross_minus(["пластиковые окна", "пластиковые окна с установкой"])

        assert minus_for(result, "пластиковые окна с установкой") == ()

    def test_минус_слова_собираются_со_всех_уточнений(self) -> None:
        result = cross_minus(
            [
                "пластиковые окна",
                "пластиковые окна с установкой",
                "пластиковые окна недорого",
                "купить пластиковые окна в твери",
            ]
        )

        assert set(minus_for(result, "пластиковые окна")) >= {
            "установкой",
            "недорого",
            "купить",
            "твери",
        }

    def test_непересекающиеся_фразы_не_трогаются(self) -> None:
        result = cross_minus(["пластиковые окна", "натяжные потолки"])

        assert result.items == ()

    def test_частичное_пересечение_не_считается_поглощением(self) -> None:
        """«Окна купить» и «двери купить» пересекаются по слову, но ни одна не
        содержит другую целиком — перехвата нет."""
        result = cross_minus(["окна купить", "двери купить"])

        assert result.items == ()

    def test_цепочка_разбирается_вся(self) -> None:
        result = cross_minus(["окна", "окна пластиковые", "окна пластиковые недорого"])

        assert set(minus_for(result, "окна")) == {"пластиковые", "недорого"}
        assert minus_for(result, "окна пластиковые") == ("недорого",)


class TestСловоформы:
    def test_окна_и_окон_считаются_одним_словом(self) -> None:
        """Сравнение по буквам пропустило бы половину пересечений."""
        result = cross_minus(["установка окон", "установка окон пвх"])

        assert minus_for(result, "установка окон") == ("пвх",)

    def test_минус_слово_отдаётся_словом_а_не_основой(self) -> None:
        """«Установк» Директ не примет."""
        result = cross_minus(["ремонт окон", "ремонт окон с установкой"])

        assert minus_for(result, "ремонт окон") == ("установкой",)


class TestСлужебныеСлова:
    def test_предлоги_не_создают_различий(self) -> None:
        """Для Директа «окна в дом» и «окна для дома» неразличимы."""
        result = cross_minus(["окна в дом", "окна для дома"])

        assert result.items == ()
        assert len(result.duplicates) == 1

    def test_предлог_не_попадает_в_минус_слова(self) -> None:
        result = cross_minus(["купить окна", "купить окна в твери"])

        assert minus_for(result, "купить окна") == ("твери",)


class TestДубликаты:
    def test_перестановка_слов_это_одна_фраза(self) -> None:
        """Директ не различает порядок слов: держать обе значит соревноваться
        с самим собой на аукционе."""
        result = cross_minus(["купить пластиковые окна", "пластиковые окна купить"])

        assert len(result.duplicates) == 1
        assert len(result.duplicates[0].phrases) == 2

    def test_дубликаты_не_считаются_поглощением(self) -> None:
        result = cross_minus(["купить окна", "окна купить"])

        assert result.items == ()

    def test_разные_фразы_не_дубликаты(self) -> None:
        result = cross_minus(["купить окна", "купить двери"])

        assert result.duplicates == ()


class TestОбъяснимость:
    def test_видно_чьи_запросы_перехватываются(self) -> None:
        """Иначе человек видит «минусуйте установку» и не понимает, откуда это
        взялось и что сломается, если послушаться."""
        result = cross_minus(["окна", "окна с установкой"])

        assert result.items[0].shadows == ("окна с установкой",)

    def test_порядок_повторяем(self) -> None:
        """Иначе выгрузка каждый раз выглядит другой, и сравнить две версии
        кампании нельзя."""
        phrases = [
            "окна",
            "окна пластиковые",
            "окна деревянные",
            "окна пластиковые недорого",
            "двери",
            "двери входные",
        ]

        first = cross_minus(phrases)
        second = cross_minus(list(reversed(phrases)))

        assert [i.phrase for i in first.items] == [i.phrase for i in second.items]
        assert [i.minus_words for i in first.items] == [i.minus_words for i in second.items]

    def test_сначала_самые_проблемные(self) -> None:
        """Фраза, перехватывающая пять чужих запросов, важнее той, что
        перехватывает один."""
        result = cross_minus(
            ["окна", "окна пвх", "окна недорого", "окна в твери", "двери", "двери входные"]
        )

        assert result.items[0].phrase == "окна"


class TestУстойчивость:
    def test_пустой_список(self) -> None:
        result = cross_minus([])

        assert result.items == ()
        assert result.analyzed == 0

    def test_повторы_в_списке_не_ломают(self) -> None:
        result = cross_minus(["окна", "окна", "окна с установкой"])

        assert result.analyzed == 2
        assert minus_for(result, "окна") == ("установкой",)

    def test_пробелы_и_пустые_строки_отбрасываются(self) -> None:
        result = cross_minus(["  окна  ", "", "   ", "окна пвх"])

        assert result.analyzed == 2

    def test_фраза_из_одних_предлогов_не_роняет(self) -> None:
        result = cross_minus(["в для на", "окна"])

        assert result.analyzed == 2

    def test_большой_список_обрабатывается(self) -> None:
        """Перебор пар здесь дал бы полмиллиона сравнений."""
        phrases = ["окна пвх"] + [f"окна пвх вариант{i}" for i in range(1000)]

        result = cross_minus(phrases)

        assert len(minus_for(result, "окна пвх")) == 1000
