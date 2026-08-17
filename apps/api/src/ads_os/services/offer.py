"""Предложение страницы: конкретные условия, а не галочки.

Сравнение по признакам «есть форма — нет формы» отвечает на вопрос, который
специалист и так не задаёт. Он приходит к конкуренту не выяснять, есть ли у
того телефон, а смотреть, **чем тот берёт**: какая цена, какой срок, что
обещают бесплатно, какая гарантия, чем заманивают сегодня.

Именно это здесь и достаётся: цифры и цитаты со страницы. Цитаты — дословные:
пересказ чужого предложения своими словами превращает факт в мнение, а всё
преимущество такого сравнения в том, что его можно проверить, открыв сайт
конкурента и найдя глазами ту же строку.

Чего здесь нет и не будет: трафика, бюджетов, позиций и «силы бренда». С
публичной страницы это не читается, а правдоподобное число на месте незнания
опаснее пустого места — по нему принимают решения.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from selectolax.parser import HTMLParser

#: Сколько цитат берём на каждое условие. Одна — случайность, десять — уже не
#: сравнение, а копия чужого сайта.
MAX_QUOTES = 3

_INVISIBLE = ("script", "style", "noscript", "template", "svg")

#: Цена с валютой. Берётся вместе с числом, чтобы можно было сравнивать.
_PRICE_RE = re.compile(r"(\d[\d\s ]{0,9})\s*(?:₽|руб\.?|р\.)(?:\s*/?\s*(м2|м²|шт|час|кв\.?м))?")

#: Срок исполнения. «За 1 день», «за 24 часа», «в день обращения».
_DEADLINE_RE = re.compile(
    r"(?:за|в течение|всего за)\s+\d{1,3}\s*(?:минут|час|часа|часов|день|дня|дней|сутки|суток)"
    r"|в день обращения"
    r"|день в день"
    r"|за один день"
    r"|круглосуточно",
    re.IGNORECASE,
)

#: Гарантия со сроком. Без срока «гарантия качества» — это не условие, а слово.
_GUARANTEE_RE = re.compile(
    r"гарантия[^.,;!?\n]{0,40}?\d{1,3}\s*(?:год|года|лет|месяц|месяца|месяцев)"
    r"|\d{1,3}\s*(?:год|года|лет|месяц|месяца|месяцев)\s+гарантии",
    re.IGNORECASE,
)

#: Что отдают бесплатно. Самый частый рычаг в услугах: замер, выезд, доставка.
_FREE_RE = re.compile(
    r"[^.,;!?\n]{0,30}\bбесплатн\w*[^.,;!?\n]{0,30}"
    r"|[^.,;!?\n]{0,25}\bв подарок\b",
    re.IGNORECASE,
)

#: Скидки и рассрочка — повод обратиться сегодня.
_PROMO_RE = re.compile(
    r"скидк\w*[^.,;!?\n]{0,30}"
    r"|акци\w*[^.,;!?\n]{0,30}"
    r"|рассрочк\w*[^.,;!?\n]{0,30}"
    r"|(?:0|беспроцентн\w*)\s*%[^.,;!?\n]{0,20}",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class OfferFacts:
    """Чем страница берёт посетителя."""

    #: Главный заголовок: как компания себя подаёт в одну строку.
    headline: str = ""
    #: Найденные цены числом — по ним и сравниваем.
    price_values: tuple[int, ...] = field(default_factory=tuple)
    #: Те же цены, как написано на странице.
    price_quotes: tuple[str, ...] = field(default_factory=tuple)
    deadlines: tuple[str, ...] = field(default_factory=tuple)
    guarantees: tuple[str, ...] = field(default_factory=tuple)
    free_offers: tuple[str, ...] = field(default_factory=tuple)
    promos: tuple[str, ...] = field(default_factory=tuple)
    #: Сколько полей в самой длинной форме. Форма из десяти полей собирает
    #: заявок в разы меньше, чем форма из двух, при том же бюджете.
    form_fields: int = 0
    messengers: tuple[str, ...] = field(default_factory=tuple)

    @property
    def min_price(self) -> int | None:
        """Самая низкая цена страницы: обычно она и стоит в объявлении."""
        return min(self.price_values) if self.price_values else None

    def as_dict(self) -> dict[str, object]:
        return {
            "headline": self.headline,
            "price_values": list(self.price_values),
            "price_quotes": list(self.price_quotes),
            "deadlines": list(self.deadlines),
            "guarantees": list(self.guarantees),
            "free_offers": list(self.free_offers),
            "promos": list(self.promos),
            "form_fields": self.form_fields,
            "messengers": list(self.messengers),
        }


def from_stored(data: dict[str, object] | None) -> OfferFacts:
    if not data:
        return OfferFacts()

    def items(key: str) -> tuple[str, ...]:
        value = data.get(key)
        return tuple(str(item) for item in value) if isinstance(value, list) else ()

    prices = data.get("price_values")
    headline = data.get("headline")
    fields = data.get("form_fields")

    return OfferFacts(
        headline=headline if isinstance(headline, str) else "",
        price_values=tuple(int(v) for v in prices if isinstance(v, int))
        if isinstance(prices, list)
        else (),
        price_quotes=items("price_quotes"),
        deadlines=items("deadlines"),
        guarantees=items("guarantees"),
        free_offers=items("free_offers"),
        promos=items("promos"),
        form_fields=fields if isinstance(fields, int) else 0,
        messengers=items("messengers"),
    )


def extract(html: str) -> OfferFacts:
    """Достаёт со страницы условия предложения."""
    tree = HTMLParser(html)

    hrefs = " ".join(node.attributes.get("href") or "" for node in tree.css("a[href]")).lower()
    form_fields = max(
        (len(form.css("input, select, textarea")) for form in tree.css("form")), default=0
    )

    for hidden in tree.css(",".join(_INVISIBLE)):
        hidden.decompose()

    text = " ".join(tree.text(separator=" ").split())
    h1 = tree.css_first("h1")

    values, quotes = _prices(text)

    return OfferFacts(
        headline=" ".join(h1.text().split())[:200] if h1 else "",
        price_values=values,
        price_quotes=quotes,
        deadlines=_quotes(_DEADLINE_RE, text),
        guarantees=_quotes(_GUARANTEE_RE, text),
        free_offers=_quotes(_FREE_RE, text),
        promos=_quotes(_PROMO_RE, text),
        form_fields=form_fields,
        messengers=tuple(
            name
            for name, marks in (
                ("Telegram", ("t.me/", "telegram.me", "tg://")),
                ("WhatsApp", ("wa.me/", "whatsapp://", "api.whatsapp.com")),
                ("MAX", ("max.ru/", "max://")),
            )
            if any(mark in hrefs for mark in marks)
        ),
    )


def _quotes(pattern: re.Pattern[str], text: str) -> tuple[str, ...]:
    """Дословные куски страницы, без повторов и мусора по краям."""
    found: list[str] = []

    for match in pattern.finditer(text):
        quote = " ".join(match.group(0).split()).strip(" -–—:·|,")
        if not quote or len(quote) > 90:
            continue
        lowered = quote.lower()
        if any(lowered == item.lower() for item in found):
            continue
        found.append(quote)
        if len(found) == MAX_QUOTES:
            break

    return tuple(found)


def _prices(text: str) -> tuple[tuple[int, ...], tuple[str, ...]]:
    """Цены числом и как написано.

    Слишком мелкие значения отбрасываются: «от 5 ₽» на странице услуг — это
    почти всегда цена за сантиметр профиля или остаток номера телефона, а не
    предложение, с которым идут сравниваться.
    """
    values: list[int] = []
    quotes: list[str] = []

    for match in _PRICE_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group(1))
        if not digits:
            continue
        value = int(digits)
        if value < 50 or value > 100_000_000:
            continue
        if value in values:
            continue
        values.append(value)
        quotes.append(" ".join(match.group(0).split()))
        if len(values) == 10:
            break

    order = sorted(range(len(values)), key=lambda i: values[i])
    return tuple(values[i] for i in order), tuple(quotes[i] for i in order[:MAX_QUOTES])
