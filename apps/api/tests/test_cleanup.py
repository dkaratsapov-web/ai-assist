"""Чистка загруженного списка запросов.

Проверяется не столько то, что мусор находится, сколько то, что находится
только мусор. Разметка, которая режет лишнее, хуже отсутствующей: человек
доверился ей один раз, потерял на этом заявки и больше не откроет этот экран.
"""

from __future__ import annotations

from ads_os.services.cleanup import (
    REASON_HINTS,
    REASON_LABELS,
    Reason,
    cities_in,
    foreign_city,
    is_nationwide,
    reason_for,
)
from ads_os.services.semantics import Intent, ParsedKeyword, classify, suggest_minus_words


class TestГорода:
    def test_город_находится_в_любом_падеже(self) -> None:
        for phrase in ("окна москва", "окна в москве", "доставка из москвы"):
            assert cities_in(phrase) == ("Москва",), phrase

    def test_сокращения_и_разговорные_названия(self) -> None:
        assert cities_in("окна спб") == ("Санкт-Петербург",)
        assert cities_in("ремонт в питере") == ("Санкт-Петербург",)
        assert cities_in("доставка екб") == ("Екатеринбург",)

    def test_составное_название_не_распадается(self) -> None:
        """Иначе «Нижний Новгород» дал бы заодно и Новгород."""
        assert cities_in("окна нижний новгород") == ("Нижний Новгород",)

    def test_несколько_городов_в_порядке_упоминания(self) -> None:
        assert cities_in("доставка москва тверь") == ("Москва", "Тверь")

    def test_обычные_слова_не_принимаются_за_города(self) -> None:
        """«Твердый», «работа», «орет» — не Тверь, не Ростов и не Орёл."""
        for phrase in ("твердый профиль", "рабочая поверхность", "орет громко"):
            assert cities_in(phrase) == (), phrase


class TestЧужойГород:
    def test_чужой_город_находится(self) -> None:
        assert foreign_city("пластиковые окна москва", "Тверь") == "Москва"

    def test_свой_город_не_считается_чужим(self) -> None:
        assert foreign_city("пластиковые окна тверь", "Тверь") is None

    def test_область_в_регионе_засчитывает_город(self) -> None:
        """В поле региона обычно пишут «Тверская область», а не «Тверь»."""
        assert foreign_city("окна в твери", "Тверская область") is None

    def test_без_региона_география_молчит(self) -> None:
        """Судить не по чему: любое решение здесь было бы догадкой."""
        assert foreign_city("пластиковые окна москва", None) is None

    def test_нераспознанный_регион_тоже_молчит(self) -> None:
        assert foreign_city("пластиковые окна москва", "центральный офис") is None

    def test_работа_по_всей_стране_отключает_проверку(self) -> None:
        assert is_nationwide("Россия") is True
        assert foreign_city("пластиковые окна москва", "Россия") is None

    def test_несколько_своих_городов(self) -> None:
        assert foreign_city("окна тверь", "Тверь, Москва") is None
        assert foreign_city("окна казань", "Тверь, Москва") == "Казань"


class TestРазборФразы:
    def test_чужой_город_сильнее_коммерческих_признаков(self) -> None:
        """Такая фраза выглядит образцово целевой — на то и расчёт."""
        result = classify("купить пластиковые окна в москве недорого", region="Тверь")

        assert result.intent is Intent.IRRELEVANT
        assert result.trigger == "Москва"
        assert result.reason is Reason.GEO

    def test_свой_город_остаётся_целевым(self) -> None:
        result = classify("купить пластиковые окна в твери", region="Тверь")

        assert result.intent is Intent.COMMERCIAL

    def test_без_региона_город_не_влияет(self) -> None:
        assert classify("окна москва").intent is Intent.COMMERCIAL

    def test_у_каждой_нецелевой_фразы_есть_причина(self) -> None:
        cases = {
            "окна своими руками": Reason.DIY,
            "вакансия монтажник окон": Reason.JOB,
            "окна бесплатно": Reason.FREE,
            "окна бу": Reason.USED,
            "реферат про окна": Reason.STUDY,
            "скачать каталог окон": Reason.MEDIA,
            "окна авито": Reason.MARKETPLACE,
            "окна мошенники": Reason.FRAUD,
        }

        for phrase, reason in cases.items():
            result = classify(phrase)
            assert result.intent is Intent.IRRELEVANT, phrase
            assert result.reason is reason, phrase

    def test_причина_находится_и_по_другой_форме_слова(self) -> None:
        """Сработала основа «работ», а объяснить надо «ищут работу»."""
        result = classify("окна работу ищу")

        assert result.reason is Reason.JOB
        assert result.trigger in {"работу", "ищу работу"}

    def test_минус_слово_из_двух_слов_отсекает_только_целиком(self) -> None:
        """Иначе «ремонт» и «окон» по отдельности вырезали бы половину ядра."""
        minus = frozenset({"ремонт окон"})

        assert classify("ремонт окон тверь", extra_irrelevant=minus).intent is Intent.IRRELEVANT
        assert classify("пластиковые окна тверь", extra_irrelevant=minus).intent is not (
            Intent.IRRELEVANT
        )
        assert classify("ремонт квартир тверь", extra_irrelevant=minus).intent is not (
            Intent.IRRELEVANT
        )

    def test_своё_минус_слово_названо_своим(self) -> None:
        result = classify("окна рассрочка", extra_irrelevant=frozenset({"рассрочка"}))

        assert result.reason is Reason.MINUS_WORD

    def test_спорные_слова_не_режутся(self) -> None:
        """Для юриста «суд» — это работа, для школы «онлайн-курс» — товар.
        Словарь, отрезающий половину ядра в своей же нише, вреден."""
        for phrase in ("составить иск в суд", "требуется ремонт окон", "заказать окна"):
            assert classify(phrase).intent is not Intent.IRRELEVANT, phrase


class TestПодсказкиМинусСлов:
    def test_города_в_минус_слова_не_предлагаются(self) -> None:
        """Городов в выгрузке десятки, и правильное решение — регион показа,
        а не два десятка минус-слов, которые всё равно всех не покроют."""
        keywords = [
            ParsedKeyword("окна москва", 100),
            ParsedKeyword("окна казань", 50),
            ParsedKeyword("окна своими руками", 30),
        ]

        words = {item.word for item in suggest_minus_words(keywords, region="Тверь")}

        assert "Москва" not in words
        assert "своими руками" in words

    def test_у_подсказки_есть_причина(self) -> None:
        keywords = [ParsedKeyword("окна вакансии", 10)]

        assert suggest_minus_words(keywords)[0].reason is Reason.JOB


class TestОбъяснения:
    def test_у_каждой_причины_есть_название_и_подсказка(self) -> None:
        for reason in Reason:
            assert REASON_LABELS[reason]
            assert len(REASON_HINTS[reason]) > 20, reason

    def test_без_пометки_причины_нет(self) -> None:
        assert reason_for(None) is None
        assert reason_for("совершенно обычное слово") is None
