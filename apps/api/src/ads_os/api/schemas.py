"""Схемы API.

Эти модели — источник правды для контракта: из них FastAPI строит OpenAPI, а из
OpenAPI генерируются типы для фронтенда. Ручное дублирование DTO на стороне
TypeScript запрещено (v0.4 §18).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..models.activity import ActivityAction
from ..models.audit import ModuleStatus
from ..models.notification import NotificationKind, NotificationLevel
from ..models.project import MainConversion, ProjectStatus
from ..services.ads import Problem
from ..services.cleanup import Reason
from ..services.competitors import FeatureKey
from ..services.economics import Availability, EconomicsMode
from ..services.progress import StepKey, StepState
from ..services.semantics import Intent
from ..services.strategy import BidStrategy, PlanStatus


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    website_url: str | None = Field(default=None, max_length=2048)
    primary_region: str | None = Field(default=None, max_length=120)
    niche: str | None = Field(default=None, max_length=50)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    website_url: str | None
    primary_region: str | None
    niche: str | None
    status: ProjectStatus
    version: int
    created_at: datetime
    updated_at: datetime


class ProjectUpdate(BaseModel):
    """Изменение проекта.

    Все поля необязательные: приходит только то, что меняют. Отличить
    «не передано» от «очищено» позволяет `exclude_unset` при разборе.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    website_url: str | None = Field(default=None, max_length=2048)
    primary_region: str | None = Field(default=None, max_length=120)
    niche: str | None = Field(default=None, max_length=50)
    status: ProjectStatus | None = None

    #: Версия, на которой пользователь редактировал (v0.4 §100).
    expected_version: int | None = None


class ProjectList(BaseModel):
    items: list[ProjectRead]
    total: int


class NicheRequirementRead(BaseModel):
    """Требование площадки к посадочной в этой нише."""

    key: str
    title: str
    hint: str
    blocking: bool


class NicheRead(BaseModel):
    """Шаблон ниши.

    Цифр экономики здесь нет намеренно: конверсия и цена клика зависят от
    региона, сезона и самого сайта сильнее, чем от отрасли, и отраслевое
    среднее в поле проекта выглядело бы как факт о бизнесе клиента.
    """

    key: str
    label: str
    minus_words: list[str]
    requirements: list[NicheRequirementRead]
    main_conversion: MainConversion | None
    notes: list[str]


class NicheList(BaseModel):
    items: list[NicheRead]


class StepRead(BaseModel):
    """Шаг канонического жизненного цикла (v0.4 §3)."""

    key: StepKey
    label: str
    state: StepState
    #: Что сделать, чтобы шаг сдвинулся. У завершённых шагов пусто.
    hint: str | None = None


class ProgressRead(BaseModel):
    """Где находится проект и что делать дальше.

    Считается на сервере, а не в интерфейсе: то же самое понадобится боту, и
    два независимых расчёта неизбежно разошлись бы.
    """

    project_id: uuid.UUID
    steps: list[StepRead]
    current: StepKey
    completed_count: int
    total_count: int
    next_action: str | None


class ProjectSummaryRead(BaseModel):
    """Строка проекта на главном экране.

    Собирается на сервере одним запросом на все проекты. Собирать её в браузере
    значило бы дёргать по четыре запроса на каждый проект — и показывать
    страницу, которая тем медленнее, чем больше клиентов у агентства.
    """

    id: uuid.UUID
    name: str
    website_url: str | None
    status: ProjectStatus

    current_step: StepKey
    current_step_label: str
    completed_count: int
    total_count: int
    next_action: str | None

    audit_status: ModuleStatus | None
    audit_score: int | None
    #: Можно ли запускать рекламу. Критические находки это запрещают (v0.3 §15).
    can_launch: bool
    economics_mode: EconomicsMode
    competitors_checked: int


class OverviewRead(BaseModel):
    """Сводка по всем проектам.

    Намеренно не содержит расходов, лидов и продаж: рекламный кабинет не
    подключён, и любые цифры здесь были бы выдуманными. Поле
    `ad_platform_connected` существует ровно для того, чтобы интерфейс сказал
    об этом прямо, а не рисовал нули (v0.3 §140).
    """

    projects: list[ProjectSummaryRead]
    total: int
    #: Сколько проектов ждут действия специалиста.
    needs_attention: int
    ad_platform_connected: bool


