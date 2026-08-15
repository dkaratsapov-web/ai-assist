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
from collections.abc import Iterable, Sequence
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


class IssueKey(StrEnum):
    """Устойчивое имя проверки.

    Заголовок находки для этого не годится: он меняется вместе с формулировкой
    и иногда содержит число («открывается за 4,2 с»). Сравнить две проверки по
    заголовкам нельзя — каждая выглядела бы новой.

    Ключ живёт дольше текста: по нему видно, что замечание исправлено, а не
    просто переформулировано.
    """

    SERVER_ERROR = "server_error"
    PAGE_UNAVAILABLE = "page_unavailable"
    NO_HTTPS = "no_https"
    NO_MOBILE = "no_mobile"
    NO_TITLE = "no_title"
    SLOW = "slow"
    VERY_SLOW = "very_slow"

    NO_H1 = "no_h1"
    NO_PRICES = "no_prices"

    NO_CONTACTS = "no_contacts"
    NO_FORM = "no_form"
    LONG_FORM = "long_form"
    PHONE_NOT_CLICKABLE = "phone_not_clickable"
    NO_CTA = "no_cta"

    NO_TRUST_SIGNALS = "no_trust_signals"
    NO_PRIVACY_POLICY = "no_privacy_policy"

    NO_METRICA = "no_metrica"


class Verdict(StrEnum):
    READY = "ready"
    READY_WITH_WARNINGS = "ready_with_warnings"
    NOT_READY = "not_ready"


#: Проверки, находки по которым всегда блокируют запуск. Список задан явно, а
#: не выведен из результата: скрывать замечание человек решает до того, как
#: очередная проверка отработает, и к этому моменту её severity ещё неизвестен.
#: Согласованность списка с реальными находками проверяется тестом.
BLOCKING_ISSUE_KEYS = frozenset(
    {
        IssueKey.SERVER_ERROR,
        IssueKey.PAGE_UNAVAILABLE,
        IssueKey.NO_HTTPS,
        IssueKey.NO_CONTACTS,
        IssueKey.NO_PRIVACY_POLICY,
        IssueKey.NO_METRICA,
    }
)

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
    #: Что именно проверялось. По нему находки сопоставляются между проверками.
    key: IssueKey
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
class PageSignals:
    """Что нашлось на странице.

    Публичная структура: тем же разбором пользуется сравнение с конкурентами.
    Второй парсер для тех же признаков означал бы, что «есть форма заявки» на
    своём сайте и на чужом определяется по разным правилам — и сравнение
    перестало бы что-либо значить.
    """

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
    #: Есть ли ссылка на политику обработки персональных данных. Для рекламы это
    #: не благое пожелание: страницу с формой без политики Яндекс Директ
    #: отклоняет на модерации.
    has_privacy_policy: bool = False
    #: Сколько видимых полей в самой большой форме. Форма из десяти полей
    #: собирает заявок в разы меньше, чем форма из двух, — при том же бюджете.
    max_form_fields: int = 0
    #: Короткие фрагменты предложения прямо со страницы: «Замер бесплатно»,
    #: «Гарантия 5 лет», «Окно от 12 900 ₽». Из них собираются черновики
    #: объявлений — так текст остаётся текстом клиента, а не выдумкой системы.
    selling_points: list[str] = field(default_factory=list)
    #: Оформлен ли телефон ссылкой tel:. С телефона по ненажимаемому номеру не
    #: позвонить — его надо запоминать и набирать вручную, и часть посетителей
    #: этого просто не делает.
    has_tel_link: bool = False


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
_PRIVACY_WORDS = (
    "политика конфиденциальности",
    "политику конфиденциальности",
    "обработку персональных данных",
    "обработки персональных данных",
    "персональных данных",
    "privacy",
)

#: Сколько полей в форме считается перебором. Порог не строгий: заявка на замер
#: и заявка на кредит требуют разного. Пять — граница, после которой почти
#: всегда есть что убрать.
MAX_COMFORTABLE_FORM_FIELDS = 5

