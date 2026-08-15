"""Семантика: разбор списка, отсев нецелевых, группировка.

Проверяется то, что стоит денег. Пропущенное нецелевое слово — это оплаченные
клики без единой заявки. Ошибочно отсеянная коммерческая фраза — это заявки,
которых не будет, и заметить их отсутствие нельзя в принципе.
"""

from __future__ import annotations

from typing import ClassVar

from ads_os.services.morphology import fold_beglye, stem
from ads_os.services.semantics import (
    Intent,
    LandingPage,
    ParsedKeyword,
    classify,
    cluster,
    match_landing,
    parse_list,
    suggest_minus_words,
)


class TestОснова:
    def test_падежи_сводятся_к_одной_основе(self) -> None:
        formy = ("ремонт", "ремонта", "ремонту", "ремонтом", "ремонты", "ремонтов")

        assert len({stem(word) for word in formy}) == 1

    def test_прилагательные_сводятся_к_одной_основе(self) -> None:
        formy = ("пластиковый", "пластиковая", "пластиковые", "пластиковых", "пластиковыми")

        assert len({stem(word) for word in formy}) == 1

    def test_короткие_слова_не_режутся(self) -> None:
        """Иначе «дом» превратится в «д» и склеит несвязанные фразы."""
        assert stem("дом") == "дом"
        assert stem("пол") == "пол"

    def test_латиница_и_цифры_остаются_как_есть(self) -> None:
        assert stem("iphone") == "iphone"
        assert stem("14") == "14"

    def test_беглая_гласная_сама_по_себе_не_обрабатывается(self) -> None:
        """Ограничение алгоритма, зафиксированное намеренно.

        «окно» и «окон» дают разные основы: беглую гласную Портер не знает.
        Само по себе это ограничение остаётся — снимается оно уже при
        группировке, по совпадению форм внутри списка.
        """
        assert stem("окно") != stem("окон")

    def test_формы_с_беглой_гласной_сводятся_по_списку(self) -> None:
        """Словаря исключений нет: свидетельство берётся из самого списка."""
        folded = fold_beglye([stem(w) for w in ("окна", "окон", "потолка", "потолок")])

        assert folded[stem("окон")] == folded[stem("окна")]
        assert folded[stem("потолок")] == folded[stem("потолка")]

    def test_одинокая_основа_не_трогается(self) -> None:
        """Иначе «ремонт» превратился бы в «ремнт» без всякого основания."""
        folded = fold_beglye([stem(w) for w in ("ремонт", "ремонта")])

        assert stem("ремонт") not in folded


class TestРазборСписка:
    def test_частотность_отделяется_от_фразы(self) -> None:
        parsed = parse_list("ремонт окон тверь\t1200")

        assert parsed[0].phrase == "ремонт окон тверь"
        assert parsed[0].frequency == 1200

    def test_понимает_разные_разделители(self) -> None:
        """Формат у пользователя не спрашиваем: он не должен в этом разбираться."""
        for line in ("окна пвх\t900", "окна пвх;900", "окна пвх 900", "окна пвх,900"):
            parsed = parse_list(line)
            assert parsed[0].phrase == "окна пвх", line
            assert parsed[0].frequency == 900, line

    def test_фраза_без_частотности_принимается(self) -> None:
        parsed = parse_list("остекление балкона")

        assert parsed[0].phrase == "остекление балкона"
        assert parsed[0].frequency is None

    def test_цифры_внутри_фразы_не_считаются_частотностью(self) -> None:
        parsed = parse_list("ремонт iphone 14")

        # Число в конце здесь — часть названия модели. Разобрать это без
        # ошибок нельзя в принципе, и предпочтение отдано сохранению фразы.
        assert "iphone" in parsed[0].phrase

    def test_повторы_схлопываются(self) -> None:
        parsed = parse_list("окна пвх\t100\nокна пвх\t900\nОкна ПВХ")

        assert len(parsed) == 1
        # Остаётся наибольшая известная частотность, а не последняя.
        assert parsed[0].frequency == 900

    def test_пустые_строки_и_мусор_пропускаются(self) -> None:
        parsed = parse_list("окна пвх\n\n   \n1200\n---")

        assert [p.phrase for p in parsed] == ["окна пвх"]


