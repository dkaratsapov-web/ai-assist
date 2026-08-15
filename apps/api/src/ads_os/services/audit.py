"""Аудит сайта и готовность к рекламе (v0.3 §14, §15).

Модуль намеренно не использует модель: всё, что здесь проверяется, проверяется
однозначно — есть форма или нет, стоит счётчик или нет. Отдавать такие вопросы
на усмотрение модели значит получить нестабильный ответ там, где возможен
точный.

Оценка нужна не сама по себе, а чтобы ответить на один вопрос: можно ли вести
на этот сайт платный трафик. Поэтому критические находки не просто снижают
балл, а запрещают автоматический запуск (v0.3 §15).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser


class Severity(StrEnum):
    """Совпадает со словарём статусов интерфейса."""

    CRITICAL = "critical"
    WARNING = "warning"
    RECOMMENDATION = "recommendation"


class Category(StrEnum):
    TECHNICAL = "technical"
    OFFER = "offer"
    CONVERSION = "conversion"
    TRUST = "trust"
    TRACKING = "tracking"


class Verdict(StrEnum):
    READY = "ready"
    READY_WITH_WARNINGS = "ready_with_warnings"
    NOT_READY = "not_ready"


#: Потолок итогового балла при наличии блокирующей находки.
MAX_SCORE_WITH_BLOCKING_ISSUE = 40

#: Вес категории в итоговом балле. Конверсия и аналитика весят больше:
#: красивый сайт без формы и без счётчика не позволяет вести рекламу вообще.
CATEGORY_WEIGHTS: dict[Category, int] = {
    Category.TECHNICAL: 20,
    Category.OFFER: 20,
    Category.CONVERSION: 25,
    Category.TRUST: 15,
    Category.TRACKING: 20,
}


@dataclass(frozen=True, slots=True)
class Issue:
    category: Category
    severity: Severity
    title: str
    #: Что именно сделать. Находка без действия бесполезна.
    action: str


@dataclass(frozen=True, slots=True)
class CategoryResult:
    category: Category
    score: int
    findings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuditResult:
    url: str
    score: int
    verdict: Verdict
    categories: tuple[CategoryResult, ...]
    issues: tuple[Issue, ...]
    #: Найденный номер счётчика Метрики, если он есть.
    metrica_counter: str | None = None

    @property
    def blocking_issues(self) -> tuple[Issue, ...]:
        """Находки, запрещающие автоматический запуск (v0.3 §15)."""
        return tuple(i for i in self.issues if i.severity is Severity.CRITICAL)

    @property
    def can_launch(self) -> bool:
        return not self.blocking_issues


@dataclass(slots=True)
class _Signals:
    """Что нашлось на странице. Промежуточный результат разбора."""

    title: str = ""
    h1: list[str] = field(default_factory=list)
    forms: int = 0
    inputs: int = 0
    phones: int = 0
    emails: int = 0
    messengers: list[str] = field(default_factory=list)
    prices: int = 0
    cta_buttons: int = 0
    has_viewport: bool = False
    metrica_counter: str | None = None
    has_analytics: bool = False
    trust_words: list[str] = field(default_factory=list)
    offer_words: list[str] = field(default_factory=list)


_PHONE_RE = re.compile(r"(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PRICE_RE = re.compile(r"\d[\d\s]{1,9}\s*(?:₽|руб|р\.)", re.IGNORECASE)
_METRICA_RE = re.compile(r"(?:ym\(\s*(\d{5,10})|mc\.yandex\.ru/watch/(\d{5,10}))")

_MESSENGERS = {
    "telegram": ("t.me/", "telegram.me", "tg://"),
    "whatsapp": ("wa.me/", "whatsapp://", "api.whatsapp.com"),
    "max": ("max.ru/", "max://"),
}

_TRUST_WORDS = ("гарант", "отзыв", "сертифик", "лиценз", "опыт работы", "кейс", "лет на рынке")
_OFFER_WORDS = ("скидк", "акци", "бесплатн", "в подарок", "от ", "срок", "за 1 час", "выезд")
_CTA_WORDS = (
    "заказ",
    "оставить заявку",
    "купить",
    "записаться",
    "перезвон",
    "консультац",
    "рассчитать",
)


def audit_page(url: str, html: str, *, status_code: int = 200) -> AuditResult:
    """Разбирает страницу и считает готовность к рекламе."""
    signals = _collect(html)
    issues: list[Issue] = []

    technical = _technical(url, status_code, signals, issues)
    offer = _offer(signals, issues)
    conversion = _conversion(signals, issues)
    trust = _trust(signals, issues)
    tracking = _tracking(signals, issues)

    categories = (technical, offer, conversion, trust, tracking)

    # Итог — взвешенное среднее по категориям. Вес отражает, насколько
    # категория мешает вести трафик, а не насколько она заметна глазу.
    total = sum(c.score * CATEGORY_WEIGHTS[c.category] for c in categories)
    score = round(total / sum(CATEGORY_WEIGHTS.values()))

    has_critical = any(i.severity is Severity.CRITICAL for i in issues)
    has_warning = any(i.severity is Severity.WARNING for i in issues)

    if has_critical:
        # Балл не должен спорить с вердиктом. Без этого ограничения сайт,
        # отвечающий ошибкой 503, набирал 80 из 100 за счёт хорошего
        # содержимого — и выглядел почти готовым, хотя вести на него трафик
        # нельзя вообще. На число смотрят чаще, чем на вердикт.
        score = min(score, MAX_SCORE_WITH_BLOCKING_ISSUE)
        verdict = Verdict.NOT_READY
    elif has_warning or score < 80:
        verdict = Verdict.READY_WITH_WARNINGS
    else:
        verdict = Verdict.READY

    return AuditResult(
        url=url,
        score=score,
        verdict=verdict,
        categories=categories,
        issues=tuple(issues),
        metrica_counter=signals.metrica_counter,
    )


def _collect(html: str) -> _Signals:
    tree = HTMLParser(html)
    signals = _Signals()

    if (node := tree.css_first("title")) is not None:
        signals.title = node.text(strip=True)

    signals.h1 = [n.text(strip=True) for n in tree.css("h1") if n.text(strip=True)]
    signals.forms = len(tree.css("form"))
    signals.inputs = len(tree.css("input, textarea, select"))
    signals.has_viewport = any(
        (n.attributes.get("name") or "").lower() == "viewport" for n in tree.css("meta")
    )

    text = tree.text(separator=" ", strip=True)
    lowered = text.lower()

    signals.phones = len(set(_PHONE_RE.findall(text)))
    signals.emails = len(set(_EMAIL_RE.findall(text)))
    signals.prices = len(_PRICE_RE.findall(text))

    hrefs = " ".join((n.attributes.get("href") or "") for n in tree.css("a"))
    for name, markers in _MESSENGERS.items():
        if any(marker in hrefs.lower() for marker in markers):
            signals.messengers.append(name)

    clickable = tree.css("button, a, input[type=submit]")
    signals.cta_buttons = sum(
        1 for n in clickable if any(w in n.text(strip=True).lower() for w in _CTA_WORDS)
    )

    signals.trust_words = [w for w in _TRUST_WORDS if w in lowered]
    signals.offer_words = [w for w in _OFFER_WORDS if w in lowered]

    if match := _METRICA_RE.search(html):
        signals.metrica_counter = match.group(1) or match.group(2)
        signals.has_analytics = True

    return signals


def _technical(url: str, status_code: int, s: _Signals, issues: list[Issue]) -> CategoryResult:
    score = 100
    findings: list[str] = []

    if status_code >= 500:
        issues.append(
            Issue(
                Category.TECHNICAL,
                Severity.CRITICAL,
                f"Сайт отвечает ошибкой {status_code}",
                "Восстановите работу сайта — вести на него трафик нельзя.",
            )
        )
        score = 0
    elif status_code >= 400:
        issues.append(
            Issue(
                Category.TECHNICAL,
                Severity.CRITICAL,
                f"Страница недоступна: код {status_code}",
                "Проверьте адрес посадочной страницы.",
            )
        )
        score = 0
    else:
        findings.append(f"Отвечает кодом {status_code}")

    if urlsplit(url).scheme != "https":
        issues.append(
            Issue(
                Category.TECHNICAL,
                Severity.CRITICAL,
                "Сайт работает без HTTPS",
                "Подключите сертификат: без защищённого соединения браузеры "
                "предупреждают посетителей, а конверсия падает.",
            )
        )
        score = min(score, 30)
    else:
        findings.append("Защищённое соединение")

    if not s.has_viewport:
        issues.append(
            Issue(
                Category.TECHNICAL,
                Severity.WARNING,
                "Нет мобильной вёрстки",
                "Добавьте мета-тег viewport: больше половины трафика приходит с телефонов.",
            )
        )
        score -= 25
    else:
        findings.append("Адаптирован под мобильные")

    if not s.title:
        issues.append(
            Issue(
                Category.TECHNICAL,
                Severity.WARNING,
                "Нет заголовка страницы",
                "Заполните title — он влияет и на выдачу, и на качество объявления.",
            )
        )
        score -= 15

    return CategoryResult(Category.TECHNICAL, _clamp(score), tuple(findings))


def _offer(s: _Signals, issues: list[Issue]) -> CategoryResult:
    score = 100
    findings: list[str] = []

    if not s.h1:
        issues.append(
            Issue(
                Category.OFFER,
                Severity.WARNING,
                "Нет заголовка H1",
                "Добавьте на страницу главный заголовок с сутью предложения.",
            )
        )
        score -= 30
    else:
        findings.append(f"Заголовок: {s.h1[0][:80]}")

    if s.prices == 0:
        issues.append(
            Issue(
                Category.OFFER,
                Severity.RECOMMENDATION,
                "На странице нет цен",
                "Покажите цены или диапазон: посетители без цены чаще уходят сравнивать.",
            )
        )
        score -= 25
    else:
        findings.append(f"Цены указаны ({s.prices} упоминаний)")

    if not s.offer_words:
        score -= 20
    else:
        findings.append("Есть акции или условия предложения")

    return CategoryResult(Category.OFFER, _clamp(score), tuple(findings))


def _conversion(s: _Signals, issues: list[Issue]) -> CategoryResult:
    score = 100
    findings: list[str] = []

    contact_ways = s.forms + s.phones + len(s.messengers)

    if contact_ways == 0:
        # Некуда оставить заявку — реклама будет расходовать бюджет впустую.
        issues.append(
            Issue(
                Category.CONVERSION,
                Severity.CRITICAL,
                "Нет ни одного способа связаться",
                "Добавьте форму заявки, телефон или мессенджер — иначе бюджет "
                "уходит на посетителей, которые физически не могут обратиться.",
            )
        )
        return CategoryResult(Category.CONVERSION, 0)

    if s.forms == 0:
        issues.append(
            Issue(
                Category.CONVERSION,
                Severity.WARNING,
                "Нет формы заявки",
                "Добавьте форму: без неё нельзя измерять конверсии и оптимизировать рекламу.",
            )
        )
        score -= 35
    else:
        findings.append(f"Форм на странице: {s.forms}")

    if s.phones:
        findings.append("Указан телефон")
    if s.messengers:
        findings.append("Мессенджеры: " + ", ".join(s.messengers))

    if s.cta_buttons == 0:
        issues.append(
            Issue(
                Category.CONVERSION,
                Severity.WARNING,
                "Нет призыва к действию",
                "Добавьте заметную кнопку «Оставить заявку» или «Рассчитать стоимость».",
            )
        )
        score -= 25
    else:
        findings.append(f"Кнопок действия: {s.cta_buttons}")

    return CategoryResult(Category.CONVERSION, _clamp(score), tuple(findings))


def _trust(s: _Signals, issues: list[Issue]) -> CategoryResult:
    score = 100
    findings: list[str] = []

    if not s.trust_words:
        issues.append(
            Issue(
                Category.TRUST,
                Severity.RECOMMENDATION,
                "Нет признаков доверия",
                "Добавьте отзывы, гарантии или примеры работ — они заметно влияют на конверсию.",
            )
        )
        score -= 40
    else:
        findings.append("Есть: " + ", ".join(s.trust_words[:3]))

    if s.phones == 0 and s.emails == 0:
        score -= 30
    else:
        findings.append("Контакты на виду")

    return CategoryResult(Category.TRUST, _clamp(score), tuple(findings))


def _tracking(s: _Signals, issues: list[Issue]) -> CategoryResult:
    if not s.has_analytics:
        # Без аналитики реклама неуправляема: не видно ни конверсий, ни
        # источников. Это блокирующая проблема, а не замечание.
        issues.append(
            Issue(
                Category.TRACKING,
                Severity.CRITICAL,
                "Не установлена Яндекс Метрика",
                "Установите счётчик до запуска: без него не видно, какие клики "
                "приносят заявки, и оптимизировать рекламу невозможно.",
            )
        )
        return CategoryResult(Category.TRACKING, 0)

    return CategoryResult(
        Category.TRACKING,
        100,
        (f"Метрика установлена, счётчик {s.metrica_counter}",),
    )


def _clamp(value: int) -> int:
    return max(0, min(100, value))