class EconomicsUpdate(BaseModel):
    """Ввод экономики.

    Все поля необязательные: проект не блокируется из-за незаполненной экономики
    (v0.4 §5). Полнота оценивается расчётом, а не валидацией запроса.
    """

    monthly_budget: Decimal | None = Field(default=None, gt=0)
    average_order_value: Decimal | None = Field(default=None, gt=0)
    expected_value: Decimal | None = Field(default=None, gt=0)
    main_conversion: MainConversion | None = None

    margin_percent: Decimal | None = Field(default=None, ge=0, le=100)
    lead_to_sale_rate: Decimal | None = Field(default=None, gt=0, le=1)
    target_cac: Decimal | None = Field(default=None, gt=0)
    target_cpl: Decimal | None = Field(default=None, gt=0)
    target_marketing_share: Decimal | None = Field(default=None, gt=0, le=1)

    #: Поля прогноза. Без них считается только ёмкость бюджета.
    expected_cpc: Decimal | None = Field(default=None, gt=0)
    site_conversion_rate: Decimal | None = Field(default=None, gt=0, le=1)

    #: Версия, на которой пользователь редактировал. Защищает от записи поверх
    #: чужого изменения (v0.4 §100).
    expected_version: int | None = None


class MetricRead(BaseModel):
    """Значение метрики вместе с оценкой достоверности.

    Состояния совпадают с состояниями карточки KPI в интерфейсе: одно и то же
    понятие не должно называться по-разному на разных концах системы.
    """

    value: Decimal | None
    availability: Availability
    reason: str | None = Field(
        default=None, description="Что заполнить, чтобы значение стало достоверным"
    )


class EconomicsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    monthly_budget: Decimal | None
    average_order_value: Decimal | None
    expected_value: Decimal | None
    main_conversion: MainConversion | None
    margin_percent: Decimal | None
    lead_to_sale_rate: Decimal | None
    target_cac: Decimal | None
    target_cpl: Decimal | None
    target_marketing_share: Decimal | None
    expected_cpc: Decimal | None
    site_conversion_rate: Decimal | None
    version: int


class EconomicsSummaryRead(BaseModel):
    mode: EconomicsMode
    can_optimize_by_sales: bool
    cta: str | None
    missing_required: list[str]
    missing_recommended: list[str]
    #: Незаполненные поля прогноза. Без них известна только ёмкость бюджета.
    missing_forecast: list[str]

    gross_profit_per_sale: MetricRead
    break_even_cac: MetricRead
    break_even_cpl: MetricRead
    break_even_roas: MetricRead
    target_cac: MetricRead
    target_cpl: MetricRead
    target_roas: MetricRead
    monthly_leads_capacity: MetricRead
    #: Сколько заявок ожидается на самом деле: бюджет → клики → заявки.
    #: Отличается от ёмкости бюджета: та отвечает «на сколько заявок хватит
    #: денег при целевой цене», а это — «сколько заявок будет».
    expected_monthly_clicks: MetricRead
    expected_monthly_leads: MetricRead
    monthly_sales_capacity: MetricRead
    projected_revenue: MetricRead
    projected_gross_profit: MetricRead


class EconomicsResponse(BaseModel):
    """Ответ экономики: введённые данные и производные величины отдельно.

    Разделение намеренное — интерфейс обязан отличать данные от вывода системы
    (v0.3 §140).
    """

    project_id: uuid.UUID
    input: EconomicsRead | None
    summary: EconomicsSummaryRead


class CompetitorCreate(BaseModel):
    url: str = Field(min_length=4, max_length=2048)
    #: Как вы называете этого конкурента. Если не задано — возьмётся заголовок
    #: его страницы.
    title: str | None = Field(default=None, max_length=300)


class RivalKindRead(BaseModel):
    """Что за сайт добавлен в конкуренты.

    Нужно ровно затем, чтобы сравнение не врало. У Авито всегда есть форма,
    цены и отзывы — просто потому, что это площадка, а не компания. Без
    пометки такое сравнение выглядит как разгромный проигрыш клиента.
    """

    #: competitor | aggregator | directory | marketplace | article |
    #: manufacturer | other
    kind: str = "other"
    label: str = "Не опознан"
    #: Почему именно так.
    reason: str = ""
    #: Что с этим делать.
    hint: str = ""
    #: Имеет ли смысл сравнивать посадочную с этим сайтом.
    comparable: bool = False
    #: known — узнан по адресу, model — разобрала модель, unknown — не вышло.
    source: str = "unknown"
    confidence: float = 0.0


class CompetitorRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    url: str
    title: str | None
    status: ModuleStatus
    #: Признак → есть или нет. Пустой словарь означает «ещё не проверяли».
    features: dict[str, bool]
    #: Вид сайта. Присутствует всегда — при неопознанном с `kind: other`.
    kind: RivalKindRead
    error_reason: str | None
    checked_at: datetime | None


class CompetitorList(BaseModel):
    items: list[CompetitorRead]
    total: int


class FeatureRowRead(BaseModel):
    """Строка таблицы сравнения."""

    key: FeatureKey
    label: str
    #: Зачем этот признак нужен. Признак без последствий для рекламы в таблице
    #: не показывается.
    why: str
    mine: bool
    rivals_with: int
    rivals_total: int
    #: Нет у нас, но есть у большинства конкурентов.
    is_gap: bool
    #: Есть у нас и меньше чем у половины конкурентов.
    is_advantage: bool


class SuggestionRead(BaseModel):
    """Кого предлагается добавить в конкуренты."""

    url: str
    title: str
    source: str
    #: Почему предлагается именно он. Адрес без объяснения не добавляют.
    reason: str


class SearchQueryRead(BaseModel):
    """Запрос, по которому в выдаче видно рекламодателей."""

    query: str
    url: str


class RivalSuggestionsRead(BaseModel):
    """Подсказки по конкурентам: из своей истории и через поиск."""

    #: Сайты, которые уже разбирались в других проектах той же ниши и города.
    known: list[SuggestionRead]
    #: Готовые запросы для поиска. Пусто, если не из чего их составить.
    queries: list[SearchQueryRead]
    #: Что сделать с этими запросами.
    hint: str
    #: Почему точного списка соперников по аукциону пока нет.
    why_manual: str
    #: Чего не хватает, чтобы подсказки заработали: ниши, региона, брифа.
    missing: list[str]


class RivalValueRead(BaseModel):
    """Условие у одного конкурента — как написано у него на странице."""

    title: str
    url: str
    value: str


class OfferRowRead(BaseModel):
    """Одно условие предложения: наше, их и вывод.

    Цитаты дословные. Пересказ чужого предложения своими словами превращает
    факт в мнение, а вся ценность такого сравнения в том, что его можно
    проверить, открыв сайт конкурента и найдя глазами ту же строку.
    """

    key: str
    label: str
    mine: str
    rivals: list[RivalValueRead]
    #: Вывод одной фразой. Пусто там, где из чисел ничего не следует.
    verdict: str
    is_gap: bool


class ComparisonRead(BaseModel):
    project_id: uuid.UUID
    #: Проверялся ли наш сайт. Без этого колонка «у вас» читалась бы как
    #: «у вас ничего нет», хотя мы просто не смотрели.
    own_site_checked: bool
    rivals_checked: int
    summary: str | None
    rows: list[FeatureRowRead]
    #: Предметное сравнение: цены, сроки, гарантии, что обещают бесплатно.
    #: Ради него сравнение и существует — по галочкам «есть форма» решение о
    #: том, чем отличаться от конкурента, принять нельзя.
    offer_rows: list[OfferRowRead]
    #: Есть ли у разобранных конкурентов хоть какие-то условия на страницах.
    offer_has_data: bool


class CurrentUserRead(BaseModel):
    """Кто вошёл. Ответ на вопрос интерфейса «показывать приложение или вход»."""

    id: uuid.UUID
    email: str
    full_name: str
    role: str
    organization_id: uuid.UUID
    organization_name: str


class SessionRead(BaseModel):
    """Один вход.

    Показывается человеку, чтобы он узнал свои устройства и заметил чужое.
    Полный User-Agent не хранится и не показывается: для узнавания достаточно
    браузера и системы, а точный отпечаток браузера — лишние данные.
    """

    id: uuid.UUID
    #: Та ли это сессия, из которой пришёл запрос. Её нельзя завершить кнопкой
    #: «завершить» — для этого есть выход.
    is_current: bool
    device: str
    ip_address: str | None
    last_seen_at: datetime | None
    created_at: datetime
    expires_at: datetime


class SessionList(BaseModel):
    items: list[SessionRead]
    total: int


class MemberCreate(BaseModel):
    """Добавление участника.

    Пароля здесь нет и быть не может: вход идёт через Яндекс ID. Достаточно
    почты — по ней человек и будет опознан при входе.
    """

    email: str = Field(min_length=3, max_length=320)
    full_name: str = Field(min_length=1, max_length=200)
    role: Literal["owner", "specialist", "viewer"] = "specialist"


class MemberUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Literal["owner", "specialist", "viewer"] | None = None
    #: Отключение участника закрывает вход и завершает все его сессии.
    is_active: bool | None = None


class MemberRead(BaseModel):
    """Участник организации.

    Пароля и способов входа здесь нет: аутентификация появится отдельным срезом
    вместе с MFA (v0.3 §91).
    """

    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    #: Входил ли человек хоть раз. Пока нет — доступ выдан, но не использован.
    has_logged_in: bool
    last_login_at: datetime | None


class PlanRead(BaseModel):
    """Лимиты организации (v0.4 §13).

    Платёжная система в MVP не подключается, но потолки существуют с первого
    дня — иначе их некуда будет добавить, когда появится биллинг.
    """

    max_projects: int
    max_users: int
    ai_usage_limit: int
    crawler_pages_limit: int
    retention_days: int


class UsageRead(BaseModel):
    """Потребление за последние 30 дней вместе с лимитом.

    Окно скользящее, а не календарный месяц: лимит, обнуляющийся первого
    числа, позволяет израсходовать двойную норму за два дня на стыке.
    """

    crawler_pages: int
    crawler_pages_limit: int
    ai_tokens: int
    ai_tokens_limit: int


class OrganizationRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    projects_count: int
    members: list[MemberRead]
    plan: PlanRead | None
    usage: UsageRead
    #: Режим работы стенда. Показывается прямо: на заглушках результаты не
    #: являются выводами настоящей модели и не касаются рекламного кабинета.
    app_env: str
    ai_provider: str
    ad_platform_adapter: str


class AdPlatformAdvertiserRead(BaseModel):
    """Рекламодатель, доступный по нашему токену."""

    login: str
    name: str
    currency: str
    can_edit: bool


class AdPlatformStatusRead(BaseModel):
    """Состояние подключения к рекламной площадке.

    Единственный экран, где видно правду о доступе: какой адаптер работает,
    настоящие ли это деньги, отвечает ли площадка и сколько осталось баллов
    API. Выяснять это по косвенным признакам — верный способ однажды принять
    заглушку за боевой аккаунт.
    """

    adapter: str
    #: Работает ли адаптер с настоящими деньгами, а не с песочницей.
    is_live: bool
    #: Снят ли предохранитель боевого доступа (v0.4 §2.1).
    live_approved: bool
    #: Ответила ли площадка на пробный запрос.
    connected: bool
    #: Почему не ответила. Пусто при успехе.
    error: str | None = None
    advertisers: list[AdPlatformAdvertiserRead] = []
    #: Расход баллов API за сутки: израсходовано, осталось, предел.
    units_spent: int = 0
    units_rest: int = 0
    units_limit: int = 0
    #: Осталось меньше десятой части суточного лимита.
    units_low: bool = False


class ActivityRead(BaseModel):
    """Строка журнала.

    Имя автора и название объекта — копии на момент действия, а не ссылки.
    Человек может быть отключён, проект удалён, а запись обязана остаться
    читаемой.
    """

    id: uuid.UUID
    action: ActivityAction
    #: Готовая фраза для ленты: «создал проект», «изменил экономику проекта».
    action_label: str
    user_name: str
    subject: str
    project_id: uuid.UUID | None
    #: Пары «поле → было → стало». Пусто, если подробностей нет.
    details: dict[str, str]
    created_at: datetime


class ActivityList(BaseModel):
    items: list[ActivityRead]
    total: int


class HealthResponse(BaseModel):
    status: str
    app_env: str
    #: Провайдер AI. Показывается явно: на заглушке результаты не являются
    #: настоящими выводами модели.
    ai_provider: str
    #: Адаптер рекламной площадки. До прохождения проверок безопасности —
    #: только заглушка (v0.4 §2.1).
    ad_platform_adapter: str


class CategoryRead(BaseModel):
    """Оценка по одной категории аудита."""

    category: str
    score: int
    findings: list[str] = Field(default_factory=list)


class AuditIssueRead(BaseModel):
    """Находка аудита.

    Поле `action` обязательное: находка без понятного действия бесполезна.
    """

    #: Устойчивое имя проверки. Пусто у записей, сделанных до его появления.
    key: str | None = None
    category: str
    severity: str
    title: str
    action: str
    #: Отмечено человеком как неактуальное для этого проекта. На балл и вердикт
    #: не влияет — скрытие меняет только то, что показывается в работе.
    dismissed: bool = False
    dismissed_reason: str | None = None
    dismissed_by: str | None = None