class TestОтборФраз:
    def test_коммерческий_запрос(self) -> None:
        assert classify("купить пластиковые окна").intent is Intent.COMMERCIAL

    def test_фраза_без_признаков_считается_целевой(self) -> None:
        """Ядро семантики — фразы без слова «купить». Отсекать их нельзя."""
        assert classify("пластиковые окна тверь").intent is Intent.COMMERCIAL

    def test_информационный_запрос(self) -> None:
        assert classify("как выбрать пластиковые окна").intent is Intent.INFORMATIONAL

    def test_нецелевой_запрос(self) -> None:
        assert classify("пластиковые окна вакансии").intent is Intent.IRRELEVANT

    def test_нецелевое_сильнее_коммерческого(self) -> None:
        """«Купить диплом» — не заявка, сколько бы в ней ни было слов о покупке."""
        assert classify("купить диплом недорого").intent is Intent.IRRELEVANT

    def test_коммерческое_сильнее_информационного(self) -> None:
        """«Какая цена» — это всё-таки покупка."""
        assert classify("какая цена на пластиковые окна").intent is Intent.COMMERCIAL

    def test_составной_признак_ловится(self) -> None:
        """По одному слову «своими руками» не поймать."""
        assert classify("установка окон своими руками").intent is Intent.IRRELEVANT

    def test_склонённое_нецелевое_слово_ловится(self) -> None:
        assert classify("окна пвх вакансия монтажника").intent is Intent.IRRELEVANT

    def test_решение_объясняется_словом(self) -> None:
        """Без этого непонятно, что править, чтобы решение изменилось."""
        result = classify("окна пвх бесплатно")

        assert result.trigger == "бесплатно"

    def test_свой_список_расширяет_отсев(self) -> None:
        """Словарь не знает ниши. Нишевые слова добавляет специалист."""
        assert classify("окна пвх рассрочка").intent is Intent.COMMERCIAL

        result = classify("окна пвх рассрочка", extra_irrelevant=frozenset({"рассрочка"}))

        assert result.intent is Intent.IRRELEVANT


