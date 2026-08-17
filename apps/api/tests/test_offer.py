"""Предметное сравнение: условия предложения, а не галочки.

Таблица «есть форма — нет формы» отвечает на вопрос, который специалист не
задаёт. К конкуренту он приходит смотреть, чем тот берёт: какая цена, какой
срок, что обещают бесплатно. Здесь проверяется, что именно это и достаётся —
дословно, чтобы можно было открыть чужой сайт и найти ту же строку глазами.
"""

from __future__ import annotations

from ads_os.services.competitors import OfferKey, compare_offers
from ads_os.services.offer import OfferFacts, extract, from_stored

MINE = """
<html><body>
  <h1>Натяжные потолки в Твери</h1>
  <p>Монтаж от 450 ₽ за м². Замер бесплатно.</p>
  <p>Гарантия 12 месяцев на полотно.</p>
  <form><input name="name"><input name="phone"><input name="email"><input name="comment"></form>
</body></html>
"""

RIVAL = """
<html><body>
  <h1>Натяжные потолки за 1 день</h1>
  <p>Цена от 290 ₽ за м². Замер бесплатно, доставка бесплатно.</p>
  <p>Гарантия 10 лет. Скидка 20% до конца месяца. Рассрочка 0%.</p>
  <a href="https://t.me/rival">Telegram</a>
  <form><input name="phone"></form>
</body></html>
"""


class TestЧтоЧитаетсяСоСтраницы:
    def test_цены_числом_и_цитатой(self) -> None:
        facts = extract(RIVAL)

        assert facts.min_price == 290
        assert any("290" in quote for quote in facts.price_quotes)

    def test_срок(self) -> None:
        assert any("1 день" in quote for quote in extract(RIVAL).deadlines)

    def test_гарантия_только_со_сроком(self) -> None:
        """«Гарантия качества» — это слово, а не условие: сравнивать нечего."""
        assert extract(RIVAL).guarantees[0].lower().startswith("гарантия 10 лет")
        assert extract("<html><body><p>Гарантия качества</p></body></html>").guarantees == ()

    def test_что_бесплатно(self) -> None:
        free = " ".join(extract(RIVAL).free_offers).lower()

        assert "замер" in free
        assert "доставка" in free

    def test_акции_и_рассрочка(self) -> None:
        promos = " ".join(extract(RIVAL).promos).lower()

        assert "скидка" in promos
        assert "рассрочка" in promos

    def test_длина_формы(self) -> None:
        assert extract(MINE).form_fields == 4
        assert extract(RIVAL).form_fields == 1

    def test_цитаты_дословные(self) -> None:
        """Пересказ своими словами превращает факт в мнение."""
        assert "Замер бесплатно" in " ".join(extract(MINE).free_offers)

    def test_мелкие_числа_за_цену_не_принимаются(self) -> None:
        """«5 ₽» на странице услуг — это остаток номера или цена сантиметра."""
        assert extract("<html><body><p>всего 5 руб</p></body></html>").price_values == ()

    def test_скрытое_содержимое_не_читается(self) -> None:
        html = '<html><body><script>var p = "от 100 ₽";</script></body></html>'

        assert extract(html).price_values == ()

    def test_сохранение_и_чтение_обратно(self) -> None:
        facts = extract(RIVAL)

        assert from_stored(facts.as_dict()) == facts

    def test_пустое_хранилище_не_ломает_чтение(self) -> None:
        assert from_stored(None) == OfferFacts()


def rivals(*pages: str) -> tuple[tuple[str, str, OfferFacts], ...]:
    return tuple(
        (f"Конкурент {i}", f"https://rival{i}.ru/", extract(page))
        for i, page in enumerate(pages, start=1)
    )


class TestСравнение:
    def test_цена_сравнивается_числами(self) -> None:
        """Не «цены есть у обоих», а насколько именно ваша выше."""
        result = compare_offers(extract(MINE), rivals(RIVAL))
        row = next(r for r in result.rows if r.key is OfferKey.PRICE)

        assert "450" in row.verdict
        assert "290" in row.verdict
        assert row.is_gap is True

    def test_самая_низкая_цена_названа_преимуществом(self) -> None:
        result = compare_offers(extract(RIVAL), rivals(MINE))
        row = next(r for r in result.rows if r.key is OfferKey.PRICE)

        assert row.is_gap is False
        assert "заголовок" in row.verdict

    def test_отсутствие_цены_у_себя_видно(self) -> None:
        result = compare_offers(OfferFacts(), rivals(RIVAL))
        row = next(r for r in result.rows if r.key is OfferKey.PRICE)

        assert row.is_gap is True
        assert "290" in row.verdict

    def test_срок_с_цитатой_конкурента(self) -> None:
        """Своего срока нет, у конкурента есть — и он назван дословно."""
        result = compare_offers(extract(MINE), rivals(RIVAL, RIVAL))
        row = next(r for r in result.rows if r.key is OfferKey.DEADLINE)

        assert row.is_gap is True
        assert "1 день" in row.verdict

    def test_один_конкурент_с_особым_условием_не_делает_пробела(self) -> None:
        """Порог — большинство: иначе любая чужая находка объявляется нашим
        упущением, и список пробелов перестают читать."""
        plain = "<html><body><h1>Потолки</h1><p>от 400 ₽</p></body></html>"
        result = compare_offers(extract(MINE), rivals(RIVAL, plain, plain))
        row = next(r for r in result.rows if r.key is OfferKey.DEADLINE)

        assert row.is_gap is False

    def test_наше_отличие_отмечается(self) -> None:
        plain = "<html><body><h1>Потолки</h1><p>от 900 ₽</p></body></html>"
        result = compare_offers(extract(MINE), rivals(plain, plain))
        row = next(r for r in result.rows if r.key is OfferKey.GUARANTEE)

        assert "только у вас" in row.verdict

    def test_длинная_форма_названа_числом(self) -> None:
        result = compare_offers(extract(MINE), rivals(RIVAL))
        row = next(r for r in result.rows if r.key is OfferKey.FORM)

        assert row.is_gap is True
        assert "4" in row.verdict and "1" in row.verdict

    def test_значение_каждого_конкурента_подписано(self) -> None:
        """Без имени и адреса непонятно, к кому идти смотреть."""
        result = compare_offers(extract(MINE), rivals(RIVAL))
        row = next(r for r in result.rows if r.key is OfferKey.PRICE)

        assert row.rivals[0].title == "Конкурент 1"
        assert row.rivals[0].url == "https://rival1.ru/"
        assert "290" in row.rivals[0].value

    def test_без_конкурентов_выводов_нет(self) -> None:
        """Сравнивать не с чем — и придумывать вывод не из чего."""
        result = compare_offers(extract(MINE), ())

        assert result.has_data is False
        assert all(row.verdict == "" for row in result.rows)

    def test_пустые_страницы_конкурентов_видно(self) -> None:
        result = compare_offers(extract(MINE), rivals("<html><body></body></html>"))

        assert result.has_data is False