class AuditChangesRead(BaseModel):
    """Что изменилось с прошлой проверки.

    Отвечает на вопрос, ради которого повторную проверку и запускают. Изменение
    балла на него не отвечает: балл мог вырасти, пока критическая проблема
    осталась на месте.
    """

    #: Сравнение проводилось. False означает, что сравнивать не с чем — это
    #: первая завершённая проверка, а не «изменений нет».
    compared: bool
    # Списки обязательны, а не со значением по умолчанию: иначе в контракте они
    # становятся необязательными, и клиент вынужден проверять каждый на
    # существование — при том, что сервер всегда их присылает.
    fixed: list[AuditIssueRead]
    #: Появившиеся замечания. Их выделяют отдельно: обычно это значит, что на
    #: сайте что-то сломали по дороге.
    appeared: list[AuditIssueRead]
    remaining: list[AuditIssueRead]


class AuditHistoryItem(BaseModel):
    """Одна прошлая проверка.

    Без списка находок: история отвечает на вопрос «стало лучше или хуже», а не
    «что именно сломано». За подробностями — в последний результат.
    """

    id: uuid.UUID
    status: ModuleStatus
    score: int | None
    verdict: str | None
    can_launch: bool
    error_reason: str | None
    finished_at: datetime | None
    created_at: datetime
    #: Насколько балл изменился по сравнению с предыдущей завершённой проверкой.
    #: None у самой первой и у незавершённых — сравнивать не с чем.
    score_delta: int | None
    #: Сколько замечаний исправлено и сколько появилось с прошлой проверки.
    fixed_count: int
    appeared_count: int


class AuditHistory(BaseModel):
    items: list[AuditHistoryItem]
    total: int


class ReviewNoteRead(BaseModel):
    """Одно замечание модели."""

    #: offer | objections | language | match | structure
    topic: str
    #: good | weak | missing
    grade: str
    what: str
    fix: str
    #: Цитата со страницы. Пустая, когда речь об отсутствующем.
    quote: str


class ReviewRead(BaseModel):
    """Мнение модели о странице.

    Отдельно от находок и от балла намеренно: это суждение, а не факт.
    Ошибиться модель может, и её ошибка не должна ни повышать балл, ни
    запрещать запуск.
    """

    #: Разбор выполнен. False — модель не подключена, недоступна или страница
    #: слишком пустая; тогда заполнено `reason`.
    available: bool
    #: Почему разбора нет. Пустое место человек читает как поломку.
    reason: str = ""
    summary: str = ""
    strongest: str = ""
    weakest: str = ""
    #: Насколько модель уверена, от 0 до 1.
    confidence: float = 0.0
    #: Какая модель отвечала. Через полгода это единственный способ понять,
    #: почему разборы разных проверок так не похожи.
    model: str = ""
    notes: list[ReviewNoteRead] = Field(default_factory=list)


class AuditRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    url: str
    final_url: str | None
    status: ModuleStatus
    score: int | None
    verdict: str | None
    metrica_counter: str | None
    error_reason: str | None
    categories: list[CategoryRead]
    issues: list[AuditIssueRead]
    #: Можно ли запускать рекламу. Критические находки это запрещают (v0.3 §15).
    can_launch: bool
    #: Что изменилось с прошлой завершённой проверки. None у незавершённых.
    changes: AuditChangesRead | None = None
    #: Мнение модели. Присутствует всегда — при отключённой модели с
    #: `available: false` и объяснением.
    review: ReviewRead
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class LaunchPlanRead(BaseModel):
    """План запуска: с какой стратегии начинать и сколько ждать выводов.

    Рядом с каждым числом идёт объяснение, откуда оно взялось. План без
    обоснования специалист не может ни принять осознанно, ни оспорить — а
    оспорить он должен уметь, потому что отвечает за бюджет он, а не система.
    """

    project_id: uuid.UUID
    status: PlanStatus
    #: Что мешает стартовать прямо сейчас. Пусто, если ничего не мешает.
    blockers: list[str]
    strategy: BidStrategy | None
    #: Название стратегии словами, как в интерфейсе Директа.
    strategy_label: str | None
    strategy_reason: str | None
    #: Ожидаемое число заявок в неделю при текущем бюджете и цене заявки.
    weekly_conversions: Decimal | None
    #: Хватает ли потока, чтобы автостратегия обучилась.
    learning_ready: bool | None
    #: Через сколько недель накопится статистика для выводов. `null` означает,
    #: что при таком объёме ждать пришлось бы неразумно долго.
    test_weeks: int | None
    test_budget: Decimal | None
    advice: list[str]