#: Пороги времени ответа. Три секунды — момент, после которого заметная часть
#: посетителей уходит, не дождавшись. Восемь — когда уходит большинство.
SLOW_RESPONSE_MS = 3000
VERY_SLOW_RESPONSE_MS = 8000

_CTA_WORDS = (
    "заказ",
    "оставить заявку",
    "купить",
    "записаться",
    "перезвон",
    "консультац",
    "рассчитать",
)


def audit_page(
    url: str, html: str, *, status_code: int = 200, elapsed_ms: int | None = None
) -> AuditResult:
    """Разбирает страницу и считает готовность к рекламе.

    `elapsed_ms` — время загрузки, если оно известно. Необязательное: страницу
    можно разобрать и из сохранённого HTML, и тогда времени нет. Отсутствие
    времени не считается хорошим результатом — проверка просто не проводится.
    """
    signals = collect_signals(html)
    issues: list[Issue] = []

    technical = _technical(url, status_code, signals, issues, elapsed_ms)
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


def collect_signals(html: str) -> PageSignals:
    """Разбирает страницу в набор признаков."""
    tree = HTMLParser(html)
    signals = PageSignals()

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

    links = tree.css("a")
    hrefs = " ".join((n.attributes.get("href") or "") for n in links)
    for name, markers in _MESSENGERS.items():
        if any(marker in hrefs.lower() for marker in markers):
            signals.messengers.append(name)

    signals.has_tel_link = "tel:" in hrefs.lower()

    # Политику ищем и по тексту ссылки, и по адресу: на одних сайтах это ссылка
    # «Политика конфиденциальности», на других — галочка согласия рядом с
    # формой, ведущая на /privacy.
    signals.has_privacy_policy = any(
        word in lowered for word in _PRIVACY_WORDS
    ) or "privacy" in hrefs.lower()

    for form in tree.css("form"):
        visible = [
            n
            for n in form.css("input, textarea, select")
            if (n.attributes.get("type") or "text").lower() not in ("hidden", "submit", "button")
        ]
        signals.max_form_fields = max(signals.max_form_fields, len(visible))

    clickable = tree.css("button, a, input[type=submit]")
    signals.cta_buttons = sum(
        1 for n in clickable if any(w in n.text(strip=True).lower() for w in _CTA_WORDS)
    )

    signals.trust_words = [w for w in _TRUST_WORDS if w in lowered]
    signals.offer_words = [w for w in _OFFER_WORDS if w in lowered]
    # Блоки разделяются переводом строки, а не пробелом: иначе заголовок
    # склеивается со следующим абзацем в одну бессмысленную строку.
    signals.selling_points = _selling_points(tree.text(separator="\n", strip=True))

    if match := _METRICA_RE.search(html):
        signals.metrica_counter = match.group(1) or match.group(2)
        signals.has_analytics = True

    return signals


def _technical(
    url: str,
    status_code: int,
    s: PageSignals,
    issues: list[Issue],
    elapsed_ms: int | None = None,
) -> CategoryResult:
    score = 100
    findings: list[str] = []

    if status_code >= 500:
        issues.append(
            Issue(
                IssueKey.SERVER_ERROR,
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
                IssueKey.PAGE_UNAVAILABLE,
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
                IssueKey.NO_HTTPS,
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
                IssueKey.NO_MOBILE,
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
                IssueKey.NO_TITLE,
                Category.TECHNICAL,
                Severity.WARNING,
                "Нет заголовка страницы",
                "Заполните title — он влияет и на выдачу, и на качество объявления.",
            )
        )
        score -= 15

    if elapsed_ms is not None:
        seconds = elapsed_ms / 1000
        if elapsed_ms >= VERY_SLOW_RESPONSE_MS:
            issues.append(
                Issue(
                    IssueKey.VERY_SLOW,
                    Category.TECHNICAL,
                    Severity.WARNING,
                    f"Сайт открывается очень долго: {seconds:.1f} с",
                    "Разберитесь со скоростью до запуска. За такое ожидание "
                    "уходит большинство посетителей, а клик оплачен.",
                )
            )
            score -= 35
        elif elapsed_ms >= SLOW_RESPONSE_MS:
            issues.append(
                Issue(
                    IssueKey.SLOW,
                    Category.TECHNICAL,
                    Severity.RECOMMENDATION,
                    f"Сайт открывается медленно: {seconds:.1f} с",
                    "Ускорьте загрузку: после трёх секунд ожидания заметная "
                    "часть посетителей закрывает вкладку.",
                )
            )
            score -= 15
        else:
            findings.append(f"Открывается за {seconds:.1f} с")

    return CategoryResult(Category.TECHNICAL, _clamp(score), tuple(findings))


