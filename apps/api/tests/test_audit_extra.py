"""Проверки, добавленные после первого живого проекта.

Каждая здесь появилась не ради числа проверок, а потому что отвечает на
вопрос, который специалист всё равно задаёт руками: тот ли это адрес, почему
ломается вёрстка, почему Директ не видит конверсий, почему клиент не звонит.
"""

from __future__ import annotations

from ads_os.services.audit import (
    HEAVY_PAGE_BYTES,
    THIN_CONTENT_LIMIT,
    IssueKey,
    Severity,
    audit_page,
    collect_signals,
)

from .test_audit import GOOD_PAGE


def keys(html: str, url: str = "https://example.com/") -> set[IssueKey]:
    return {i.key for i in audit_page(url, html).issues}


class TestТехника:
    def test_закрытая_от_индексации_страница_замечается(self) -> None:
        """Почти всегда это значит, что дали адрес тестовой версии."""
        html = GOOD_PAGE.replace("<head>", '<head><meta name="robots" content="noindex">')

        assert IssueKey.NOINDEX in keys(html)

    def test_индексация_не_блокирует_запуск(self) -> None:
        """Рекламе noindex не мешает. Это повод проверить адрес, а не запрет."""
        html = GOOD_PAGE.replace("<head>", '<head><meta name="robots" content="noindex">')

        assert audit_page("https://example.com/", html).can_launch is True

    def test_ресурсы_по_http_на_защищённой_странице(self) -> None:
        html = GOOD_PAGE.replace("</body>", '<img src="http://example.com/logo.png"></body>')

        assert IssueKey.MIXED_CONTENT in keys(html)

    def test_на_незащищённой_странице_смешанного_содержимого_нет(self) -> None:
        """Там своя, более важная находка — сам протокол."""
        html = GOOD_PAGE.replace("</body>", '<img src="http://example.com/logo.png"></body>')

        assert IssueKey.MIXED_CONTENT not in keys(html, "http://example.com/")

    def test_обычная_ссылка_по_http_не_считается(self) -> None:
        """Браузер блокирует подключаемые файлы, а не переходы по ссылкам."""
        html = GOOD_PAGE.replace("</body>", '<a href="http://partner.ru">Партнёр</a></body>')

        assert IssueKey.MIXED_CONTENT not in keys(html)

    def test_тяжёлая_страница(self) -> None:
        html = GOOD_PAGE.replace("</body>", "<p>" + "текст " * 300_000 + "</p></body>")

        assert len(html.encode()) > HEAVY_PAGE_BYTES
        assert IssueKey.HEAVY_PAGE in keys(html)

    def test_нет_описания(self) -> None:
        html = GOOD_PAGE.replace(
            '<meta name="description" content="Ремонт iPhone за час с гарантией 12 месяцев">', ""
        )

        assert IssueKey.NO_DESCRIPTION in keys(html)

    def test_нет_языка(self) -> None:
        html = GOOD_PAGE.replace('<html lang="ru">', "<html>")

        assert IssueKey.NO_LANG in keys(html)


class TestПредложение:
    def test_страница_почти_без_текста(self) -> None:
        html = (
            '<html lang="ru"><head><title>Окна в Твери</title></head><body>'
            "<h1>Окна</h1><p>Звоните: +7 900 123-45-67</p>"
            '<form><input name="phone"></form></body></html>'
        )

        assert collect_signals(html).text_length < THIN_CONTENT_LIMIT
        assert IssueKey.THIN_CONTENT in keys(html)

    def test_каркас_на_скриптах_не_считается_тонким(self) -> None:
        """Там мы не разглядели содержимое, а не убедились, что его нет.
        Обвинить сайт в пустоте, которую сами не увидели, значит соврать."""
        html = (
            "<html lang='ru'><head><title>Окна</title></head><body><div id='root'></div>"
            "<script>a=1</script><script>b=2</script><script>c=3</script>"
            "</body></html>"
        )

        assert IssueKey.THIN_CONTENT not in keys(html)

    def test_бессмысленный_заголовок_вкладки(self) -> None:
        html = GOOD_PAGE.replace("Ремонт техники Apple в Твери", "Главная")

        assert IssueKey.GENERIC_TITLE in keys(html)

    def test_осмысленный_заголовок_замечаний_не_даёт(self) -> None:
        assert IssueKey.GENERIC_TITLE not in keys(GOOD_PAGE)


class TestЗаявка:
    def test_нет_мессенджеров(self) -> None:
        html = GOOD_PAGE.replace('<a href="https://t.me/example">Написать в Telegram</a>', "")

        assert IssueKey.NO_MESSENGERS in keys(html)

    def test_много_разных_телефонов(self) -> None:
        html = GOOD_PAGE.replace(
            "</body>", "<p>+7 (900) 111-11-11</p><p>+7 (900) 222-22-22</p></body>"
        )

        assert IssueKey.MANY_PHONES in keys(html)

    def test_один_телефон_замечаний_не_даёт(self) -> None:
        assert IssueKey.MANY_PHONES not in keys(GOOD_PAGE)

    def test_форма_без_галочки_согласия(self) -> None:
        """Ссылка на политику в подвале не заменяет галочку: политика
        объясняет, а галочка фиксирует согласие."""
        html = GOOD_PAGE.replace('<input type="checkbox" name="consent">', "")

        assert IssueKey.FORM_WITHOUT_CONSENT in keys(html)

    def test_без_формы_согласие_не_требуется(self) -> None:
        html = GOOD_PAGE.replace('<input name="phone">', "").replace(
            '<input type="checkbox" name="consent">', ""
        )
        html = html.replace("<form action=\"/lead\">", "<div>").replace("</form>", "</div>")

        assert IssueKey.FORM_WITHOUT_CONSENT not in keys(html)