class DismissalCreate(BaseModel):
    """Отметка «замечание неактуально для этого проекта»."""

    issue_key: str
    #: Почему. Не обязательно, но именно это читает второй специалист через
    #: полгода, когда сомневается в решении.
    reason: str | None = Field(default=None, max_length=300)


class DismissalRead(BaseModel):
    issue_key: str
    reason: str | None
    dismissed_by: str
    created_at: datetime


class DismissalList(BaseModel):
    items: list[DismissalRead]
    total: int


class KeywordRead(BaseModel):
    id: uuid.UUID
    phrase: str
    frequency: int | None
    intent: Intent
    intent_label: str
    #: Слово, из-за которого фраза отнесена к этому типу. Пусто, если признаков
    #: не нашлось и сработало правило по умолчанию.
    trigger: str | None
    #: Вид мусора: другой город, поиск работы, «своими руками». Одного слова
    #: мало — «москва» само по себе не объясняет, почему фраза лишняя.
    reason: Reason | None = None
    reason_label: str | None = None
    #: Тип назначен человеком, а не словарём. Повторный разбор такие фразы не
    #: трогает.
    is_manual: bool
    cluster_name: str | None


class KeywordList(BaseModel):
    items: list[KeywordRead]
    total: int


class KeywordImport(BaseModel):
    """Вставленный список фраз."""

    text: str = Field(max_length=2_000_000)


class KeywordFileImport(BaseModel):
    """Выгрузка файлом.

    Содержимое приходит в base64, а не многочастной формой. Причина простая:
    так файл проходит тем же путём, что и вставленный текст, и не тянет за собой
    отдельную библиотеку разбора форм ради одной кнопки.
    """

    filename: str = Field(default="", max_length=260)
    content_base64: str = Field(max_length=14_000_000)


class KeywordUpdate(BaseModel):
    intent: Intent


class BriefUpdate(BaseModel):
    """Ответы на короткий бриф."""

    sells: str = Field(default="", max_length=2000)
    synonyms: str = Field(default="", max_length=2000)
    excludes: str = Field(default="", max_length=2000)
    cities: str = Field(default="", max_length=2000)


class QuestionRead(BaseModel):
    """Вопрос клиенту: сайт на него не отвечает."""

    key: str
    text: str
    #: Почему без ответа не обойтись. Вопрос без обоснования выглядит анкетой
    #: ради анкеты, и его пропускают.
    why: str
    #: Что ответили. Пусто — значит ещё не спрашивали или не записали.
    answer: str = ""


class AnswersUpdate(BaseModel):
    """Ответы на вопросы клиенту.

    Приходят те, что изменились, а не все сразу: поля сохраняются по мере
    заполнения, и присылать каждый раз всю анкету значило бы затирать ответ,
    который в этот момент правят во второй вкладке.
    """

    answers: dict[str, str] = Field(default_factory=dict)


class ClientProfileRead(BaseModel):
    """Что удалось прочитать на сайте клиента."""

    company: str | None
    city: str | None
    niche_key: str | None
    niche_label: str | None
    services: list[str]
    prices: list[str]
    phones: list[str]
    emails: list[str]
    messengers: list[str]
    address: str | None
    company_details: str | None
    working_hours: str | None


class OnboardingRead(BaseModel):
    """Онбординг: что система прочитала сама и что осталось спросить."""

    #: Была ли вообще проверка сайта. Без неё читать нечего, и это надо сказать
    #: прямо, а не показывать пустую анкету.
    has_audit: bool
    #: Адрес, с которого читали. Человек должен видеть источник: анкета,
    #: собранная с тестовой копии сайта, выглядит так же, как настоящая.
    source_url: str | None
    profile: ClientProfileRead
    #: Сколько полей удалось заполнить.
    filled: int
    #: Что из прочитанного ещё не перенесено в проект.
    can_apply: list[str]
    #: Вопросы клиенту: на них сайт не отвечает никогда.
    questions: list[QuestionRead]
    #: Вопросы, специфичные для угаданной ниши.
    niche_questions: list[QuestionRead]


class OnboardingApply(BaseModel):
    """Что из прочитанного перенести в проект.

    Поля выбираются по одному, а не «применить всё»: разбор ошибается, и
    человек должен иметь возможность взять город, но не взять нишу.
    """

    region: bool = False
    niche: bool = False
    #: Услуги и город — в бриф для сбора запросов.
    brief: bool = False


