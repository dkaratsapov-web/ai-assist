"""Анкета клиента, прочитанная с его сайта.

Главное здесь — граница. Всё, что на сайте написано, читаем; всего, чего на
сайте не бывает, не выдумываем. Ошибка в первую сторону стоит лишнего вопроса,
ошибка во вторую — расчёта экономики, построенного на придуманных числах.
"""

from __future__ import annotations

import pytest

from ads_os.services import profile
from ads_os.services.profile import ClientProfile, extract, niche_questions, open_questions

PAGE = """
<html lang="ru"><head>
  <title>Натяжные потолки в Твери — Компания «Потолок»</title>
  <meta property="og:site_name" content="Потолок">
</head><body>
  <nav><a href="/">Главная</a><a href="/ceilings">Натяжные потолки</a>
    <a href="/light">Световые линии</a><a href="/contacts">Контакты</a></nav>
  <h1>Натяжные потолки в Твери за 1 день</h1>
  <h2>Глянцевые и матовые полотна</h2>
  <h2>Многоуровневые потолки</h2>
  <p>Монтаж от 350 ₽ за м². Замер бесплатно. Багет в подарок.</p>
  <p>Работаем ежедневно с 9:00 до 20:00.</p>
  <p>Телефон: <a href="tel:+79001234567">+7 (900) 123-45-67</a>, почта: info@potolok.ru</p>
  <a href="https://t.me/potolok">Telegram</a>
  <a href="https://wa.me/79001234567">WhatsApp</a>
  <p>Адрес: г. Тверь, ул. Советская, д. 10</p>
  <p>ООО «Потолок», ИНН 6950123456</p>
</body></html>
"""


class TestЧтоЧитаетсяССайта:
    def test_город(self) -> None:
        assert extract(PAGE).city == "Тверь"

    def test_ниша_угадывается(self) -> None:
        result = extract(PAGE)

        assert result.niche_key == "stretch_ceilings"
        assert result.niche_label == "Натяжные потолки"

    def test_ниша_не_угадывается_по_одному_слову(self) -> None:
        """«Окна» есть и у клининга, который их моет. Одно совпадение — не ниша."""
        html = "<html><body><h1>Клининг</h1><p>Моем окна в офисах</p></body></html>"

        assert extract(html).niche_key != "plastic_windows"

    def test_название_юрлица_предпочтительнее_заголовка(self) -> None:
        assert extract(PAGE).company == "ООО «Потолок»"

    def test_услуги_из_заголовков_и_меню(self) -> None:
        services = extract(PAGE).services

        assert "Глянцевые и матовые полотна" in services
        assert "Многоуровневые потолки" in services

    def test_город_из_названия_услуги_убирается(self) -> None:
        """Иначе «Натяжные потолки в Твери» уедет в бриф вместе с городом, а
        город там уже есть отдельным полем."""
        assert "Натяжные потолки" in extract(PAGE).services

    def test_общие_пункты_меню_услугами_не_считаются(self) -> None:
        services = [item.lower() for item in extract(PAGE).services]

        assert "главная" not in services
        assert "контакты" not in services

    def test_цены(self) -> None:
        assert any("350" in price for price in extract(PAGE).prices)

    def test_контакты(self) -> None:
        result = extract(PAGE)

        assert result.phones == ("+7 (900) 123-45-67",)
        assert result.emails == ("info@potolok.ru",)
        assert set(result.messengers) == {"Telegram", "WhatsApp"}

    def test_адрес_и_реквизиты(self) -> None:
        result = extract(PAGE)

        assert "Советская" in (result.address or "")
        assert result.company_details == "ИНН 6950123456"

    def test_режим_работы(self) -> None:
        assert extract(PAGE).working_hours is not None

    def test_пустая_страница_даёт_пустую_анкету(self) -> None:
        """Ни одно поле не заполняется догадкой: пусто значит пусто."""
        result = extract("<html><body><p>Скоро открытие</p></body></html>")

        assert result.filled == 0

    def test_скрипты_в_анкету_не_попадают(self) -> None:
        """В JSON на странице бывает и телефон, и цена — но это не витрина."""
        html = (
            "<html><body><h1>Потолки</h1>"
            '<script>var d = {"phone":"+7 (999) 111-11-11"};</script>'
            "</body></html>"
        )

        assert extract(html).phones == ()


class TestВопросыКлиенту:
    def test_общие_вопросы_задаются_всегда(self) -> None:
        """Средний чек и маржа не написаны ни на одном сайте — и не будут."""
        keys = {q.key for q in open_questions(extract(PAGE))}

        assert "average_check" in keys
        assert "lead_to_sale" in keys

    def test_пробел_в_анкете_превращается_в_вопрос(self) -> None:
        keys = {q.key for q in open_questions(ClientProfile())}

        assert "city" in keys
        assert "niche" in keys
        assert "prices" in keys

    def test_найденное_повторно_не_спрашивается(self) -> None:
        keys = {q.key for q in open_questions(extract(PAGE))}

        assert "city" not in keys
        assert "niche" not in keys

    def test_у_каждого_вопроса_есть_обоснование(self) -> None:
        """Вопрос без объяснения, зачем он, пропускают."""
        for question in open_questions(ClientProfile()):
            assert len(question.why) > 30, question.text

    def test_вопросы_ниши_добавляются_отдельно(self) -> None:
        assert len(niche_questions("stretch_ceilings")) > 0

    def test_без_ниши_нишевых_вопросов_нет(self) -> None:
        assert niche_questions(None) == ()


class TestНавигацияНеУслуга:
    """Пункты меню и контакты не должны попадать в «что продаём».

    Разбор брал их и раньше, и это выглядело безобидной неточностью в анкете.
    Безобидной она не была: из брифа строятся маски для Вордстата, и система
    собирала частотность по номеру телефона, тратя запрос из сотни в час.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "Связаться с нами",
            "Наши услуги",
            "О нашей команде",
            "Проекты",
            "Портфолио",
            "Оставить заявку",
            "Заказать звонок",
            "Отзывы клиентов",
            "Политика конфиденциальности",
            "8 (922) 155-53-66",
            "design@shadrina-interiors.ru",
            "+7 900 123-45-67",
        ],
    )
    def test_навигация_и_контакты_отсеиваются(self, text: str) -> None:
        assert profile.is_service(text) is False

    @pytest.mark.parametrize(
        "text",
        [
            "Дизайн интерьера",
            "Натяжные потолки",
            "Остекление балконов под ключ",
            "Ремонт квартир",
            "Пластиковые окна ПВХ",
        ],
    )
    def test_настоящие_услуги_остаются(self, text: str) -> None:
        assert profile.is_service(text) is True

    def test_меню_не_попадает_в_анкету(self) -> None:
        html = """
        <html><body>
          <nav>
            <a href="/">Главная</a>
            <a href="/services">Наши услуги</a>
            <a href="/projects">Проекты</a>
            <a href="/team">О нашей команде</a>
            <a href="/contacts">Связаться с нами</a>
            <a href="tel:+79221555366">8 (922) 155-53-66</a>
            <a href="mailto:design@studio.ru">design@studio.ru</a>
          </nav>
          <h1>Дизайн интерьера</h1>
          <h2>Авторский надзор</h2>
        </body></html>
        """

        found = profile.extract(html).services

        assert "Дизайн интерьера" in found
        assert all("связаться" not in item.lower() for item in found)
        assert all("@" not in item for item in found)
        assert all(not item.strip().startswith("8 (") for item in found)