def _offer(s: PageSignals, issues: list[Issue]) -> CategoryResult:
    score = 100
    findings: list[str] = []

    if not s.h1:
        issues.append(
            Issue(
                IssueKey.NO_H1,
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
                IssueKey.NO_PRICES,
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


def _conversion(s: PageSignals, issues: list[Issue]) -> CategoryResult:
    score = 100
    findings: list[str] = []

    contact_ways = s.forms + s.phones + len(s.messengers)

    if contact_ways == 0:
        # Некуда оставить заявку — реклама будет расходовать бюджет впустую.
        issues.append(
            Issue(
                IssueKey.NO_CONTACTS,
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
                IssueKey.NO_FORM,
                Category.CONVERSION,
                Severity.WARNING,
                "Нет формы заявки",
                "Добавьте форму: без неё нельзя измерять конверсии и оптимизировать рекламу.",
            )
        )
        score -= 35
    else:
        findings.append(f"Форм на странице: {s.forms}")

    if s.max_form_fields > MAX_COMFORTABLE_FORM_FIELDS:
        issues.append(
            Issue(
                IssueKey.LONG_FORM,
                Category.CONVERSION,
                Severity.RECOMMENDATION,
                f"В форме {s.max_form_fields} полей",
                "Оставьте имя и телефон, остальное спросите при звонке. "
                "Длинная форма собирает меньше заявок при том же бюджете.",
            )
        )
        score -= 15

    if s.phones and not s.has_tel_link:
        issues.append(
            Issue(
                IssueKey.PHONE_NOT_CLICKABLE,
                Category.CONVERSION,
                Severity.RECOMMENDATION,
                "Телефон нельзя нажать",
                "Оформите номер ссылкой tel: — с телефона по такому номеру "
                "звонят в одно касание, а не переписывают вручную.",
            )
        )
        score -= 10

    if s.phones:
        findings.append("Указан телефон")
    if s.messengers:
        findings.append("Мессенджеры: " + ", ".join(s.messengers))

    if s.cta_buttons == 0:
        issues.append(
            Issue(
                IssueKey.NO_CTA,
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


def _trust(s: PageSignals, issues: list[Issue]) -> CategoryResult:
    score = 100
    findings: list[str] = []

    if not s.trust_words:
        issues.append(
            Issue(
                IssueKey.NO_TRUST_SIGNALS,
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

    if s.forms and not s.has_privacy_policy:
        # Не гигиена, а причина отказа на модерации: страница собирает
        # персональные данные, а на каком основании — не сказано. Реклама
        # просто не запустится, поэтому это блокирующая находка.
        issues.append(
            Issue(
                IssueKey.NO_PRIVACY_POLICY,
                Category.TRUST,
                Severity.CRITICAL,
                "Форма есть, а политики обработки данных нет",
                "Добавьте ссылку на политику обработки персональных данных и "
                "согласие в форме. Без этого Яндекс Директ отклонит объявления "
                "на модерации.",
            )
        )
        score -= 40
    elif s.has_privacy_policy:
        findings.append("Есть политика обработки данных")

    return CategoryResult(Category.TRUST, _clamp(score), tuple(findings))


def _tracking(s: PageSignals, issues: list[Issue]) -> CategoryResult:
    if not s.has_analytics:
        # Без аналитики реклама неуправляема: не видно ни конверсий, ни
        # источников. Это блокирующая проблема, а не замечание.
        issues.append(
            Issue(
                IssueKey.NO_METRICA,
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


@dataclass(frozen=True, slots=True)
class IssueChanges:
    """Что изменилось между двумя проверками.

    Отвечает на вопрос, ради которого повторный аудит и запускают: помогли
    доработки или нет. Изменение балла на это не отвечает — балл мог вырасти на
    три пункта, пока критическая проблема осталась на месте.
    """

    #: Замечания, которых больше нет.
    fixed: tuple[Issue, ...] = ()
    #: Замечания, которых раньше не было. Их появление важнее исправлений:
    #: обычно это значит, что сайт что-то сломал по дороге.
    appeared: tuple[Issue, ...] = ()
    #: Замечания, которые были и остались.
    remaining: tuple[Issue, ...] = ()


def compare_issues(previous: Sequence[Issue], current: Sequence[Issue]) -> IssueChanges:
    """Сопоставляет находки двух проверок по ключам.

    Сравнение идёт по ключу, а не по заголовку: заголовок «Сайт открывается за
    4,2 с» меняется при каждой проверке, и по нему любая находка выглядела бы
    одновременно исправленной и новой.
    """
    previous_by_key = {issue.key: issue for issue in previous}
    current_by_key = {issue.key: issue for issue in current}

    return IssueChanges(
        fixed=tuple(issue for key, issue in previous_by_key.items() if key not in current_by_key),
        appeared=tuple(
            issue for key, issue in current_by_key.items() if key not in previous_by_key
        ),
        remaining=tuple(issue for key, issue in current_by_key.items() if key in previous_by_key),
    )


def issues_from_stored(rows: Iterable[dict[str, object]]) -> tuple[Issue, ...]:
    """Восстанавливает находки из сохранённого вида.

    Записи, сделанные до появления ключей, пропускаются: у них нет устойчивого
    имени, и сопоставить их не с чем. Молча подставлять им заголовок вместо
    ключа нельзя — сравнение показало бы исправления, которых не было.
    """
    restored: list[Issue] = []

    for row in rows:
        key = row.get("key")
        if not key:
            continue
        try:
            restored.append(
                Issue(
                    key=IssueKey(str(key)),
                    category=Category(str(row["category"])),
                    severity=Severity(str(row["severity"])),
                    title=str(row["title"]),
                    action=str(row["action"]),
                )
            )
        except (KeyError, ValueError):
            # Незнакомая проверка — из будущей или уже удалённой версии.
            # Пропускаем её, а не роняем всю историю.
            continue

    return tuple(restored)


#: Предел длины фрагмента предложения. Ограничение идёт от объявления: во
#: второй заголовок Директа помещается тридцать символов, и фрагмент длиннее
#: годится разве что в текст.
MAX_SELLING_POINT = 60

_SENTENCE_RE = re.compile(r"[^.!?•·|\n]+")


def _selling_points(text: str) -> list[str]:
    """Короткие фрагменты предложения прямо со страницы.

    Берутся куски собственного текста клиента, а не сочинённые формулировки.
    Причина не в скромности: объявление, обещающее то, чего на странице нет, —
    это отказ на модерации в лучшем случае и жалоба клиента в худшем.
    """
    found: list[str] = []
    seen: set[str] = set()

    pieces: list[str] = []
    for raw in _SENTENCE_RE.findall(text):
        sentence = " ".join(raw.split()).strip(" ,;:—-")
        pieces.append(sentence)
        # Длинное предложение дополнительно режется по запятым. «Гарантия 5
        # лет, более 4000 отзывов, 11 лет на рынке» целиком не помещается во
        # второй заголовок, а каждая часть по отдельности — помещается.
        if len(sentence) > 30 and "," in sentence:
            pieces.extend(part.strip() for part in sentence.split(","))

    for fragment in pieces:
        if not (3 < len(fragment) <= MAX_SELLING_POINT):
            continue

        lowered = fragment.lower()
        if not any(w in lowered for w in _OFFER_WORDS + _TRUST_WORDS) and not _PRICE_RE.search(
            fragment
        ):
            continue

        key = lowered
        if key in seen:
            continue
        seen.add(key)
        found.append(fragment)

    return found[:12]
