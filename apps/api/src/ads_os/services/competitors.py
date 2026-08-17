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

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .audit import PageSignals
from .offer import OfferFacts


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


# --- Предметное сравнение ----------------------------------------------------
#
# Таблица «есть / нет» отвечает на вопрос, который специалист не задаёт. К
# конкуренту он приходит не выяснять, есть ли у того телефон, а смотреть, чем
# тот берёт: какая цена, какой срок, что обещают бесплатно, какая гарантия.
# Ниже — сравнение именно по этому, с числами и дословными цитатами.


class OfferKey(StrEnum):
    """Условия, по которым посетитель на самом деле выбирает."""

    PRICE = "price"
    DEADLINE = "deadline"
    GUARANTEE = "guarantee"
    FREE = "free"
    PROMO = "promo"
    FORM = "form"
    MESSENGERS = "messengers"


OFFER_LABELS: dict[OfferKey, str] = {
    OfferKey.PRICE: "Цена",
    OfferKey.DEADLINE: "Срок",
    OfferKey.GUARANTEE: "Гарантия",
    OfferKey.FREE: "Что бесплатно",
    OfferKey.PROMO: "Акции и рассрочка",
    OfferKey.FORM: "Полей в форме",
    OfferKey.MESSENGERS: "Мессенджеры",
}


@dataclass(frozen=True, slots=True)
class RivalValue:
    """Значение условия у одного конкурента."""

    title: str
    url: str
    #: Как написано у него на странице. Пусто, если условия нет.
    value: str


@dataclass(frozen=True, slots=True)
class OfferRow:
    """Одно условие: что у нас, что у них и что это значит."""

    key: OfferKey
    label: str
    mine: str
    rivals: tuple[RivalValue, ...]
    #: Вывод одной фразой. Именно за ним человек сюда и приходит.
    verdict: str
    #: Стоит ли на это смотреть в первую очередь.
    is_gap: bool = False

    @property
    def rivals_with(self) -> int:
        return sum(1 for rival in self.rivals if rival.value)


@dataclass(frozen=True, slots=True)
class OfferComparison:
    rows: tuple[OfferRow, ...]
    gaps: tuple[OfferRow, ...]
    #: Есть ли вообще что сравнивать: у разобранных конкурентов бывает пусто.
    has_data: bool


def compare_offers(
    mine: OfferFacts, rivals: tuple[tuple[str, str, OfferFacts], ...]
) -> OfferComparison:
    """Сравнивает условия предложения: своё против конкурентов.

    Каждая строка — не оценка, а факты рядом: наша цена и их цены, наш срок и
    их сроки. Вывод формулируется только там, где он следует из чисел; там, где
    не следует, строка честно молчит.
    """
    rows = (
        _price_row(mine, rivals),
        _quotes_row(OfferKey.DEADLINE, mine.deadlines, rivals, lambda f: f.deadlines),
        _quotes_row(OfferKey.GUARANTEE, mine.guarantees, rivals, lambda f: f.guarantees),
        _quotes_row(OfferKey.FREE, mine.free_offers, rivals, lambda f: f.free_offers),
        _quotes_row(OfferKey.PROMO, mine.promos, rivals, lambda f: f.promos),
        _form_row(mine, rivals),
        _quotes_row(OfferKey.MESSENGERS, mine.messengers, rivals, lambda f: f.messengers),
    )

    return OfferComparison(
        rows=rows,
        gaps=tuple(row for row in rows if row.is_gap),
        has_data=any(row.rivals_with for row in rows),
    )