class MaskRead(BaseModel):
    """Строка, которую человек вставит в Вордстат."""

    query: str
    #: Зачем она нужна. Без этого список масок выглядит набором похожих строк,
    #: и половину пропускают как повтор.
    purpose: str


class BriefRead(BriefUpdate):
    """Бриф вместе с тем, что из него следует."""

    #: Регион проекта: в Вордстате его выбирают отдельно, и это важнее масок.
    region: str | None
    masks: list[MaskRead]
    steps: list[str]
    #: Почему сбор не делается сам. Человек всё равно спросит — лучше ответить
    #: сразу, чем оставить впечатление недоделанной кнопки.
    why_manual: str


class ImportSummary(BaseModel):
    """Итог разбора списка.

    Числа важнее списка: после загрузки трёх тысяч фраз человеку нужно понять
    масштаб, а не листать результат.
    """

    added: int
    updated: int
    #: Сколько строк не удалось разобрать: пустые, из одних цифр, мусор.
    skipped: int
    commercial: int
    informational: int
    irrelevant: int
    clusters: int
    #: Из чего складывается нецелевая часть. Без разбивки число «нецелевых: 480»
    #: остаётся числом: непонятно, вычистилось лишнее или вычистилось нужное.
    cleaned: list[CleanupGroupRead]


class CleanupGroupRead(BaseModel):
    """Одна причина, по которой фразы признаны нецелевыми."""

    reason: Reason
    label: str
    #: Что с этим делать. Для чужих городов — поправить регион, для остального —
    #: перенести слово в минус-список.
    hint: str
    phrases: int
    examples: list[str]


class ClusterRead(BaseModel):
    """Группа фраз под одно объявление."""

    name: str
    #: Общие основы, по которым фразы объединились. Это объяснение группировки:
    #: без него человек не может ни проверить её, ни поправить.
    core: list[str]
    phrases: int
    total_frequency: int


class ClusterList(BaseModel):
    items: list[ClusterRead]
    total: int


class MinusWordSuggestionRead(BaseModel):
    word: str
    #: Сколько фраз оно уводит в нецелевые.
    phrases: int
    examples: list[str]
    reason: Reason | None = None
    reason_label: str | None = None


class MinusWordRead(BaseModel):
    id: uuid.UUID
    word: str


class MinusWordList(BaseModel):
    items: list[MinusWordRead]
    #: Предложения из разобранных фраз, ещё не добавленные в список.
    suggestions: list[MinusWordSuggestionRead]
    #: Слова, которые специалист сам относил к нецелевым в других проектах.
    #: Словарь не знает ниши — а человек знает, и повторённое решение стоит
    #: заметить, а не заставлять принимать заново.
    learned: list[str]
    #: Стартовый набор: слова, которые минусуют почти всегда, плюс нишевые —
    #: если у проекта задана ниша. Как и остальные подсказки, ничего не
    #: добавляет само: отсечённый трафик, о котором человек не просил, заметить
    #: труднее всего.
    from_niche: list[str]
    total: int


class CrossMinusRead(BaseModel):
    """Что добавить к фразе, чтобы она не перехватывала чужие запросы."""

    phrase: str
    minus_words: list[str]
    #: Чьи запросы она иначе перехватывала бы. Без этого списка совет
    #: невозможно проверить и не понять, что сломается, если ему последовать.
    shadows: list[str]


class DuplicateRead(BaseModel):
    """Фразы, неразличимые для площадки."""

    phrases: list[str]


class CrossMinusResultRead(BaseModel):
    """Пересечения внутри ядра.

    Общая фраза, перехватывающая запросы уточнённой, — самая тихая утечка
    бюджета: в отчёте обе фразы получают показы, и по цифрам всё выглядит
    нормально.
    """

    items: list[CrossMinusRead]
    duplicates: list[DuplicateRead]
    analyzed: int


class MinusWordCreate(BaseModel):
    word: str = Field(min_length=2, max_length=60)


class MinusWordBulkCreate(BaseModel):
    """Несколько минус-слов разом.

    Стартовый набор ниши — это два десятка слов. Добавлять их по одному значит
    двадцать раз нажать и двадцать раз дождаться перепроверки ядра.
    """

    words: list[str] = Field(min_length=1, max_length=200)


class CleanupResult(BaseModel):
    """Итог чистки ядра."""

    #: Сколько фраз удалено или перемечено.
    affected: int
    #: Сколько осталось в проекте.
    remaining: int
    commercial: int
    informational: int
    irrelevant: int
    clusters: int


