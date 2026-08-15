"""Черновики объявлений.

Проверяется то, из-за чего объявление не запустится: превышенные лимиты Директа
и слова, из-за которых приходит отказ. Ошибка здесь стоит не денег, а времени —
кампания просто не выйдет на показы, и специалист узнает об этом от модератора.
"""

from __future__ import annotations

from ads_os.services.ads import (
    MAX_CALLOUT,
    MAX_TEXT,
    MAX_TITLE,
    MAX_TITLE_2,
    Problem,
    build_draft,
)

POINTS = ("Замер бесплатно", "Окно от 12 900 ₽", "Гарантия 5 лет", "11 лет на рынке")


def draft(cluster: str = "пластиковые окна тверь", **kwargs: object):
    defaults: dict[str, object] = {
        "cluster_name": cluster,
        "keywords": ("пластиковые окна тверь",),
        "selling_points": POINTS,
        "region": "Тверь",
    }
    defaults.update(kwargs)
    return build_draft(**defaults)  # type: ignore[arg-type]


class TestСборка:
    def test_заголовок_это_ключевая_фраза(self) -> None:
        """Директ подсвечивает совпадение с запросом — это главный рычаг релевантности."""
        assert draft().title == "Пластиковые окна тверь"

    def test_текст_собран_из_фрагментов_страницы(self) -> None:
        """Объявление не должно обещать того, чего нет на посадочной."""
        result = draft()

        assert "Замер бесплатно" in result.text
        assert "12 900" in result.text

    def test_второй_заголовок_помещается_в_лимит(self) -> None:
        result = draft()

        assert result.title_2 is not None
        assert len(result.title_2) <= MAX_TITLE_2

    def test_уточнения_не_дублируют_второй_заголовок(self) -> None:
        result = draft()

        assert result.title_2 not in result.callouts

    def test_отображаемая_ссылка_читается_как_раздел(self) -> None:
        assert draft().display_path == "пластиковые"


class TestЛимитыДиректа:
    def test_собранный_черновик_проходит_лимиты(self) -> None:
        result = draft()

        assert len(result.title) <= MAX_TITLE
        assert len(result.text) <= MAX_TEXT
        assert all(len(c) <= MAX_CALLOUT for c in result.callouts)
        assert result.is_ready

    def test_длинная_фраза_режется_по_словам(self) -> None:
        """Обрубок слова читается как опечатка и бьёт по доверию сильнее длины."""
        long_phrase = "остекление балконов и лоджий под ключ недорого с гарантией в твери"
        result = draft(long_phrase)

        assert len(result.title) <= MAX_TITLE
        assert not result.title.endswith("-")
        # Последнее слово должно остаться целым.
        assert result.title.split()[-1] in long_phrase.split()

    def test_о_сокращении_сообщается(self) -> None:
        """Молчаливое обрезание — это подмена того, что человек хотел сказать."""
        result = draft("остекление балконов и лоджий под ключ недорого с гарантией в твери")

        assert any(v.problem is Problem.TOO_LONG for v in result.violations)

    def test_текст_не_переполняется_фрагментами(self) -> None:
        many = tuple(f"Фрагмент предложения номер {i}" for i in range(20))
        result = draft(selling_points=many)

        assert len(result.text) <= MAX_TEXT

    def test_регион_не_дописывается_обрезанным(self) -> None:
        """«в Твер» хуже, чем отсутствие региона."""
        long_points = ("Очень длинный фрагмент предложения ровно на весь доступный текст",)
        result = draft(selling_points=long_points, region="Санкт-Петербург")

        assert len(result.text) <= MAX_TEXT
        assert "Санкт-Пет" not in result.text or "Санкт-Петербург" in result.text


class TestМодерация:
    def test_превосходная_степень_помечается(self) -> None:
        """Требует документального подтверждения, которого почти никогда нет."""
        result = draft(selling_points=("Самые низкие цены",))

        assert any(v.problem is Problem.UNPROVEN_SUPERLATIVE for v in result.violations)

    def test_капс_помечается(self) -> None:
        result = draft(selling_points=("СКИДКА только сегодня",))

        assert any(v.problem is Problem.CAPS for v in result.violations)

    def test_аббревиатура_капсом_не_считается_нарушением(self) -> None:
        """Иначе «окна ПВХ» нельзя было бы написать вовсе."""
        result = draft("окна пвх тверь", selling_points=("Профиль ПВХ от 12 900 ₽",))

        assert not any(v.problem is Problem.CAPS for v in result.violations)

    def test_нарушение_названо_понятно(self) -> None:
        result = draft(selling_points=("Самые низкие цены",))

        message = result.violations[0].message
        assert len(message) > 20
        assert "отказ" in message or "не примет" in message


class TestПустойСайт:
    def test_без_фрагментов_текст_не_выдумывается(self) -> None:
        """Сочинённое обещание — это отказ на модерации или претензия клиента."""
        result = draft(selling_points=())

        assert result.text == ""
        assert any(v.problem is Problem.NOTHING_TO_SAY for v in result.violations)

    def test_отсутствие_текста_объясняется(self) -> None:
        result = draft(selling_points=())
        problem = next(v for v in result.violations if v.problem is Problem.NOTHING_TO_SAY)

        assert "вручную" in problem.message

    def test_черновик_без_текста_не_считается_готовым(self) -> None:
        assert draft(selling_points=()).is_ready is False


class TestБыстрыеСсылки:
    """Занимают место в выдаче и дают попасть сразу в нужный раздел."""

    LINKS = (
        ("Пластиковые окна", "/okna"),
        ("Остекление балконов", "/balkony"),
        ("Цены", "/ceny"),
        ("О компании", "/o-nas"),
        ("Отзывы", "/otzyvy"),
        ("Контакты", "/kontakty"),
    )

    def test_ссылки_собираются_из_разделов_сайта(self) -> None:
        result = draft(internal_links=self.LINKS)

        assert len(result.sitelinks) == 4
        assert result.sitelinks[0].url.startswith("/")

    def test_раздел_совпадающий_с_темой_группы_пропускается(self) -> None:
        """Вести из объявления «окна» в раздел «окна» — потратить место зря."""
        result = draft("пластиковые окна тверь", internal_links=self.LINKS)

        assert "Пластиковые окна" not in {link.title for link in result.sitelinks}

    def test_длинная_подпись_не_берётся(self) -> None:
        long_title = "Остекление балконов и лоджий под ключ с гарантией"
        result = draft(internal_links=((long_title, "/x"), ("Цены", "/ceny")))

        assert [link.title for link in result.sitelinks] == ["Цены"]

    def test_без_ссылок_черновик_не_ломается(self) -> None:
        result = draft(internal_links=())

        assert result.sitelinks == ()
        assert result.is_ready
