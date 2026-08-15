"""Тесты аудита сайта.

Главное, что проверяется: критические находки действительно запрещают запуск,
а не просто снижают балл. Смысл аудита именно в этом — не поставить оценку, а
не пустить платный трафик на сайт, где он гарантированно потратится впустую.
"""

from __future__ import annotations

from ads_os.services.audit import Category, Severity, Verdict, audit_page

GOOD_PAGE = """
<html><head>
  <title>Ремонт техники Apple в Твери</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script>ym(12345678, 'init', {});</script>
</head><body>
  <h1>Ремонт iPhone за 1 час с гарантией</h1>
  <p>Замена экрана от 3 500 ₽. Диагностика бесплатно. Гарантия 12 месяцев.</p>
  <p>Более 2000 отзывов, сертифицированный сервис, 8 лет на рынке.</p>
  <a href="https://t.me/example">Написать в Telegram</a>
  <p>Телефон: +7 (900) 123-45-67</p>
  <form action="/lead"><input name="phone"><button>Оставить заявку</button></form>
  <a href="/privacy">Политика конфиденциальности</a>
</body></html>
"""

BARE_PAGE = "<html><head><title>Сайт</title></head><body><p>Мы работаем</p></body></html>"


class TestХорошийСайт:
    def test_готов_к_рекламе(self) -> None:
        result = audit_page("https://example.com/", GOOD_PAGE)

        assert result.verdict is Verdict.READY
        assert result.can_launch is True
        assert result.score >= 80
        assert result.blocking_issues == ()

    def test_счётчик_метрики_найден(self) -> None:
        result = audit_page("https://example.com/", GOOD_PAGE)
        assert result.metrica_counter == "12345678"

    def test_счётчик_находится_и_по_адресу_скрипта(self) -> None:
        html = GOOD_PAGE.replace(
            "<script>ym(12345678, 'init', {});</script>",
            '<script src="https://mc.yandex.ru/metrika/watch/87654321.js"></script>',
        ).replace("mc.yandex.ru/metrika/watch/", "mc.yandex.ru/watch/")
        result = audit_page("https://example.com/", html)
        assert result.metrica_counter == "87654321"


class TestБлокирующиеНаходки:
    def test_нет_аналитики_запрещает_запуск(self) -> None:
        """Без счётчика не видно, какие клики приносят заявки."""
        html = GOOD_PAGE.replace("<script>ym(12345678, 'init', {});</script>", "")
        result = audit_page("https://example.com/", html)

        assert result.can_launch is False
        assert result.verdict is Verdict.NOT_READY
        assert any(i.category is Category.TRACKING for i in result.blocking_issues)

    def test_не_с_чем_связаться_запрещает_запуск(self) -> None:
        result = audit_page("https://example.com/", BARE_PAGE)

        assert result.can_launch is False
        blocking = {i.category for i in result.blocking_issues}
        assert Category.CONVERSION in blocking

    def test_сайт_без_https_запрещает_запуск(self) -> None:
        result = audit_page("http://example.com/", GOOD_PAGE)

        assert result.can_launch is False
        assert any("HTTPS" in i.title for i in result.blocking_issues)

    def test_ошибка_сервера_запрещает_запуск(self) -> None:
        result = audit_page("https://example.com/", GOOD_PAGE, status_code=503)

        assert result.can_launch is False
        # Балл не должен спорить с вердиктом: неработающий сайт не может
        # выглядеть почти готовым только потому, что содержимое хорошее.
        assert result.score <= 40

    def test_страница_не_найдена_запрещает_запуск(self) -> None:
        result = audit_page("https://example.com/", GOOD_PAGE, status_code=404)
        assert result.can_launch is False


class TestЗамечания:
    def test_нет_мобильной_вёрстки(self) -> None:
        html = GOOD_PAGE.replace(
            '<meta name="viewport" content="width=device-width, initial-scale=1">', ""
        )
        result = audit_page("https://example.com/", html)

        assert result.can_launch is True  # это замечание, а не запрет
        assert result.verdict is Verdict.READY_WITH_WARNINGS
        assert any("мобильн" in i.title.lower() for i in result.issues)

    def test_нет_цен_это_рекомендация(self) -> None:
        html = GOOD_PAGE.replace("от 3 500 ₽", "по договорённости")
        result = audit_page("https://example.com/", html)

        prices = [i for i in result.issues if "цен" in i.title.lower()]
        assert prices and prices[0].severity is Severity.RECOMMENDATION
        assert result.can_launch is True

    def test_телефон_без_формы_не_блокирует(self) -> None:
        """Связаться можно — значит трафик не пропадёт впустую."""
        html = GOOD_PAGE.replace(
            '<form action="/lead"><input name="phone"><button>Оставить заявку</button></form>', ""
        )
        result = audit_page("https://example.com/", html)

        assert result.can_launch is True
        assert any("форм" in i.title.lower() for i in result.issues)


