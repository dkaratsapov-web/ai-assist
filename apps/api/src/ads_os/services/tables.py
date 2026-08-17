"""Чтение выгрузок: xlsx и текстовые таблицы.

Вордстат отдаёт файл в xlsx, Key Collector — в xlsx или csv, а кто-то просто
копирует колонку в блокнот. Требовать от человека привести файл к одному виду —
значит переложить на него работу, которая занимает минуту у программы и десять
у человека, причём каждый раз.

Разбор намеренно грубый: из таблицы нужны два столбца — фраза и число рядом.
Всё остальное в выгрузках Вордстата не несёт смысла для нас, а угадывать
назначение колонок по заголовкам ненадёжно: они меняются от версии к версии и
переводятся по-разному.

xlsx читается стандартной библиотекой. Файл этого формата — обычный zip с
xml внутри, и ради двух столбцов тянуть в проект библиотеку работы с таблицами
незачем: она принесёт свои зависимости, свои уязвимости и свои обновления.
"""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree

#: Предел на файл. Двадцать тысяч фраз — это около мегабайта xlsx; всё, что
#: заметно больше, либо не выгрузка, либо её всё равно не обработать за раз.
MAX_FILE_BYTES = 10 * 1024 * 1024

#: Пространство имён таблиц Open XML. Одно на все файлы этого формата.
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

_ZIP_MAGIC = b"PK\x03\x04"


class UnreadableFileError(ValueError):
    """Файл не удалось прочитать как таблицу."""


def looks_like_xlsx(content: bytes) -> bool:
    return content[:4] == _ZIP_MAGIC


def to_lines(content: bytes, *, filename: str = "") -> str:
    """Приводит содержимое файла к строкам «фраза<таб>частотность».

    Дальше их разбирает тот же код, что и вставленный руками список: у выгрузки
    и у вставки не должно быть двух разных путей, иначе они разойдутся, и
    расхождение обнаружится на чужом файле.
    """
    if len(content) > MAX_FILE_BYTES:
        raise UnreadableFileError("Файл слишком большой")

    if looks_like_xlsx(content):
        return _from_xlsx(content)

    return _from_text(content, filename=filename)


def _from_text(content: bytes, *, filename: str = "") -> str:
    """Текстовая выгрузка: csv, tsv, просто колонка.

    Кодировка угадывается, а не спрашивается. Windows-1251 в csv из русских
    программ встречается до сих пор, и человек, которому предложат выбрать
    кодировку, выберет неправильно — а увидит это уже в виде «ïëàñòèêîâûå».
    """
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise UnreadableFileError(
        f"Не удалось прочитать файл{f' «{filename}»' if filename else ''}: "
        "сохраните его как CSV в кодировке UTF-8"
    )


def _from_xlsx(content: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            shared = _shared_strings(archive)
            sheet = _first_sheet(archive)
            rows = _rows(archive.read(sheet), shared)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as error:
        raise UnreadableFileError(
            "Файл повреждён или это не таблица. Откройте его и сохраните заново "
            "в формате xlsx или csv."
        ) from error

    return "\n".join("\t".join(cells) for cells in rows if cells)


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    """Общая таблица строк.

    В xlsx текст ячеек хранится не в самой ячейке, а отдельным списком — ячейка
    ссылается на него номером. Без этого списка вместо фраз получаются индексы.
    """
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.itertext()) for node in root.findall(f"{_NS}si")]


def _first_sheet(archive: zipfile.ZipFile) -> str:
    names = [name for name in archive.namelist() if name.startswith("xl/worksheets/sheet")]
    if not names:
        raise KeyError("в файле нет ни одного листа")
    return sorted(names)[0]


def _rows(sheet: bytes, shared: list[str]) -> list[list[str]]:
    root = ElementTree.fromstring(sheet)
    result: list[list[str]] = []

    for row in root.iter(f"{_NS}row"):
        cells: list[str] = []
        for cell in row.iter(f"{_NS}c"):
            cells.append(_value(cell, shared))
        # Ведущие пустые ячейки убирать нельзя — сдвинется соответствие
        # столбцов, — а хвостовые не значат ничего.
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            result.append(cells)

    return result


def _value(cell: ElementTree.Element, shared: list[str]) -> str:
    kind = cell.get("t")

    if kind == "s":
        node = cell.find(f"{_NS}v")
        index = int(node.text or 0) if node is not None and node.text else -1
        return shared[index] if 0 <= index < len(shared) else ""

    if kind == "inlineStr":
        node = cell.find(f"{_NS}is")
        return "".join(node.itertext()) if node is not None else ""

    node = cell.find(f"{_NS}v")
    text = (node.text or "") if node is not None else ""
    # Числа в xlsx хранятся как есть: «1234» или «1234.0». Дробная часть у
    # частотности не бывает осмысленной, а мешает разбору.
    return re.sub(r"\.0+$", "", text.strip())
