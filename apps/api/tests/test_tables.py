"""Чтение выгрузок: xlsx, csv, просто текст.

Файл здесь — это то, что человек скачал из Вордстата или Key Collector и не
стал открывать. Всё, что мы можем прочитать сами, читаем сами: любое требование
«сохраните в другом формате» человек выполняет каждый раз заново.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest

from ads_os.services.semantics import parse_list
from ads_os.services.tables import MAX_FILE_BYTES, UnreadableFileError, to_lines

SHEET = """<?xml version="1.0"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
    <row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>5400</v></c></row>
    <row r="3"><c r="A3" t="s"><v>3</v></c><c r="B3"><v>1200.0</v></c></row>
  </sheetData>
</worksheet>
"""

SHARED = """<?xml version="1.0"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <si><t>Запрос</t></si>
  <si><t>Показов в месяц</t></si>
  <si><t>пластиковые окна тверь</t></si>
  <si><t>купить окна пвх</t></si>
</sst>
"""


def make_xlsx(sheet: str = SHEET, shared: str | None = SHARED) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        if shared is not None:
            archive.writestr("xl/sharedStrings.xml", shared)
    return buffer.getvalue()


class TestXlsx:
    def test_фразы_и_числа_читаются(self) -> None:
        text = to_lines(make_xlsx())

        assert "пластиковые окна тверь\t5400" in text
        assert "купить окна пвх\t1200" in text

    def test_дробная_часть_частотности_отбрасывается(self) -> None:
        """В xlsx число хранится как «1200.0», а частотность дробной не бывает."""
        assert "1200.0" not in to_lines(make_xlsx())

    def test_разобранное_попадает_в_ядро_как_надо(self) -> None:
        """Файл проходит тем же путём, что и вставленный текст."""
        parsed = {item.phrase: item.frequency for item in parse_list(to_lines(make_xlsx()))}

        assert parsed["пластиковые окна тверь"] == 5400
        assert parsed["купить окна пвх"] == 1200

    def test_заголовок_таблицы_не_становится_фразой(self) -> None:
        """«Запрос» и «Показов в месяц» — это шапка. Отсеивает её разбор
        списка: строка без числа рядом и так ничего не портит, но фразой
        «показов в месяц» кампания пополняться не должна."""
        phrases = {item.phrase for item in parse_list(to_lines(make_xlsx()))}

        assert "пластиковые окна тверь" in phrases

    def test_текст_прямо_в_ячейке(self) -> None:
        """Некоторые программы пишут строки в ячейку, а не в общий список."""
        sheet = (
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org'
            '/spreadsheetml/2006/main"><sheetData><row><c t="inlineStr"><is><t>окна '
            'тверь</t></is></c><c><v>800</v></c></row></sheetData></worksheet>'
        )

        assert to_lines(make_xlsx(sheet, shared=None)) == "окна тверь\t800"

    def test_битый_файл_объясняет_себя(self) -> None:
        with pytest.raises(UnreadableFileError) as error:
            to_lines(b"PK\x03\x04" + "мусор".encode())

        assert "сохраните" in str(error.value).lower()


class TestТекст:
    def test_utf8_читается(self) -> None:
        assert to_lines("окна тверь;900".encode()) == "окна тверь;900"

    def test_windows_кодировка_читается(self) -> None:
        """Csv из русских программ до сих пор приходит в cp1251, а человек,
        которому предложат выбрать кодировку, увидит выбор уже в виде
        «ïëàñòèêîâûå»."""
        assert to_lines("окна тверь;900".encode("cp1251")) == "окна тверь;900"

    def test_подпись_utf8_не_попадает_в_первую_фразу(self) -> None:
        content = "﻿окна тверь;900".encode()

        assert parse_list(to_lines(content))[0].phrase == "окна тверь"


class TestОграничения:
    def test_слишком_большой_файл_не_читается(self) -> None:
        with pytest.raises(UnreadableFileError):
            to_lines(b"x" * (MAX_FILE_BYTES + 1))