class TestГруппировка:
    def test_падежи_попадают_в_одну_группу(self) -> None:
        groups = cluster(
            [
                ParsedKeyword("ремонт окон", 500),
                ParsedKeyword("ремонта окна", 300),
                ParsedKeyword("ремонту окон", 100),
            ]
        )

        assert len(groups) == 1
        assert len(groups[0].phrases) == 3

    def test_коммерческие_слова_не_разводят_группы(self) -> None:
        """«Купить окна» и «окна цена» ведут на одну страницу."""
        groups = cluster(
            [
                ParsedKeyword("купить пластиковые окна", 800),
                ParsedKeyword("пластиковые окна цена", 600),
                ParsedKeyword("пластиковые окна недорого", 200),
            ]
        )

        assert len(groups) == 1

    def test_разный_смысл_разводит_группы(self) -> None:
        groups = cluster(
            [
                ParsedKeyword("ремонт окон", 500),
                ParsedKeyword("ремонта окон", 400),
                ParsedKeyword("установка дверей", 300),
                ParsedKeyword("установку дверей", 200),
            ]
        )

        assert len(groups) == 2

    def test_частное_вливается_в_общее(self) -> None:
        """Иначе структура распадается на группы по одной фразе."""
        groups = cluster(
            [
                ParsedKeyword("ремонт окон", 1000),
                ParsedKeyword("ремонта окон", 800),
                ParsedKeyword("ремонт окон пвх", 50),
                ParsedKeyword("ремонта окон пвх", 40),
            ]
        )

        assert len(groups) == 1
        assert len(groups[0].phrases) == 4

    def test_группа_названа_самой_частотной_фразой(self) -> None:
        """Искусственное имя вроде «ремонт+окн» человек не читает."""
        groups = cluster(
            [ParsedKeyword("ремонт окон", 100), ParsedKeyword("ремонта окон срочно", 900)]
        )

        assert groups[0].name == "ремонта окон срочно"

    def test_группировка_объясняется_ядром(self) -> None:
        groups = cluster(
            [ParsedKeyword("ремонт окон", 100), ParsedKeyword("ремонта окон", 200)]
        )

        assert "ремонт" in groups[0].core

    def test_одиночные_фразы_собираются_в_остаток(self) -> None:
        """Кампания из одного ключа не обучится: Директу нужен объём."""
        groups = cluster(
            [
                ParsedKeyword("ремонт окон", 500),
                ParsedKeyword("ремонта окон", 400),
                ParsedKeyword("натяжные потолки", 10),
            ]
        )

        assert any(g.name == "Остальные фразы" for g in groups)

    def test_ни_одна_фраза_не_теряется(self) -> None:
        """Потерянная фраза — это трафик, которого не будет, и заметить нельзя."""
        keywords = [
            ParsedKeyword("ремонт окон", 500),
            ParsedKeyword("ремонта окон", 400),
            ParsedKeyword("установка дверей", 300),
            ParsedKeyword("натяжные потолки", 10),
            ParsedKeyword("купить недорого", 5),
        ]

        groups = cluster(keywords)
        collected = {phrase for group in groups for phrase in group.phrases}

        assert collected == {k.phrase for k in keywords}

    def test_фраза_не_попадает_в_две_группы(self) -> None:
        keywords = [
            ParsedKeyword("ремонт окон", 500),
            ParsedKeyword("ремонта окон", 400),
            ParsedKeyword("ремонт окон пвх", 50),
        ]

        groups = cluster(keywords)
        collected = [phrase for group in groups for phrase in group.phrases]

        assert len(collected) == len(set(collected))

    def test_группы_идут_от_крупных_к_мелким(self) -> None:
        groups = cluster(
            [
                ParsedKeyword("натяжные потолки", 100),
                ParsedKeyword("натяжных потолков", 90),
                ParsedKeyword("ремонт окон", 5000),
                ParsedKeyword("ремонта окон", 4000),
            ]
        )

        assert groups[0].total_frequency > groups[1].total_frequency

    def test_пустой_список_не_роняет_расчёт(self) -> None:
        assert cluster([]) == []


class TestМинусСлова:
    def test_собирает_слова_отсева(self) -> None:
        suggestions = suggest_minus_words(
            [
                ParsedKeyword("окна пвх вакансии", 100),
                ParsedKeyword("окна пвх работа", 80),
                ParsedKeyword("окна пвх бесплатно", 30),
                ParsedKeyword("окна пвх цена", 900),
            ]
        )

        words = {s.word for s in suggestions}
        assert {"вакансии", "работа", "бесплатно"} <= words
        assert "цена" not in words

    def test_частые_слова_идут_первыми(self) -> None:
        """Слово из одной фразы и слово из двухсот требуют разного внимания."""
        suggestions = suggest_minus_words(
            [
                ParsedKeyword("окна вакансии", 10),
                ParsedKeyword("двери вакансии", 10),
                ParsedKeyword("потолки вакансии", 10),
                ParsedKeyword("окна бесплатно", 10),
            ]
        )

        assert suggestions[0].word == "вакансии"
        assert suggestions[0].phrases == 3

    def test_приводятся_примеры(self) -> None:
        """Без примера непонятно, не выбросит ли минус-слово нужное."""
        suggestions = suggest_minus_words([ParsedKeyword("окна пвх вакансии", 10)])

        assert suggestions[0].examples == ("окна пвх вакансии",)


