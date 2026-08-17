"""Бриф → маски для Вордстата.

Проверяется главным образом честность: маски должны быть такими, чтобы их
можно было вставить в Вордстат как есть и получить осмысленный список, — и не
должно возникать впечатления, будто система собирает запросы сама.
"""

from __future__ import annotations

from ads_os.services.wordstat import (
    MAX_MINUS,
    MAX_TERMS,
    WHY_MANUAL,
    Brief,
    masks,
    minus_words,
    steps,
    terms,
)

OKNA = Brief(
    sells="пластиковые окна, остекление балконов",
    synonyms="окна пвх",
    excludes="ремонт окон, москитные сетки",
    cities="тверь",
)


class TestРазборБрифа:
    def test_темы_собираются_из_двух_полей(self) -> None:
        assert terms(OKNA) == ("пластиковые окна", "остекление балконов", "окна пвх")

    def test_повторы_схлопываются(self) -> None:
        brief = Brief(sells="окна, Окна", synonyms="окна")

        assert terms(brief) == ("окна",)

    def test_разделители_разные(self) -> None:
        brief = Brief(sells="окна; двери\nбалконы")

        assert terms(brief) == ("окна", "двери", "балконы")

    def test_число_тем_ограничено(self) -> None:
        """Каждая маска — это отдельный заход в Вордстат руками. Список из
        сорока масок не собирает никто."""
        brief = Brief(sells=", ".join(f"тема{i}" for i in range(20)))

        assert len(terms(brief)) == MAX_TERMS

    def test_пустой_бриф_видно(self) -> None:
        assert Brief().is_filled is False
        assert OKNA.is_filled is True


class TestМинусСлова:
    def test_берутся_из_того_чего_не_делаем(self) -> None:
        assert "ремонт" in minus_words(OKNA)
        assert "москитные" in minus_words(OKNA)

    def test_нишевые_добавляются(self) -> None:
        assert "регулировка" in minus_words(Brief(sells="окна"), niche_words=("регулировка",))

    def test_короткие_слова_не_берутся(self) -> None:
        """«Из», «на», «до» в минусах Вордстата только мешают."""
        assert minus_words(Brief(excludes="из на до")) == ()

    def test_число_минусов_ограничено(self) -> None:
        brief = Brief(excludes=", ".join(f"слово{i}" for i in range(20)))

        assert len(minus_words(brief)) == MAX_MINUS


class TestМаски:
    def test_на_каждую_тему_есть_широкая_маска(self) -> None:
        queries = [mask.query for mask in masks(OKNA)]

        assert any(query.startswith("пластиковые окна ") for query in queries)
        assert any(query.startswith("остекление балконов ") for query in queries)

    def test_минусы_попадают_в_строку(self) -> None:
        first = masks(OKNA)[0].query

        assert "-ремонт" in first
        assert "-москитные" in first

    def test_коммерческие_уточнения_по_главной_теме(self) -> None:
        queries = [mask.query for mask in masks(OKNA)]

        assert any(query.startswith("купить пластиковые окна") for query in queries)
        assert any(query.startswith("пластиковые окна цена") for query in queries)

    def test_город_отдельной_маской(self) -> None:
        """Регион в Вордстате и город внутри запроса — разные вещи."""
        assert "пластиковые окна тверь" in [mask.query for mask in masks(OKNA)]

    def test_город_берётся_из_региона_если_в_брифе_его_нет(self) -> None:
        brief = Brief(sells="окна")

        assert "окна тверь" in [mask.query for mask in masks(brief, region="тверь")]

    def test_без_брифа_масок_нет(self) -> None:
        """Придумывать маски за человека не из чего, а показать пустой список
        честнее, чем показать список ни о чём."""
        assert masks(Brief()) == ()

    def test_у_каждой_маски_есть_объяснение(self) -> None:
        for mask in masks(OKNA):
            assert len(mask.purpose) > 20, mask.query


class TestИнструкция:
    def test_регион_называется_прямо(self) -> None:
        assert any("Тверь" in step for step in steps("Тверь"))

    def test_шаги_не_пустые(self) -> None:
        assert len(steps()) >= 4
        for step in steps():
            assert len(step) > 20

    def test_сказано_почему_не_автоматически(self) -> None:
        """Иначе ручной шаг выглядит недоделанной кнопкой."""
        assert "Вордстат" in WHY_MANUAL
        assert len(WHY_MANUAL) > 100
