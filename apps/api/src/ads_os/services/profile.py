"""Анкета клиента, прочитанная с его сайта.

Разбор сайта уже ходит на страницу ради оценки готовности к рекламе. Странно
при этом заставлять человека вручную вписывать город, услуги и телефон —
всё это на той же странице и написано. Модуль достаёт оттуда то, что можно
прочитать, и складывает в анкету.

Граница проведена жёстко и намеренно.

Слева — то, что на сайте **написано**: название, город, услуги, цены,
контакты, реквизиты. Это факты со страницы, их можно показать и проверить
глазами за секунду.

Справа — то, чего на сайте **не бывает**: сколько клиент готов платить за
заявку, какая у него маржа, что он на самом деле не делает, есть ли сезонность,
куда попадают заявки. Ни один разбор страницы этого не даст, и угадывать здесь
нельзя — на этих числах строится весь расчёт экономики. Поэтому вторая половина
анкеты остаётся вопросами, которые человек задаёт клиенту.

Ничего не применяется само. Анкета — предложение: специалист смотрит, правит и
принимает. Молча проставленный не тот город стоит месяца рекламы не в том
регионе, и заметить это по интерфейсу, который ничего не спросил, невозможно.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from selectolax.parser import HTMLParser

from . import niches
from .cleanup import cities_in
from .morphology import stem, tokenize

#: Сколько услуг забираем с сайта. Больше десяти — это уже не список услуг, а
#: пересказ меню, и проверять его человек не станет.
MAX_SERVICES = 10

#: Сколько ключевых слов ниши должны найтись, чтобы считать её угаданной. Одно
#: слово ничего не значит: «окна» встречается и у клининга, который моет окна.
NICHE_HITS_NEEDED = 2

_PHONE_RE = re.compile(r"(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PRICE_RE = re.compile(r"(?:от\s+)?\d[\d\s ]{1,9}\s*(?:₽|руб\.?|р\.)", re.IGNORECASE)
_COMPANY_RE = re.compile(
    r"(?:ООО|АО|ЗАО|ПАО|ИП)\s*[«\"]?([А-ЯЁA-Z][^»\"\n,.]{1,40})[»\"]?", re.IGNORECASE
)
_INN_RE = re.compile(r"\b(?:ИНН|ОГРНИП|ОГРН)\b[\s:№]*(\d{5,15})", re.IGNORECASE)
_HOURS_RE = re.compile(
    r"(круглосуточно"
    r"|ежедневно[^.\n]{0,30}"
    r"|(?:пн|понедельник)[\s\-–—]*(?:пт|вс|сб|пятниц|воскресень)[^.\n]{0,30}"
    r"|с\s*\d{1,2}[:.]?\d{0,2}\s*до\s*\d{1,2}[:.]?\d{0,2})",
    re.IGNORECASE,
)
#: Тип улицы — якорь адреса. От него отсчитывается всё остальное.
_STREET_TYPE = (
    r"ул\.|улиц[аы]|просп(?:ект)?\.?|пр-?кт\.?|пр-т|шоссе|ш\.|"
    r"переул(?:ок)?\.?|пер\.|бульвар|б-р|набережн(?:ая)?|наб\.|проезд|"
    r"площад[ьи]|пл\.|микрорайон|мкр\.?"
)

#: Адрес: одно слово названия перед типом улицы либо название после него,
#: затем дом.
#:
#: Раньше здесь стоял захват «до шестидесяти любых знаков» в обе стороны от
#: типа улицы, и в анкету уезжало вот это: «пании Trade-in Ремонт Акции Бонусы
#: Контакты Тверь, Тверской пр-т, д». Окно захватывало кусок меню, начиналось
#: с середины слова и обрывалось на середине дома. Адрес, обрезанный с двух
#: сторон, хуже отсутствующего: по нему нельзя ни позвонить, ни проверить, а
#: выглядит он как данные.
#:
#: Теперь границы заданы смыслом, а не длиной: слева — ровно одно слово с
#: заглавной буквы («Тверской пр-т»), справа — название улицы до запятой и
#: номер дома с корпусом. Запятая и точка границы не пересекают, поэтому меню
#: в адрес попасть не может.
_ADDRESS_RE = re.compile(
    r"(?:(?P<before>[А-ЯЁA-Z][\w-]{2,24})\s+)?"
    rf"(?P<type>{_STREET_TYPE})"
    r"(?P<after>\s*[А-ЯЁA-Zа-яёa-z][^,.;:!?\n|]{0,34})?"
    # Буква дома («15А»), но не «к» из «25к1»: это корпус, и он разбирается
    # следующей группой.
    r"(?P<house>\s*,\s*(?:д(?:ом)?\.?\s*)?\d{1,4}(?:[А-Яа-яA-Za-z](?!\s*\d))?"
    r"(?:\s*,?\s*(?:корп(?:ус)?|к|стр(?:оение)?|литера?)\.?\s*\d{1,3}[А-Яа-я]?)?"
    r"(?:\s*,?\s*(?:оф(?:ис)?|пом(?:ещение)?|каб)\.?\s*\d{1,4}[А-Яа-я]?)?)?",
    re.IGNORECASE,
)

#: Название компании обрывается перед реквизитами. Без этого «ИП ГАВРИКОВ
#: МИХАИЛ ВАЛЕРЬЕВИЧ ИНН 4023153177» проходило целиком и обрезалось по длине —
#: посреди ИНН. Номер, укороченный на две цифры, — это не «примерно верно», это
#: другой номер.
_REGISTRY_TAIL_RE = re.compile(r"\s*(?:ИНН|ОГРНИП|ОГРН|КПП|БИК)\b.*$", re.IGNORECASE)

_INVISIBLE = ("script", "style", "noscript", "template", "svg")

#: Заголовки и пункты меню, которые есть у всех и не говорят об услуге ничего.
_GENERIC_HEADINGS = frozenset(
    [
        "главная", "о нас", "о компании", "контакты", "отзывы", "новости", "блог",
        "цены", "прайс", "прайс-лист", "услуги", "каталог", "галерея", "портфолио",
        "наши работы", "вопросы и ответы", "faq", "доставка", "оплата", "акции",
        "меню", "корзина", "поиск", "войти", "регистрация", "политика",
        "политика конфиденциальности", "карта сайта", "вакансии", "сотрудничество",
        "菜单",
    ]
)

#: Слова, по которым узнаётся пункт навигации, а не услуга.
#:
#: Проверка идёт по вхождению, а не по точному совпадению, и это исправление
#: прямой поломки. Точный список ловил «услуги», но пропускал «наши услуги»,
#: «связаться с нами» и «о нашей команде» — и всё это уезжало в бриф как
#: «что продаём», а оттуда в маски для Вордстата. Система собирала частотность
#: по пункту меню.
_NAVIGATION_MARKERS = (
    "о нас",
    "о компании",
    "о команде",
    "наша команда",
    "о нашей",
    "связаться",
    "свяжитесь",
    "контакт",
    "написать нам",
    "позвонить",
    "заказать звонок",
    "обратный звонок",
    "оставить заявку",
    "наши услуги",
    "наши работы",
    "наши проекты",
    "проекты",
    "портфолио",
    "галере",
    "отзыв",
    "новост",
    "блог",
    "статьи",
    "вакансии",
    "карьера",
    "доставка",
    "оплата",
    "гарантии и возврат",
    "политик",
    "соглашение",
    "карта сайта",
    "корзина",
    "личный кабинет",
    "войти",
    "регистрация",
    "сотрудничеств",
    "партнёр",
    "партнер",
    "франшиз",
    "вопрос",
    "faq",
    "главная",
    "меню",
    "подробнее",
    "смотреть все",
    "все услуги",
)

#: Контакт в тексте ссылки. Телефон и почта в меню — обычное дело, и услугой
#: они не являются ни при каких обстоятельствах.
_CONTACT_IN_TEXT = re.compile(r"@|(?:\+?\d[\s\-()]*){7,}")

_MESSENGER_HOSTS = {
    "Telegram": ("t.me/", "telegram.me", "tg://"),
    "WhatsApp": ("wa.me/", "whatsapp://", "api.whatsapp.com"),
    "MAX": ("max.ru/", "max://"),
    "ВКонтакте": ("vk.com/",),
}


@dataclass(frozen=True, slots=True)
class Question:
    """Что нужно спросить у клиента: сайт на это не отвечает."""

    key: str
    text: str
    #: Почему без ответа не обойтись. Вопрос без обоснования выглядит анкетой
    #: ради анкеты, и его пропускают.
    why: str


@dataclass(frozen=True, slots=True)
class ClientProfile:
    """Что удалось прочитать на сайте клиента."""

    company: str | None = None
    city: str | None = None
    niche_key: str | None = None
    niche_label: str | None = None
    services: tuple[str, ...] = field(default_factory=tuple)
    prices: tuple[str, ...] = field(default_factory=tuple)
    phones: tuple[str, ...] = field(default_factory=tuple)
    emails: tuple[str, ...] = field(default_factory=tuple)
    messengers: tuple[str, ...] = field(default_factory=tuple)
    address: str | None = None
    company_details: str | None = None
    working_hours: str | None = None

    @property
    def filled(self) -> int:
        """Сколько полей анкеты удалось заполнить."""
        return sum(
            1
            for value in (
                self.company,
                self.city,
                self.niche_key,
                self.services,
                self.prices,
                self.phones,
                self.emails,
                self.messengers,
                self.address,
                self.company_details,
                self.working_hours,
            )
            if value
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "company": self.company,
            "city": self.city,
            "niche_key": self.niche_key,
            "niche_label": self.niche_label,
            "services": list(self.services),
            "prices": list(self.prices),
            "phones": list(self.phones),
            "emails": list(self.emails),
            "messengers": list(self.messengers),
            "address": self.address,
            "company_details": self.company_details,
            "working_hours": self.working_hours,
        }


def from_stored(data: dict[str, object] | None) -> ClientProfile:
    """Восстанавливает анкету из сохранённого вида."""
    if not data:
        return ClientProfile()

    def text(key: str) -> str | None:
        value = data.get(key)
        return value if isinstance(value, str) and value else None

    def items(key: str) -> tuple[str, ...]:
        value = data.get(key)
        return tuple(str(item) for item in value) if isinstance(value, list) else ()

    return ClientProfile(
        company=text("company"),
        city=text("city"),
        niche_key=text("niche_key"),
        niche_label=text("niche_label"),
        services=items("services"),
        prices=items("prices"),
        phones=items("phones"),
        emails=items("emails"),
        messengers=items("messengers"),
        address=text("address"),
        company_details=text("company_details"),
        working_hours=text("working_hours"),
    )


def extract(html: str) -> ClientProfile:
    """Читает анкету со страницы клиента."""
    tree = HTMLParser(html)

    hrefs = " ".join(
        node.attributes.get("href") or "" for node in tree.css("a[href]")
    ).lower()

    for hidden in tree.css(",".join(_INVISIBLE)):
        hidden.decompose()

    text = " ".join(tree.text(separator=" ").split())
    title = tree.css_first("title")
    title_text = title.text().strip() if title else ""

    headings = [node.text().strip() for node in tree.css("h1, h2, h3")]
    links = [node.text().strip() for node in tree.css("nav a, header a, footer a")]

    city = _city(text)
    niche = _niche(f"{title_text} {' '.join(headings)} {text[:4000]}")

    return ClientProfile(
        company=_company(tree, title_text, text),
        city=city,
        niche_key=niche.key if niche else None,
        niche_label=niche.label if niche else None,
        services=_services(headings, links, city),
        prices=_unique(_PRICE_RE.findall(text))[:5],
        phones=_unique(match.strip() for match in _PHONE_RE.findall(text))[:5],
        emails=_unique(_EMAIL_RE.findall(text))[:3],
        messengers=tuple(
            name for name, marks in _MESSENGER_HOSTS.items() if any(m in hrefs for m in marks)
        ),
        address=_address(text),
        company_details=_details(text),
        working_hours=_hours(text),
    )


def _unique(values: Iterable[object]) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values:
        item = " ".join(str(value).split())
        if item and item not in seen:
            seen.append(item)
    return tuple(seen)


def _company(tree: HTMLParser, title: str, text: str) -> str | None:
    """Название компании.

    Порядок источников — от надёжного к правдоподобному. Юрлицо в подвале
    указано однозначно; название сайта из разметки ставит владелец; хвост
    заголовка вкладки после тире — уже догадка, но чаще всего верная.
    """
    legal = _COMPANY_RE.search(text)
    if legal:
        # Реквизиты в название не входят. Иначе строка обрезалась по длине —
        # посреди ИНН, и на экран уезжал номер, укороченный на две цифры.
        return _REGISTRY_TAIL_RE.sub("", legal.group(0)).strip(" ,;") or None

    site_name = tree.css_first('meta[property="og:site_name"]')
    if site_name:
        value = (site_name.attributes.get("content") or "").strip()
        if value:
            return value[:120]

    for separator in ("—", "–", "|", "»"):
        if separator in title:
            tail = title.rsplit(separator, 1)[1].strip()
            if 2 < len(tail) < 60:
                return tail

    return None


def _city(text: str) -> str | None:
    found = cities_in(text[:6000])
    return found[0] if found else None


def _niche(text: str) -> niches.Niche | None:
    """Угадывает нишу по словам страницы.

    Считаются попадания по основам: «стеклопакеты» и «стеклопакет» — одно слово.
    Порог в два разных слова нужен, чтобы клининг, моющий окна, не оказался
    оконной компанией.
    """
    words = {stem(word) for word in tokenize(text)}
    lowered = text.lower()

    best: niches.Niche | None = None
    best_hits = 0

    for niche in niches.NICHES:
        hits = 0
        for keyword in niche.keywords:
            if " " in keyword:
                hits += 1 if keyword in lowered else 0
            else:
                hits += 1 if stem(keyword) in words else 0

        if hits > best_hits:
            best, best_hits = niche, hits

    return best if best_hits >= NICHE_HITS_NEEDED else None


def is_service(text: str) -> bool:
    """Похоже ли это на название услуги.

    Проверка нужна в двух местах, и потому она публичная. Первое — здесь, при
    чтении сайта: в меню рядом с услугами стоят «Контакты», «О нас» и телефон.
    Второе — при построении масок для Вордстата: бриф заполняет и человек, и
    вставить туда он может что угодно.

    Второе место важнее первого. Ошибка в анкете клиента — это неверная
    строчка на экране, которую видно. Та же ошибка в маске — это потраченный
    запрос из сотни в час и сотня фраз про чужую тему в ядре, а заметить её
    можно только вручную перечитав список.
    """
    item = " ".join(text.split()).strip(" -–—:·|").lower()

    if len(item) < 3:
        return False
    if item in _GENERIC_HEADINGS:
        return False
    if _CONTACT_IN_TEXT.search(item):
        return False
    return all(marker not in item for marker in _NAVIGATION_MARKERS)


def _services(headings: list[str], links: list[str], city: str | None) -> tuple[str, ...]:
    """Услуги: заголовки страницы и пункты меню, кроме общих слов.

    Город из названия услуги убирается: «Натяжные потолки в Твери» — это всё
    та же услуга, а в бриф город попадёт отдельным полем и попал бы дважды.
    """
    result: list[str] = []

    for raw in headings + links:
        item = " ".join(raw.split())
        if city:
            item = re.sub(rf"\s+в\s+{re.escape(city)}\w*", "", item, flags=re.IGNORECASE)
        item = item.strip(" -–—:·|")

        if not 3 <= len(item) <= 60:
            continue
        if not is_service(item):
            continue
        if any(char.isdigit() for char in item) and "₽" in item:
            continue
        if item not in result:
            result.append(item)

    return tuple(result[:MAX_SERVICES])


def _address(text: str) -> str | None:
    """Адрес одной строкой — или ничего.

    Половина адреса хуже, чем его отсутствие: по обрывку нельзя ни приехать,
    ни проверить, а выглядит он как данные. Поэтому найденное проверяется на
    осмысленность, и сомнительное отбрасывается.
    """
    for match in _ADDRESS_RE.finditer(text):
        found = " ".join(match.group(0).split()).strip(" ,;·|-")
        if len(found) > 120:
            continue
        # Пункт меню рядом с типом улицы — обычное дело: «Контакты», «Проезд».
        # Название улицы без дома ещё бывает полезно, кусок навигации — нет.
        if not is_service(found) and match.group("house") is None:
            continue
        if match.group("after") is None and match.group("house") is None:
            continue
        return found
    return None


def _details(text: str) -> str | None:
    match = _INN_RE.search(text)
    return " ".join(match.group(0).split()) if match else None


def _hours(text: str) -> str | None:
    match = _HOURS_RE.search(text)
    return " ".join(match.group(0).split())[:120] if match else None


#: Вопросы, ответы на которые не написаны ни на одном сайте.
#:
#: Это не анкета «для порядка». На этих числах стоит весь расчёт экономики, и
#: подставить вместо них правдоподобные значения — та самая ошибка, от которой
#: расчёт защищается тремя состояниями достоверности: лучше показать «не
#: посчитано», чем красивую цифру, взятую из воздуха.
UNIVERSAL_QUESTIONS: tuple[Question, ...] = (
    Question(
        key="average_check",
        text="Какой средний чек и сколько остаётся с продажи после всех расходов?",
        why="Без этого нельзя сказать, какая цена заявки для клиента приемлема, — "
        "а значит, и оценить, окупится ли реклама вообще.",
    ),
    Question(
        key="lead_to_sale",
        text="Сколько обращений из десяти доходит до оплаты?",
        why="Заявка и продажа — разные вещи. Реклама, дешёвая по заявкам, может "
        "оказаться убыточной по продажам, и наоборот.",
    ),
    Question(
        key="counts_as_lead",
        text="Что клиент считает заявкой: звонок, форму, сообщение в мессенджер?",
        why="По этому настраиваются цели в Метрике. Ошибка здесь означает, что "
        "Директ будет обучаться не на том действии.",
    ),
    Question(
        key="not_selling",
        text="Чего клиент точно не делает, хотя его об этом спрашивают?",
        why="Отсюда берутся минус-слова. Сайт про это молчит: там пишут, что "
        "делают, а не чего не делают.",
    ),
    Question(
        key="capacity",
        text="Сколько заявок в неделю клиент способен обработать?",
        why="Реклама, которая приводит больше заявок, чем успевают обработать, "
        "тратит бюджет на людей, которым не перезвонят.",
    ),
    Question(
        key="where_leads_go",
        text="Куда попадают заявки: CRM, почта, телефон?",
        why="Без этого нельзя сверить рекламу с продажами и придётся судить об "
        "успехе по кликам.",
    ),
)


def open_questions(profile: ClientProfile) -> tuple[Question, ...]:
    """Что осталось спросить у человека после чтения сайта.

    Вопросы про то, что на сайте не нашлось, идут первыми: они закрывают
    конкретный пробел и отвечаются за секунду. Дальше — общие: их задают всегда,
    сколько бы ни было написано на сайте.
    """
    gaps: list[Question] = []

    if not profile.city:
        gaps.append(
            Question(
                key="city",
                text="В каком городе и на какую территорию работает клиент?",
                why="На сайте города нет, а показывать рекламу по всей стране "
                "для местной услуги — это оплаченные клики из чужих регионов.",
            )
        )

    if not profile.niche_key:
        gaps.append(
            Question(
                key="niche",
                text="К какой нише отнести проект?",
                why="От ниши зависят требования модерации и стартовый набор "
                "минус-слов. По сайту определить не удалось.",
            )
        )

    if not profile.prices:
        gaps.append(
            Question(
                key="prices",
                text="Какие цены можно называть в объявлениях?",
                why="Цены на сайте не нашлись. Объявление с ценой отсеивает тех, "
                "кто всё равно не купит, — и клики за них не тратятся.",
            )
        )

    if not profile.phones and not profile.messengers:
        gaps.append(
            Question(
                key="contacts",
                text="Как с клиентом связываются: телефон, мессенджер, форма?",
                why="Контактов на странице не нашлось. Если связаться не с кем, "
                "реклама приводит людей в тупик.",
            )
        )

    return tuple(gaps) + UNIVERSAL_QUESTIONS


def niche_questions(niche_key: str | None) -> tuple[Question, ...]:
    """Вопросы, которые в этой нише стоит задать отдельно."""
    niche = niches.get(niche_key)
    if niche is None:
        return ()

    return tuple(
        Question(key=f"{niche.key}_{index}", text=note, why="Особенность ниши: " + niche.label)
        for index, note in enumerate(niche.notes)
    )
