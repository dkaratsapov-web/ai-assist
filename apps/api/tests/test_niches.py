"""Шаблоны ниш.

Проверяется то, ради чего шаблоны существуют: они дают проверяемое знание
(слова и требования площадки), не выдают допущений за факты и не молчат там,
где молчание стоит отклонённых объявлений.
"""

from __future__ import annotations

import pytest

from ads_os.services.audit import BLOCKING_ISSUE_KEYS, IssueKey, Severity, audit_page
from ads_os.services.niches import (
    COMMON_MINUS_WORDS,
    NICHES,
    get,
    minus_words,
    requirement_issues,
)


class TestСправочник:
    def test_ключи_не_повторяются(self) -> None:
        keys = [n.key for n in NICHES]

        assert len(keys) == len(set(keys))

    def test_ниша_находится_по_ключу(self) -> None:
        assert get("supplements") is not None

    def test_неизвестный_ключ_не_ломает(self) -> None:
        """Ниши живут в коде, а ключ — в базе. Удалённая ниша не должна ронять
        проект, который на неё ссылается."""
        assert get("ниша-которой-нет") is None
        assert get(None) is None

    def test_у_каждой_ниши_есть_чем_помочь(self) -> None:
        for niche in NICHES:
            assert niche.label
            assert niche.minus_words or niche.requirements or niche.notes


class TestМинусСлова:
    def test_общие_слова_есть_всегда(self) -> None:
        """Даже без ниши «бесплатно» и «своими руками» минусуют почти все."""
        words = minus_words(None)

        assert "своими руками" in words
        assert "вакансии" in words

    def test_нишевые_добавляются_к_общим(self) -> None:
        words = minus_words(get("auto_service"))

        assert "своими руками" in words
        assert "запчасти купить" in words

    def test_без_повторов(self) -> None:
        """Общее слово, повторённое в нише, не должно предлагаться дважды."""
        for niche in NICHES:
            words = minus_words(niche)
            assert len(words) == len(set(words))

    def test_общие_слова_не_дублируются_в_нишах(self) -> None:
        """Иначе список ниши растёт, а пользы не прибавляется."""
        common = set(COMMON_MINUS_WORDS)
        for niche in NICHES:
            assert not (set(niche.minus_words) & common), niche.key


class TestТребованияПлощадки:
    def test_бад_без_оговорки_блокирует_запуск(self) -> None:
        issues = requirement_issues(get("supplements"), "<html>Витамины со скидкой</html>")

        assert [i.key for i in issues] == [IssueKey.NO_SUPPLEMENT_DISCLAIMER]
        assert issues[0].key in BLOCKING_ISSUE_KEYS

    def test_оговорка_на_странице_снимает_замечание(self) -> None:
        html = "<html>Витамины. БАД, не является лекарственным средством.</html>"

        assert requirement_issues(get("supplements"), html) == ()

    def test_клинике_нужны_и_лицензия_и_противопоказания(self) -> None:
        issues = requirement_issues(get("medical_clinic"), "<html>Приём врача</html>")

        assert {i.key for i in issues} == {
            IssueKey.NO_MEDICAL_LICENCE,
            IssueKey.NO_CONTRAINDICATION_WARNING,
        }

    def test_ниша_без_требований_ничего_не_добавляет(self) -> None:
        assert requirement_issues(get("cleaning"), "<html>Уборка</html>") == ()

    def test_без_ниши_проверок_нет(self) -> None:
        """Искать лицензию на сайте по продаже окон бессмысленно."""
        assert requirement_issues(None, "<html>Окна</html>") == ()

    def test_регистр_не_мешает(self) -> None:
        html = "<html>НЕ ЯВЛЯЕТСЯ ЛЕКАРСТВЕННЫМ СРЕДСТВОМ</html>"

        assert requirement_issues(get("supplements"), html) == ()

    def test_юридические_реквизиты_предупреждают_а_не_блокируют(self) -> None:
        """Отсутствие ИНН на странице — повод поправить сайт, но реклама
        юруслуг без него всё-таки выходит."""
        issues = requirement_issues(get("legal_services"), "<html>Юрист</html>")

        assert issues[0].severity is Severity.WARNING
        assert issues[0].key not in BLOCKING_ISSUE_KEYS


class TestВлияниеНаАудит:
    """Нишевая находка должна менять вердикт, а не лежать примечанием."""

    PAGE = """
    <html><head><title>Витамины</title></head><body>
      <h1>Витамины для иммунитета</h1>
      <p>Цена 990 ₽. Гарантия качества, сертификаты, 10 лет на рынке.</p>
      <a href="tel:+79001234567">+7 900 123-45-67</a>
      <form><input name="name"><input name="phone">
        <button>Заказать</button>
        <a href="/privacy">Политика конфиденциальности</a>
      </form>
      <script>ym(12345678, 'init', {});</script>
    </body></html>
    """

    def test_без_оговорки_сайт_не_готов(self) -> None:
        result = audit_page(
            "https://example.ru",
            self.PAGE,
            extra_issues=requirement_issues(get("supplements"), self.PAGE),
        )

        assert result.can_launch is False
        assert any(i.key is IssueKey.NO_SUPPLEMENT_DISCLAIMER for i in result.issues)

    def test_с_оговоркой_сайт_проходит(self) -> None:
        page = self.PAGE.replace(
            "Цена 990 ₽.", "Цена 990 ₽. БАД, не является лекарственным средством."
        )

        result = audit_page(
            "https://example.ru",
            page,
            extra_issues=requirement_issues(get("supplements"), page),
        )

        assert result.can_launch is True

    def test_чужие_находки_не_теряются(self) -> None:
        """Разбор страницы добавляет свои замечания поверх переданных."""
        result = audit_page("http://example.ru", "<html></html>", extra_issues=())

        assert result.issues


class TestЧестностьШаблона:
    """Шаблон не должен подсовывать допущения под видом данных клиента."""

    def test_в_шаблоне_нет_цифр_экономики(self) -> None:
        """Конверсия и цена клика зависят от региона, сезона и самого сайта
        сильнее, чем от отрасли. Отраслевое среднее в поле проекта выглядело бы
        как факт о бизнесе клиента — ровно то, от чего защищает расчёт
        экономики тремя состояниями достоверности."""
        for niche in NICHES:
            fields = set(niche.__slots__)
            assert not fields & {
                "site_conversion_rate",
                "expected_cpc",
                "lead_to_sale_rate",
                "margin_percent",
                "average_order_value",
            }

    @pytest.mark.parametrize("niche", NICHES, ids=lambda n: n.key)
    def test_заметки_это_вопросы_а_не_приказы(self, niche) -> None:  # type: ignore[no-untyped-def]
        """Заметка должна помогать думать, а не подменять решение специалиста:
        поэтому она достаточно развёрнута, чтобы её можно было оспорить."""
        for note in niche.notes:
            assert len(note) > 40
