"""Схемы API.

Эти модели — источник правды для контракта: из них FastAPI строит OpenAPI, а из
OpenAPI генерируются типы для фронтенда. Ручное дублирование DTO на стороне
TypeScript запрещено (v0.4 §18).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from ..models.audit import ModuleStatus
from ..models.project import MainConversion, ProjectStatus
from ..services.competitors import FeatureKey
from ..services.economics import Availability, EconomicsMode
from ..services.progress import StepKey, StepState


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

    category: str
    severity: str
    title: str
    action: str


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
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