class TestСборкаГрупп:
    """Структура кампании должна быть из групп, а не из россыпи одиночек."""

    def test_группы_собираются_вокруг_частого_сочетания(self) -> None:
        groups = cluster(
            [
                ParsedKeyword("пластиковые окна тверь", 5400),
                ParsedKeyword("купить пластиковые окна", 3100),
                ParsedKeyword("пластиковые окна цена", 2800),
                ParsedKeyword("остекление балкона тверь", 900),
                ParsedKeyword("остекление балконов цена", 700),
            ]
        )

        assert len(groups) == 2
        assert {"окн", "пластиков"} == set(groups[0].core)

    def test_общее_ядро_собирает_и_узкие_фразы(self) -> None:
        """Раньше «остекление балкона тверь» не сливалось с «остекление балконов».

        Склейка работала в одну сторону: частное вливалось в общее, только если
        общее встретилось раньше. При обратном порядке частотностей обе фразы
        оставались одиночками и уезжали в остаток.
        """
        groups = cluster(
            [
                ParsedKeyword("остекление балкона тверь", 900),
                ParsedKeyword("остекление балконов цена", 700),
            ]
        )

        assert len(groups) == 1
        assert len(groups[0].phrases) == 2

    def test_пара_основ_предпочитается_одиночной(self) -> None:
        """Иначе «окн» смешало бы ремонт, остекление и продажу в одну группу."""
        groups = cluster(
            [
                ParsedKeyword("ремонт окон", 100),
                ParsedKeyword("ремонта окон", 90),
                ParsedKeyword("продажа окон", 80),
                ParsedKeyword("продажи окон", 70),
            ]
        )

        assert len(groups) == 2
        for group in groups:
            assert len(group.core) == 2

    def test_фраза_попадает_ровно_в_одну_группу(self) -> None:
        keywords = [
            ParsedKeyword("пластиковые окна тверь", 5400),
            ParsedKeyword("купить пластиковые окна", 3100),
            ParsedKeyword("окна пвх тверь", 1200),
            ParsedKeyword("окна пвх отзывы", 290),
            ParsedKeyword("ремонт окон тверь", 260),
        ]

        groups = cluster(keywords)
        collected = [phrase for group in groups for phrase in group.phrases]

        assert len(collected) == len(set(collected)) == len(keywords)


class TestПодборПосадочной:
    """Реклама на нерелевантную страницу — оплаченный клик без заявки.

    Мы сами называем это ошибкой в аудите, и делать её в собственных
    объявлениях тем более незачем.
    """

    PAGES: ClassVar[list[LandingPage]] = [
        LandingPage("https://x.ru/", "Пластиковые окна под ключ"),
        LandingPage("https://x.ru/balkony", "Остекление балконов и лоджий"),
        LandingPage("https://x.ru/remont", "Ремонт окон ПВХ"),
    ]

    def test_группа_ведёт_на_свою_страницу(self) -> None:
        assert (
            match_landing(("балкон", "остеклен"), self.PAGES, fallback="https://x.ru/")
            == "https://x.ru/balkony"
        )

    def test_беглая_гласная_не_мешает_совпадению(self) -> None:
        """В заголовке «Ремонт окон» основа «окон», а в ядре группы — «окн»."""
        assert (
            match_landing(("ремонт", "окн"), self.PAGES, fallback="https://x.ru/")
            == "https://x.ru/remont"
        )

    def test_без_совпадения_остаётся_главная(self) -> None:
        """На главной человек хотя бы попадает в понятное место."""
        assert (
            match_landing(("потолк", "натяжн"), self.PAGES, fallback="https://x.ru/")
            == "https://x.ru/"
        )

    def test_страница_без_заголовка_не_участвует(self) -> None:
        pages = [LandingPage("https://x.ru/tmp", None)]

        assert match_landing(("окн",), pages, fallback="https://x.ru/") == "https://x.ru/"

    def test_пустое_ядро_ведёт_на_главную(self) -> None:
        assert match_landing((), self.PAGES, fallback="https://x.ru/") == "https://x.ru/"
