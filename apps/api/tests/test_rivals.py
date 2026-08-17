"""Подсказка конкурентов.

Проверяется главным образом сдержанность. Подсказать сайт, который конкурентом
не является, хуже, чем не подсказать ничего: специалист добавит его, система
разберёт чужую страницу, сравнение съедет — и всё это молча.
"""

from __future__ import annotations

from ads_os.services.rivals import (
    MAX_QUERIES,
    SEARCH_HINT,
    WHY_NOT_AUTOMATIC,
    KnownSite,
    Source,
    domain,
    search_queries,
    suggest,
)

TVER = KnownSite(
    url="https://okna-tver.ru/",
    title="Окна Твери",
    project_name="Окна Тверь",
    niche="plastic_windows",
    region="Тверь",
)
MOSCOW = KnownSite(
    url="https://okna-msk.ru/",
    title="Окна Москвы",
    project_name="Окна Москва",
    niche="plastic_windows",
    region="Москва",
)
OTHER_NICHE = KnownSite(
    url="https://potolki-tver.ru/",
    title="Потолки",
    project_name="Потолки Тверь",
    niche="stretch_ceilings",
    region="Тверь",
)


def keys(**kwargs: object) -> set[str]:
    return {item.url for item in suggest(**kwargs)}  # type: ignore[arg-type]


class TestПодсказкиИзИстории:
    def test_та_же_ниша_и_город_предлагается(self) -> None:
        result = suggest(
            (TVER,), niche="plastic_windows", region="Тверь", exclude=frozenset()
        )

        assert result[0].url == "https://okna-tver.ru/"
        assert "Окна Тверь" in result[0].reason

    def test_другая_ниша_не_предлагается(self) -> None:
        """Иначе подсказка вырождается в список всех сайтов агентства."""
        assert (
            suggest((OTHER_NICHE,), niche="plastic_windows", region="Тверь", exclude=frozenset())
            == ()
        )

    def test_другой_город_не_предлагается(self) -> None:
        """Компании из разных городов аукцион не делят."""
        assert (
            suggest((MOSCOW,), niche="plastic_windows", region="Тверь", exclude=frozenset()) == ()
        )

    def test_без_региона_подсказка_остаётся(self) -> None:
        """Сравнивать нечего — значит, решает человек, а не мы за него."""
        result = suggest((MOSCOW,), niche="plastic_windows", region=None, exclude=frozenset())

        assert len(result) == 1

    def test_без_ниши_подсказок_нет(self) -> None:
        assert suggest((TVER,), niche=None, region="Тверь", exclude=frozenset()) == ()

    def test_уже_добавленный_не_предлагается(self) -> None:
        result = suggest(
            (TVER,),
            niche="plastic_windows",
            region="Тверь",
            exclude=frozenset({"okna-tver.ru"}),
        )

        assert result == ()

    def test_повторы_по_домену_схлопываются(self) -> None:
        """Один сайт, добавленный в двух проектах, — это один конкурент."""
        twin = KnownSite(
            url="https://www.okna-tver.ru/catalog",
            title="Окна Твери",
            project_name="Другой проект",
            niche="plastic_windows",
            region="Тверь",
        )

        result = suggest(
            (TVER, twin), niche="plastic_windows", region="Тверь", exclude=frozenset()
        )

        assert len(result) == 1

    def test_свой_проект_помечается_отдельно(self) -> None:
        """Два клиента одной ниши в одном городе делят аукцион между собой.
        Промолчать об этом нельзя, но и выдать за чужой сайт тоже."""
        own = KnownSite(
            url="https://client2.ru/",
            title="Клиент 2",
            project_name="Клиент 2",
            niche="plastic_windows",
            region="Тверь",
            is_own_project=True,
        )

        result = suggest((own,), niche="plastic_windows", region="Тверь", exclude=frozenset())

        assert result[0].source is Source.OWN_PROJECT
        assert "вашего проекта" in result[0].reason

    def test_у_каждой_подсказки_есть_объяснение(self) -> None:
        for item in suggest(
            (TVER,), niche="plastic_windows", region="Тверь", exclude=frozenset()
        ):
            assert len(item.reason) > 30


class TestДомен:
    def test_схема_и_www_отбрасываются(self) -> None:
        assert domain("https://www.okna.ru/catalog?a=1") == "okna.ru"

    def test_пустой_адрес_не_ломает(self) -> None:
        assert domain("") == ""


class TestПоисковыеЗапросы:
    def test_город_попадает_в_запрос(self) -> None:
        """Местная услуга и та же услуга по стране — две разные выдачи."""
        queries = [item.query for item in search_queries(("пластиковые окна",), "Тверь")]

        assert "пластиковые окна Тверь" in queries

    def test_есть_ссылка_на_выдачу(self) -> None:
        item = search_queries(("окна",), "Тверь")[0]

        assert item.url.startswith("https://yandex.ru/search/?text=")

    def test_без_региона_запрос_остаётся_осмысленным(self) -> None:
        assert search_queries(("окна",), None)[0].query == "окна"

    def test_число_запросов_ограничено(self) -> None:
        terms = tuple(f"тема{i}" for i in range(10))

        assert len(search_queries(terms, "Тверь")) == MAX_QUERIES

    def test_без_тем_запросов_нет(self) -> None:
        assert search_queries((), "Тверь") == ()


class TestОбъяснения:
    def test_сказано_что_брать_из_выдачи(self) -> None:
        """Иначе человек берёт первые сайты подряд, а нужны рекламные места."""
        assert "Реклама" in SEARCH_HINT

    def test_сказано_почему_не_автоматически(self) -> None:
        assert "Директ" in WHY_NOT_AUTOMATIC
        assert len(WHY_NOT_AUTOMATIC) > 100
