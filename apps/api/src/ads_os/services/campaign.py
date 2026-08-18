"""Структура кампании и проверки перед выгрузкой.

Один модуль на две задачи, и это не экономия, а необходимость. Экран проверки
и файл для Коммандера обязаны показывать одно и то же: если структура на экране
считается одним кодом, а в файле — другим, человек проверит одно, а заведёт
другое. Обнаружится это в Директе, где правки стоят дороже всего.

До появления этого модуля так и было: выгрузка пересобирала группы заново
расчётом, не глядя на то, как их разложил человек. Все переносы и
переименования в файл не попадали.

Здесь же живут проверки перед выгрузкой. Смысл у них один: **вопросы должны
задаваться до Коммандера, а не после запуска.** Группа из одной фразы, фраза
без частотности, кампания без единого минус-слова — всё это не ошибки, при
которых нельзя работать, а места, где человек обычно хотел не этого.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class Phrase:
    phrase: str
    frequency: int | None = None


@dataclass(frozen=True, slots=True)
class Group:
    """Группа так, как она сейчас лежит в ядре."""

    name: str
    phrases: tuple[Phrase, ...] = field(default_factory=tuple)
    #: Группу собрал человек: расчёт её не трогает.
    manual: bool = False

    @property
    def total_frequency(self) -> int:
        return sum(item.frequency or 0 for item in self.phrases)


class Severity(StrEnum):
    """Насколько замечание мешает.

    `BLOCKING` — выгружать можно, но результат почти наверняка не тот, который
    ожидали. Запретить выгрузку было бы неверно: специалист может знать про
    свой случай больше, чем проверка.
    """

    BLOCKING = "blocking"
    WARNING = "warning"
    NOTE = "note"


@dataclass(frozen=True, slots=True)
class Check:
    """Одно замечание перед выгрузкой."""

    key: str
    severity: Severity
    title: str
    #: Что сделать. Замечание без действия — это упрёк, а не помощь.
    action: str
    #: Чего именно касается: названия групп или фразы. Без примеров человек не
    #: понимает, где искать, и замечание остаётся непрочитанным.
    examples: tuple[str, ...] = field(default_factory=tuple)
    count: int = 0


#: Директу нужен объём, чтобы автостратегия обучилась. Группа из одной фразы
#: его не даёт: показов мало, статистика не набирается, и стратегия работает
#: вслепую.
MIN_PHRASES_IN_GROUP = 2

#: Сверху ограничение другое. Объявление пишется под смысл группы, и чем
#: больше в ней фраз, тем дальше оно от каждой из них. Двадцать — тот предел,
#: после которого заголовок перестаёт совпадать с запросом.
MAX_PHRASES_IN_GROUP = 20

#: Сколько примеров показываем. Больше — это уже список, который надо
#: разбирать, а замечание должно читаться за секунду.
MAX_EXAMPLES = 5


def structure(
    rows: list[tuple[str, str | None, int | None, bool, bool]],
) -> tuple[list[Group], list[Phrase]]:
    """Собирает структуру кампании из фраз ядра.

    На вход — кортежи `(фраза, группа, частотность, ручная, нецелевая)`.
    Плоские кортежи вместо моделей нарочно: модуль не должен знать про базу,
    иначе его нельзя будет прогнать на выдуманных данных в тесте.

    Возвращает группы и отдельно фразы без группы. Второе — не пустяк: в
    кампанию они не уедут, и человек должен увидеть это до выгрузки, а не
    обнаружить недостачу в Директе.
    """
    groups: dict[str, list[Phrase]] = {}
    manual: dict[str, bool] = {}
    orphans: list[Phrase] = []

    for phrase, group, frequency, is_manual, irrelevant in rows:
        if irrelevant:
            continue

        item = Phrase(phrase=phrase, frequency=frequency)
        if not group:
            orphans.append(item)
            continue

        groups.setdefault(group, []).append(item)
        manual[group] = manual.get(group, False) or is_manual

    built = [
        Group(
            name=name,
            phrases=tuple(sorted(items, key=lambda p: (-(p.frequency or 0), p.phrase))),
            manual=manual.get(name, False),
        )
        for name, items in groups.items()
    ]
    built.sort(key=lambda group: -group.total_frequency)

    orphans.sort(key=lambda p: (-(p.frequency or 0), p.phrase))
    return built, orphans


def checks(
    groups: list[Group],
    orphans: list[Phrase],
    *,
    minus_words: int = 0,
    duplicates: tuple[tuple[str, ...], ...] = (),
    ad_warnings: tuple[str, ...] = (),
    has_landing: bool = True,
) -> list[Check]:
    """Что стоит поправить до Коммандера.

    Порядок — от того, что почти наверняка испортит запуск, к тому, что просто
    стоит знать. Ни одна из проверок выгрузку не запрещает: специалист может
    знать про свой случай больше, а запрет, который нельзя обойти, приводит к
    тому, что работу доделывают мимо системы.
    """
    found: list[Check] = []

    if not groups:
        found.append(
            Check(
                key="no_groups",
                severity=Severity.BLOCKING,
                title="Групп нет — выгружать нечего",
                action="Соберите фразы и разложите их по группам.",
            )
        )
        return found

    if orphans:
        found.append(
            Check(
                key="ungrouped",
                severity=Severity.BLOCKING,
                title=f"Фраз без группы: {len(orphans)}",
                action=(
                    "В кампанию они не уедут: объявление собирается по группе. "
                    "Перенесите их в таблице фраз или распустите ненужную группу."
                ),
                examples=tuple(item.phrase for item in orphans[:MAX_EXAMPLES]),
                count=len(orphans),
            )
        )

    thin = [group for group in groups if len(group.phrases) < MIN_PHRASES_IN_GROUP]
    if thin:
        found.append(
            Check(
                key="thin_groups",
                severity=Severity.WARNING,
                title=f"Групп из одной фразы: {len(thin)}",
                action=(
                    "Автостратегии нужен объём: по одной фразе статистика не "
                    "набирается, и ставки считаются вслепую. Объедините их с "
                    "соседними по смыслу."
                ),
                examples=tuple(group.name for group in thin[:MAX_EXAMPLES]),
                count=len(thin),
            )
        )

    fat = [group for group in groups if len(group.phrases) > MAX_PHRASES_IN_GROUP]
    if fat:
        found.append(
            Check(
                key="fat_groups",
                severity=Severity.WARNING,
                title=f"Слишком крупных групп: {len(fat)}",
                action=(
                    f"Больше {MAX_PHRASES_IN_GROUP} фраз в группе — объявление "
                    "перестаёт совпадать с запросом, и цена клика растёт. "
                    "Разделите по смыслу."
                ),
                examples=tuple(
                    f"{group.name} — {len(group.phrases)}" for group in fat[:MAX_EXAMPLES]
                ),
                count=len(fat),
            )
        )

    blind = [
        item.phrase for group in groups for item in group.phrases if item.frequency is None
    ]
    if blind:
        found.append(
            Check(
                key="no_frequency",
                severity=Severity.WARNING,
                title=f"Фраз без частотности: {len(blind)}",
                action=(
                    "По ним нельзя оценить охват и спланировать бюджет. "
                    "Соберите частотности или уберите эти фразы."
                ),
                examples=tuple(blind[:MAX_EXAMPLES]),
                count=len(blind),
            )
        )

    if duplicates:
        found.append(
            Check(
                key="duplicates",
                severity=Severity.WARNING,
                title=f"Одинаковых для Директа фраз: {len(duplicates)}",
                action=(
                    "Порядок слов Директ не различает: такие фразы конкурируют "
                    "между собой и поднимают цену клика. Оставьте по одной."
                ),
                examples=tuple(" = ".join(pair) for pair in duplicates[:MAX_EXAMPLES]),
                count=len(duplicates),
            )
        )

    if minus_words == 0:
        found.append(
            Check(
                key="no_minus_words",
                severity=Severity.WARNING,
                title="Минус-слов нет ни одного",
                action=(
                    "Без них кампания соберёт всё подряд: работу, «своими руками», "
                    "рефераты. Добавьте хотя бы стартовый набор."
                ),
            )
        )

    if not has_landing:
        found.append(
            Check(
                key="no_landing",
                severity=Severity.BLOCKING,
                title="У проекта не указан адрес сайта",
                action="Без него ссылки объявлений будут пустыми. Укажите адрес в проекте.",
            )
        )

    if ad_warnings:
        found.append(
            Check(
                key="ad_warnings",
                severity=Severity.NOTE,
                title=f"Замечаний к объявлениям: {len(ad_warnings)}",
                action=(
                    "Они не мешают выгрузке и попадут в файл отдельным столбцом, "
                    "но на модерации могут стоить времени."
                ),
                examples=tuple(ad_warnings[:MAX_EXAMPLES]),
                count=len(ad_warnings),
            )
        )

    return found


def can_export(found: list[Check]) -> bool:
    """Есть ли смысл выгружать прямо сейчас.

    Возвращает False только при блокирующих замечаниях, и даже тогда кнопка
    остаётся: это подсказка, а не запрет. Запрет, который нельзя обойти,
    приводит к тому, что работу доделывают мимо системы.
    """
    return not any(check.severity is Severity.BLOCKING for check in found)