class AdViolationRead(BaseModel):
    """Что помешает объявлению выйти на показы."""

    problem: Problem
    field_name: str
    message: str


class SitelinkRead(BaseModel):
    """Быстрая ссылка объявления."""

    title: str
    url: str


class AdDraftRead(BaseModel):
    """Черновик объявления.

    Именно черновик: система делает механическую часть — подставляет фразу,
    собирает текст из фрагментов страницы и проверяет лимиты. Итоговый текст
    пишет специалист, у которого есть контекст.
    """

    cluster: str
    #: Куда вести эту группу. Подбирается по совпадению темы группы с
    #: заголовком проверенной страницы; при отсутствии совпадения — главная.
    landing_url: str
    title: str
    title_2: str | None
    text: str
    display_path: str | None
    callouts: list[str]
    #: Быстрые ссылки на разделы сайта, найденные на проверенной странице.
    sitelinks: list[SitelinkRead]
    keywords: list[str]
    violations: list[AdViolationRead]
    #: Пройдёт ли модерацию по проверяемым правилам. Не «хорошее объявление».
    is_ready: bool


class UtmNotesRead(BaseModel):
    """Как размечены ссылки и что об этом надо знать."""

    #: Пример готовой ссылки с подставленными значениями. Строка с
    #: фигурными скобками выглядит как ошибка, и это первый вопрос.
    example: str
    notes: list[str]


class AdDraftList(BaseModel):
    items: list[AdDraftRead]
    total: int
    #: Сколько черновиков без нарушений.
    ready: int
    #: Пусто, если аудит не проводился: без него неоткуда взять текст.
    source_note: str | None = None
    #: Разметка ссылок: пример и пояснения. Показывается рядом с
    #: черновиками, потому что именно эти ссылки уедут в кампанию.
    utm: UtmNotesRead


class NotificationRead(BaseModel):
    """Одно сообщение системы.

    Рядом с тем, что случилось, всегда стоит, что с этим делать. Уведомление
    без второго — это тревога без выхода, и от неё больше вреда, чем пользы.
    """

    id: uuid.UUID
    project_id: uuid.UUID | None
    project_name: str
    kind: NotificationKind
    level: NotificationLevel
    title: str
    body: str
    is_read: bool
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationRead]
    total: int
    #: Непрочитанных всего, а не в выдаче: это число показывается на колокольчике.
    unread: int


class AuditStart(BaseModel):
    """Запуск проверки.

    Без адреса проверяется главная страница проекта. С адресом — другая
    страница того же сайта.
    """

    url: str | None = Field(default=None, max_length=2048)


class AuditPageRead(BaseModel):
    """Проверенная страница проекта."""

    url: str
    #: Главная страница проекта. С неё начинают, и она открывается по умолчанию.
    is_primary: bool
    score: int | None
    verdict: str | None
    can_launch: bool
    status: ModuleStatus
    checked_at: datetime | None


class AuditPageList(BaseModel):
    items: list[AuditPageRead]
    total: int


class MinusWordSetRead(BaseModel):
    """Именованный набор минус-слов, общий для всех проектов."""

    id: uuid.UUID
    name: str
    words: list[str]
    created_at: datetime


class MinusWordSetList(BaseModel):
    items: list[MinusWordSetRead]
    total: int


class MinusWordSetCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    #: Слова набора. Пусто означает «взять текущие минус-слова проекта» —
    #: именно так набор чаще всего и заводят: сначала собрали в работе, потом
    #: решили сохранить.
    words: list[str] = Field(default_factory=list)
    source_project_id: uuid.UUID | None = None


class ApplySetResult(BaseModel):
    """Итог применения набора к проекту."""

    added: int
    #: Сколько слов уже были в проекте. Показывается отдельно: «добавлено 0»
    #: без этого числа читается как сбой, хотя означает «всё уже на месте».
    already_present: int


class SearchProjectRead(BaseModel):
    id: uuid.UUID
    name: str
    status: ProjectStatus


class SearchKeywordRead(BaseModel):
    """Найденная фраза вместе с проектом.

    Без указания проекта фраза не отвечает ни на один вопрос: «остекление
    балконов» есть у половины клиентов.
    """

    phrase: str
    frequency: int | None
    intent: Intent
    project_id: uuid.UUID
    project_name: str


class SearchResult(BaseModel):
    projects: list[SearchProjectRead]
    keywords: list[SearchKeywordRead]
