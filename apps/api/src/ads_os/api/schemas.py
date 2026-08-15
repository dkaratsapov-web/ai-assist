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
from ..models.project import MainConversion, ProjectStatus
from ..services.competitors import FeatureKey
from ..services.economics import Availability, EconomicsMode
from ..services.progress import StepKey, StepState
from ..services.semantics import Intent
from ..services.strategy import BidStrategy, PlanStatus


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    website_url: str | None = Field(default=None, max_length=2048)
    primary_region: str | None = Field(default=None, max_length=120)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    website_url: str | None
    primary_region: str | None
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
    status: ProjectStatus | None = None

    #: Версия, на которой пользователь редактировал (v0.4 §100).
    expected_version: int | None = None


class ProjectList(BaseModel):
    items: list[ProjectRead]
    total: int


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
    version: int


class EconomicsSummaryRead(BaseModel):
    mode: EconomicsMode
    can_optimize_by_sales: bool
    cta: str | None
    missing_required: list[str]
    missing_recommended: list[str]

    gross_profit_per_sale: MetricRead
    break_even_cac: MetricRead
    break_even_cpl: MetricRead
    break_even_roas: MetricRead
    target_cac: MetricRead
    target_cpl: MetricRead
    target_roas: MetricRead
    monthly_leads_capacity: MetricRead
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


class CompetitorRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    url: str
    title: str | None
    status: ModuleStatus
    #: Признак → есть или нет. Пустой словарь означает «ещё не проверяли».
    features: dict[str, bool]
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


class ComparisonRead(BaseModel):
    project_id: uuid.UUID
    #: Проверялся ли наш сайт. Без этого колонка «у вас» читалась бы как
    #: «у вас ничего нет», хотя мы просто не смотрели.
    own_site_checked: bool
    rivals_checked: int
    summary: str | None
    rows: list[FeatureRowRead]


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


class OrganizationRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    projects_count: int
    members: list[MemberRead]
    plan: PlanRead | None
    #: Режим работы стенда. Показывается прямо: на заглушках результаты не
    #: являются выводами настоящей модели и не касаются рекламного кабинета.
    app_env: str
    ai_provider: str
    ad_platform_adapter: str


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


class KeywordUpdate(BaseModel):
    intent: Intent


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


class MinusWordRead(BaseModel):
    id: uuid.UUID
    word: str


class MinusWordList(BaseModel):
    items: list[MinusWordRead]
    #: Предложения из разобранных фраз, ещё не добавленные в список.
    suggestions: list[MinusWordSuggestionRead]
    total: int


class MinusWordCreate(BaseModel):
    word: str = Field(min_length=2, max_length=60)