def _price_row(
    mine: OfferFacts, rivals: tuple[tuple[str, str, OfferFacts], ...]
) -> OfferRow:
    """Цены сравниваются числами, а не наличием.

    Берётся самая низкая цена страницы: именно она обычно попадает в объявление
    и именно её видит человек, сравнивающий предложения в выдаче.
    """
    values = [(title, url, facts.min_price) for title, url, facts in rivals]
    known = [price for _, _, price in values if price is not None]

    verdict = ""
    is_gap = False

    if mine.min_price is None and known:
        verdict = (
            f"У вас цены на странице нет, а у {len(known)} из {len(rivals)} она указана — "
            f"от {min(known):,} ₽. Посетитель уходит сравнивать туда, где цену видно."
        ).replace(",", " ")
        is_gap = True
    elif mine.min_price is not None and known:
        cheaper = [price for price in known if price < mine.min_price]
        if cheaper:
            verdict = (
                f"Ваша цена от {mine.min_price:,} ₽ выше, чем у {len(cheaper)} из "
                f"{len(known)}: самая низкая у них — {min(cheaper):,} ₽. Это не повод "
                f"снижать: это повод объяснить разницу в объявлении и на странице."
            ).replace(",", " ")
            is_gap = True
        else:
            verdict = (
                f"Ваша цена от {mine.min_price:,} ₽ — самая низкая из сравниваемых. "
                f"Стоит вынести её в заголовок объявления."
            ).replace(",", " ")

    return OfferRow(
        key=OfferKey.PRICE,
        label=OFFER_LABELS[OfferKey.PRICE],
        mine=", ".join(mine.price_quotes) if mine.price_quotes else "",
        rivals=tuple(
            RivalValue(title=title, url=url, value=", ".join(facts.price_quotes))
            for title, url, facts in rivals
        ),
        verdict=verdict,
        is_gap=is_gap,
    )


def _quotes_row(
    key: OfferKey,
    mine: tuple[str, ...],
    rivals: tuple[tuple[str, str, OfferFacts], ...],
    pick: Callable[[OfferFacts], tuple[str, ...]],
) -> OfferRow:
    """Условие, которое сравнивается цитатами: срок, гарантия, «бесплатно»."""
    values = [(title, url, pick(facts)) for title, url, facts in rivals]
    with_value = [(title, quotes) for title, _, quotes in values if quotes]

    verdict = ""
    is_gap = False

    # Порог именно большинство: один конкурент с необычным условием — это
    # разница подходов, а не пробел у нас.
    if not mine and len(with_value) * 2 > len(rivals) and rivals:
        examples = ", ".join(f"«{quotes[0]}»" for _, quotes in with_value[:2])
        verdict = (
            f"У вас этого на странице нет, а у {len(with_value)} из {len(rivals)} есть: "
            f"{examples}. Спросите клиента — возможно, он это делает, но не пишет."
        )
        is_gap = True
    elif mine and not with_value and rivals:
        verdict = f"Есть только у вас: «{mine[0]}». Это отличие, и его стоит выносить в объявление."

    return OfferRow(
        key=key,
        label=OFFER_LABELS[key],
        mine=", ".join(mine),
        rivals=tuple(
            RivalValue(title=title, url=url, value=", ".join(quotes))
            for title, url, quotes in values
        ),
        verdict=verdict,
        is_gap=is_gap,
    )


def _form_row(mine: OfferFacts, rivals: tuple[tuple[str, str, OfferFacts], ...]) -> OfferRow:
    """Длина формы. Короче — почти всегда лучше, и это измеримо."""
    lengths = [facts.form_fields for _, _, facts in rivals if facts.form_fields]
    verdict = ""
    is_gap = False

    if mine.form_fields and lengths:
        shortest = min(lengths)
        if mine.form_fields > shortest + 1:
            verdict = (
                f"Ваша форма из {mine.form_fields} полей длиннее самой короткой у "
                f"конкурентов — там {shortest}. Каждое лишнее поле стоит части заявок."
            )
            is_gap = True
        else:
            verdict = "Ваша форма не длиннее, чем у конкурентов."

    return OfferRow(
        key=OfferKey.FORM,
        label=OFFER_LABELS[OfferKey.FORM],
        mine=str(mine.form_fields) if mine.form_fields else "",
        rivals=tuple(
            RivalValue(
                title=title, url=url, value=str(facts.form_fields) if facts.form_fields else ""
            )
            for title, url, facts in rivals
        ),
        verdict=verdict,
        is_gap=is_gap,
    )