class TestОценка:
    def test_у_каждой_находки_есть_действие(self) -> None:
        """Находка без понятного действия бесполезна пользователю."""
        result = audit_page("https://example.com/", BARE_PAGE)
        for issue in result.issues:
            assert issue.action, f"нет действия у находки: {issue.title}"
            assert len(issue.action) > 20

    def test_балл_в_допустимых_пределах(self) -> None:
        for html, status in ((GOOD_PAGE, 200), (BARE_PAGE, 200), (BARE_PAGE, 500)):
            result = audit_page("https://example.com/", html, status_code=status)
            assert 0 <= result.score <= 100

    def test_пустой_сайт_набирает_мало(self) -> None:
        result = audit_page("https://example.com/", BARE_PAGE)
        assert result.score < 40

    def test_все_категории_присутствуют(self) -> None:
        result = audit_page("https://example.com/", GOOD_PAGE)
        assert {c.category for c in result.categories} == set(Category)


class TestПерсональныеДанные:
    """Проверка, которая отвечает не за конверсию, а за допуск к показам."""

    def test_форма_без_политики_запрещает_запуск(self) -> None:
        html = GOOD_PAGE.replace('<a href="/privacy">Политика конфиденциальности</a>', "")
        result = audit_page("https://example.com/", html)

        blocking = [i for i in result.issues if i.severity is Severity.CRITICAL]
        assert any("политик" in i.title.lower() for i in blocking)
        assert result.can_launch is False

    def test_страница_без_формы_политику_не_требует(self) -> None:
        """Ничего не собираем — нечего и обосновывать."""
        html = GOOD_PAGE.replace(
            '<form action="/lead"><input name="phone"><button>Оставить заявку</button></form>', ""
        ).replace('<a href="/privacy">Политика конфиденциальности</a>', "")
        result = audit_page("https://example.com/", html)

        assert not any("политик" in i.title.lower() for i in result.issues)

    def test_согласие_в_тексте_формы_засчитывается(self) -> None:
        """Не у всех политика вынесена ссылкой — у многих это галочка согласия."""
        html = GOOD_PAGE.replace(
            '<a href="/privacy">Политика конфиденциальности</a>',
            "<label><input type=checkbox> Согласен на обработку персональных данных</label>",
        )
        result = audit_page("https://example.com/", html)

        assert not any("политик" in i.title.lower() for i in result.issues)


class TestСкорость:
    def test_быстрый_ответ_замечаний_не_даёт(self) -> None:
        result = audit_page("https://example.com/", GOOD_PAGE, elapsed_ms=800)

        assert not any("долго" in i.title or "медленно" in i.title for i in result.issues)

    def test_медленный_ответ_это_рекомендация(self) -> None:
        result = audit_page("https://example.com/", GOOD_PAGE, elapsed_ms=4000)

        slow = [i for i in result.issues if "медленно" in i.title]
        assert slow and slow[0].severity is Severity.RECOMMENDATION
        # Медленный сайт работает, просто хуже. Запрещать запуск за это нельзя.
        assert result.can_launch is True

    def test_очень_медленный_ответ_это_предупреждение(self) -> None:
        result = audit_page("https://example.com/", GOOD_PAGE, elapsed_ms=12000)

        slow = [i for i in result.issues if "очень долго" in i.title]
        assert slow and slow[0].severity is Severity.WARNING

    def test_без_измерения_проверки_нет(self) -> None:
        """Неизвестное время — не то же самое, что хорошее время."""
        result = audit_page("https://example.com/", GOOD_PAGE)

        assert not any("Открывается за" in f for c in result.categories for f in c.findings)


class TestУдобствоЗаявки:
    def test_длинная_форма_это_рекомендация(self) -> None:
        fields = "".join(f'<input name="f{i}">' for i in range(8))
        html = GOOD_PAGE.replace('<input name="phone">', fields)
        result = audit_page("https://example.com/", html)

        long_form = [i for i in result.issues if "полей" in i.title]
        assert long_form and long_form[0].severity is Severity.RECOMMENDATION

    def test_скрытые_поля_не_считаются(self) -> None:
        """Иначе форма с шестью utm-метками выглядела бы неудобной для человека."""
        hidden = "".join(f'<input type="hidden" name="utm{i}">' for i in range(8))
        html = GOOD_PAGE.replace('<input name="phone">', f'<input name="phone">{hidden}')
        result = audit_page("https://example.com/", html)

        assert not any("полей" in i.title for i in result.issues)

    def test_телефон_без_ссылки_это_рекомендация(self) -> None:
        result = audit_page("https://example.com/", GOOD_PAGE)

        clickable = [i for i in result.issues if "нажать" in i.title]
        assert clickable and clickable[0].severity is Severity.RECOMMENDATION

    def test_телефон_ссылкой_замечаний_не_даёт(self) -> None:
        html = GOOD_PAGE.replace(
            "Телефон: +7 (900) 123-45-67",
            'Телефон: <a href="tel:+79001234567">+7 (900) 123-45-67</a>',
        )
        result = audit_page("https://example.com/", html)

        assert not any("нажать" in i.title for i in result.issues)