class TestДоверие:
    def test_нет_реквизитов(self) -> None:
        html = GOOD_PAGE.replace("ООО «Ремонт», ИНН 6950123456", "Мы работаем честно")

        assert IssueKey.NO_COMPANY_DETAILS in keys(html)

    def test_реквизиты_с_номером_засчитываются(self) -> None:
        assert IssueKey.NO_COMPANY_DETAILS not in keys(GOOD_PAGE)

    def test_слово_инн_без_номера_не_считается_реквизитами(self) -> None:
        """Иначе «инновации» и «инновационный» сойдут за ИНН."""
        html = GOOD_PAGE.replace("ООО «Ремонт», ИНН 6950123456", "Инновационный подход")

        assert IssueKey.NO_COMPANY_DETAILS in keys(html)

    def test_нет_адреса(self) -> None:
        html = GOOD_PAGE.replace("Адрес: г. Тверь, ул. Советская, д. 10, офис 3", "Работаем везде")

        assert IssueKey.NO_ADDRESS in keys(html)

    def test_нет_соцсетей(self) -> None:
        html = GOOD_PAGE.replace(
            '<a href="https://vk.com/example">Мы во ВКонтакте</a>', ""
        ).replace('<a href="https://t.me/example">Написать в Telegram</a>', "")

        assert IssueKey.NO_SOCIAL in keys(html)

    def test_нет_отзывов(self) -> None:
        html = GOOD_PAGE.replace("Более 2000 отзывов, ", "")

        assert IssueKey.NO_REVIEWS in keys(html)


class TestАналитика:
    def test_два_счётчика_метрики(self) -> None:
        """Два счётчика делят визиты, и обе картины оказываются неполными — а
        решения принимаются по каждой как по целой."""
        html = GOOD_PAGE.replace(
            "<script>ym(12345678, 'init', {});</script>",
            "<script>ym(12345678, 'init', {});ym(87654321, 'init', {});</script>",
        )

        assert IssueKey.MANY_METRICA_COUNTERS in keys(html)

    def test_один_счётчик_замечаний_не_даёт(self) -> None:
        assert IssueKey.MANY_METRICA_COUNTERS not in keys(GOOD_PAGE)

    def test_чужая_аналитика_не_заменяет_метрику(self) -> None:
        """Человек уверен, что аналитика стоит, и замечание про её отсутствие
        выглядит ошибкой проверки. Надо объяснить, почему не считается."""
        html = GOOD_PAGE.replace(
            "<script>ym(12345678, 'init', {});</script>",
            '<script src="https://www.googletagmanager.com/gtag/js"></script>',
        )
        found = keys(html)

        assert IssueKey.NO_METRICA in found
        assert IssueKey.FOREIGN_ANALYTICS_ONLY in found

    def test_без_всякой_аналитики_отдельной_находки_нет(self) -> None:
        html = GOOD_PAGE.replace("<script>ym(12345678, 'init', {});</script>", "")
        found = keys(html)

        assert IssueKey.NO_METRICA in found
        assert IssueKey.FOREIGN_ANALYTICS_ONLY not in found


class TestОбщее:
    def test_у_всех_новых_находок_есть_действие(self) -> None:
        """Находка без понятного действия бесполезна."""
        html = "<html><body><p>Пусто</p></body></html>"

        for issue in audit_page("http://example.com/", html).issues:
            assert len(issue.action) > 20, issue.title

    def test_эталонная_страница_остаётся_чистой(self) -> None:
        """Семнадцать новых проверок не должны портить хороший сайт: иначе
        безупречных страниц не бывает, и балл перестаёт что-либо значить."""
        result = audit_page("https://example.com/", GOOD_PAGE)

        assert result.issues == ()
        assert result.score >= 90

    def test_новые_проверки_не_блокируют_запуск(self) -> None:
        """Блокировка — сильное средство. Из добавленного её заслуживает только
        то, из-за чего реклама физически не пойдёт, а такого здесь нет."""
        html = "<html><body><p>Пусто</p></body></html>"
        blocking = {i.key for i in audit_page("https://example.com/", html).blocking_issues}

        assert IssueKey.NOINDEX not in blocking
        assert IssueKey.NO_ADDRESS not in blocking
        assert IssueKey.MANY_PHONES not in blocking
        assert Severity.CRITICAL not in {
            i.severity
            for i in audit_page("https://example.com/", html).issues
            if i.key
            in {
                IssueKey.NO_DESCRIPTION,
                IssueKey.NO_LANG,
                IssueKey.NO_SOCIAL,
                IssueKey.NO_REVIEWS,
                IssueKey.HEAVY_PAGE,
            }
        }
