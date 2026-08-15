"""Выгрузка кампании файлом.

Смысл модуля в том, что он работает без доступа к API Директа. Специалист
получает готовую структуру — группы, фразы, объявления, минус-слова — одним
файлом и заводит кампанию через Коммандер или руками. Это единственный способ
довести работу до реального запуска, пока доступ к API не получен, и он же
остаётся полезным после: не все кампании заводят через API.

Формат — CSV с точкой с запятой и меткой кодировки в начале. Оба решения
приняты ради Excel: без метки он показывает русский текст крякозябрами, а с
запятой в качестве разделителя разносит по столбцам числа вида «12 900,00».
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

#: Метка кодировки для Excel. Без неё русский текст открывается нечитаемым, и
#: человек решает, что выгрузка сломана.
BOM = "﻿"

COLUMNS = (
    "Кампания",
    "Группа",
    "Ключевая фраза",
    "Заголовок 1",
    "Заголовок 2",
    "Текст",
    "Ссылка",
    "Отображаемая ссылка",
    "Уточнения",
    "Минус-слова кампании",
    "Замечания",
)


@dataclass(frozen=True, slots=True)
class ExportRow:
    """Одна строка выгрузки: фраза вместе с объявлением своей группы."""

    campaign: str
    group: str
    phrase: str
    title: str
    title_2: str
    text: str
    url: str
    display_path: str
    callouts: str
    minus_words: str
    warnings: str


def to_csv(rows: list[ExportRow]) -> str:
    """Собирает CSV.

    Строка на каждую фразу, а не на группу: именно так устроены таблицы
    Коммандера и именно так их проще править руками. Данные объявления
    повторяются в каждой строке группы — это избыточность, но она делает файл
    пригодным для сортировки и фильтрации, а без неё половина строк оказалась бы
    пустой.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")

    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow(
            [
                row.campaign,
                row.group,
                row.phrase,
                row.title,
                row.title_2,
                row.text,
                row.url,
                row.display_path,
                row.callouts,
                row.minus_words,
                row.warnings,
            ]
        )

    return BOM + buffer.getvalue()


def file_name(project_name: str) -> str:
    """Имя файла из названия проекта.

    Небезопасные для файловой системы символы заменяются, а не удаляются:
    «Окна/Двери» иначе превратилось бы в «ОкнаДвери» — другое название.
    """
    safe = "".join("-" if ch in '\\/:*?"<>|' else ch for ch in project_name).strip()
    return f"кампания-{safe or 'проект'}.csv"
