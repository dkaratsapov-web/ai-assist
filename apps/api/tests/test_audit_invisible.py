"""Невидимое содержимое страницы не считается её текстом.

Первый живой проект вытащил в объявление фрагмент
«__DATA__ = {"current_text":"57 890 ₽"}» — кусок JSON из тега script. Разбор
брал текст страницы целиком, вместе со скриптами и стилями, и всё, что там
лежало, участвовало в проверках наравне с видимым текстом.

Последствия расходились дальше объявлений: цены считались по разметке, а не по
витрине, а страница с большим скриптом переставала опознаваться как собираемая
в браузере — «текста» на ней оказывалось много.
"""

from __future__ import annotations

from ads_os.services.audit import collect_signals, looks_js_rendered

WITH_SCRIPT = """
<html><body>
  <h1>Купить айфон в Твери</h1>
  <p>Гарантия низкой цены. Гарантия 2 года.</p>
  <div class="price">57 890 ₽</div>
  <script>window.__DATA__ = {"current_text":"57 890 ₽","old":"113 890 ₽"};</script>
  <style>.price { color: red; content: "отзывы"; }</style>
</body></html>
"""


class TestСкриптыНеТекст:
    def test_json_не_попадает_в_фрагменты_предложения(self) -> None:
        """Ровно то, что уехало в живое объявление."""
        points = collect_signals(WITH_SCRIPT).selling_points

        assert not any("__DATA__" in p or "{" in p for p in points)

    def test_видимые_фрагменты_остаются(self) -> None:
        points = collect_signals(WITH_SCRIPT).selling_points

        assert "Гарантия низкой цены" in points
        assert "Гарантия 2 года" in points

    def test_цены_считаются_только_видимые(self) -> None:
        """В JSON цена встречается дважды, на витрине — один раз."""
        assert collect_signals(WITH_SCRIPT).prices == 1

    def test_текст_стилей_не_учитывается(self) -> None:
        """Слово «отзыв» есть только внутри CSS. Засчитать его за признак
        доверия — значит поставить сайту балл за то, чего посетитель не видит.

        «Гарантия» при этом остаётся: она в видимом тексте, и это правильно.
        """
        trust = collect_signals(WITH_SCRIPT).trust_words

        assert "отзыв" not in trust
        assert "гарант" in trust

    def test_длина_текста_без_скриптов(self) -> None:
        signals = collect_signals(WITH_SCRIPT)

        assert signals.text_length < 120

    def test_скрипты_всё_ещё_считаются(self) -> None:
        """Их количество — признак страницы, собираемой в браузере. Вырезание
        содержимого не должно стирать сам факт, что скрипты есть."""
        assert collect_signals(WITH_SCRIPT).scripts == 1

    def test_пустой_каркас_с_большим_скриптом_опознаётся(self) -> None:
        """Раньше длинный скрипт добавлял «текста», и страница выглядела
        полноценной."""
        html = (
            "<html><body><div id='root'></div>"
            "<script>" + "var x = 'заполнитель';" * 200 + "</script>"
            "</body></html>"
        )

        assert looks_js_rendered(collect_signals(html)) is True

    def test_счётчик_метрики_находится_несмотря_на_вырезание(self) -> None:
        """Счётчик живёт как раз в скрипте: он ищется по исходному коду."""
        html = "<html><body><script>ym(12345678,'init',{});</script></body></html>"

        assert collect_signals(html).metrica_counter == "12345678"
