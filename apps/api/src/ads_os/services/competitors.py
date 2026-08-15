"""Сравнение с конкурентами (v0.3 §16).

Модуль отвечает на один вопрос: чего нет на вашей посадочной странице из того,
что есть у конкурентов. Не «кто лучше» — такую оценку нельзя вывести из
разметки страницы, и притворяться, что можно, значит выдавать домысел за факт.

Никакой модели здесь тоже нет. Всё, что сравнивается, определяется однозначно:
есть форма или нет, указаны цены или нет, установлен счётчик или нет. Признаки
берутся тем же разбором, что и для собственного сайта, — иначе одно и то же
свойство определялось бы у себя и у конкурента по разным правилам.

Чего модуль намеренно не делает: не пытается определить объём трафика, бюджеты
или позиции конкурента. Эти данные с публичной страницы не читаются, а
правдоподобная цифра на их месте опаснее пробела.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .audit import PageSignals


class FeatureKey(StrEnum):
    """Сравнимые свойства страницы.

    Список закрытый и короткий: сравнение по тридцати признакам перестаёт быть
    сравнением и становится таблицей, которую никто не читает.
    """

    PRICES = "prices"
    FORM = "form"
    PHONE = "phone"
    MESSENGERS = "messengers"
    CTA = "cta"
    TRUST = "trust"
    PROMO = "promo"
    MOBILE = "mobile"
    ANALYTICS = "analytics"


#: Подписи и пояснения. Пояснение отвечает на вопрос «и что с того»: признак
#: без последствий для рекламы в этом списке не нужен.
FEATURE_LABELS: dict[FeatureKey, tuple[str, str]] = {
    FeatureKey.PRICES: ("Цены на странице", "Без цены посетитель уходит сравнивать"),
    FeatureKey.FORM: ("Форма заявки", "Без неё нельзя измерять конверсии"),
    FeatureKey.PHONE: ("Телефон", "Часть аудитории звонит, а не пишет"),
    FeatureKey.MESSENGERS: ("Мессенджеры", "Telegram, WhatsApp или MAX для быстрой связи"),
    FeatureKey.CTA: ("Призыв к действию", "Заметная кнопка вместо «свяжитесь с нами»"),
    FeatureKey.TRUST: ("Отзывы и гарантии", "Прямо влияют на конверсию"),
    FeatureKey.PROMO: ("Акции и условия", "Повод обратиться сейчас, а не потом"),
    FeatureKey.MOBILE: ("Мобильная вёрстка", "Больше половины трафика — телефоны"),
    FeatureKey.ANALYTICS: ("Счётчик Метрики", "Без него реклама неуправляема"),
}


def extract_features(signals: PageSignals) -> dict[FeatureKey, bool]:
    """Приводит признаки страницы к набору «есть / нет»."""
    return {
        FeatureKey.PRICES: signals.prices > 0,
        FeatureKey.FORM: signals.forms > 0,
        FeatureKey.PHONE: signals.phones > 0,
        FeatureKey.MESSENGERS: bool(signals.messengers),
        FeatureKey.CTA: signals.cta_buttons > 0,
        FeatureKey.TRUST: bool(signals.trust_words),
        FeatureKey.PROMO: bool(signals.offer_words),
        FeatureKey.MOBILE: signals.has_viewport,
        FeatureKey.ANALYTICS: signals.has_analytics,
    }


@dataclass(frozen=True, slots=True)
class Participant:
    """Участник сравнения: свой сайт или сайт конкурента."""

    url: str
    title: str
    features: dict[FeatureKey, bool]


@dataclass(frozen=True, slots=True)
class FeatureRow:
    """Строка таблицы сравнения по одному признаку."""

    key: FeatureKey
    label: str
    why: str
    mine: bool
    #: У скольких конкурентов признак есть.
    rivals_with: int
    rivals_total: int

    @property
    def is_gap(self) -> bool:
        """Признак есть у большинства конкурентов, а у нас нет.

        Порог именно большинство, а не «хотя бы у одного»: один конкурент с
        необычным решением — это не пробел, а разница подходов.
        """
        return not self.mine and self.rivals_total > 0 and self.rivals_with * 2 > self.rivals_total

    @property
    def is_advantage(self) -> bool:
        """Есть у нас и меньше чем у половины конкурентов."""
        return self.mine and self.rivals_total > 0 and self.rivals_with * 2 < self.rivals_total


@dataclass(frozen=True, slots=True)
class Comparison:
    rows: tuple[FeatureRow, ...]
    gaps: tuple[FeatureRow, ...]
    advantages: tuple[FeatureRow, ...]
    #: Одно предложение с выводом. Пусто, когда сравнивать не с чем.
    summary: str | None


def compare(mine: Participant, rivals: tuple[Participant, ...]) -> Comparison:
    """Строит таблицу сравнения и выделяет пробелы."""
    rows: list[FeatureRow] = []

    for key in FeatureKey:
        label, why = FEATURE_LABELS[key]
        rows.append(
            FeatureRow(
                key=key,
                label=label,
                why=why,
                mine=mine.features.get(key, False),
                rivals_with=sum(1 for r in rivals if r.features.get(key, False)),
                rivals_total=len(rivals),
            )
        )

    gaps = tuple(r for r in rows if r.is_gap)
    advantages = tuple(r for r in rows if r.is_advantage)

    return Comparison(
        rows=tuple(rows),
        gaps=gaps,
        advantages=advantages,
        summary=_summary(gaps, advantages, len(rivals)),
    )


def _summary(
    gaps: tuple[FeatureRow, ...], advantages: tuple[FeatureRow, ...], rivals: int
) -> str | None:
    if rivals == 0:
        return None

    if not gaps:
        base = "По сравниваемым признакам вы не уступаете конкурентам"
        if advantages:
            return f"{base}. Ваше отличие: {_enumerate(advantages)}"
        return base

    return f"Чего нет у вас, но есть у большинства конкурентов: {_enumerate(gaps)}"


def _enumerate(rows: tuple[FeatureRow, ...]) -> str:
    """Перечисление подписей строчными буквами, до трёх штук."""
    labels = [r.label.lower() for r in rows[:3]]
    tail = "" if len(rows) <= 3 else f" и ещё {len(rows) - 3}"
    return ", ".join(labels) + tail
