"""Прогресс проекта по каноническому жизненному циклу (v0.4 §3).

Десять шагов — единственное представление порядка работы. В v0.3 их было три
разных (8, 10 и 12 шагов в разных разделах), и это была не косметическая
проблема: интерфейс, бот и рекомендации спорили бы о том, где находится проект.

Модуль намеренно чистый: он получает уже собранные факты и возвращает состояние
шагов. Ни базы, ни сети — иначе одно и то же состояние считалось бы по-разному
на сервере и в боте.

Правило, которому подчинён весь расчёт: шаг считается сделанным только тогда,
когда для него есть данные. Никаких «наверное, уже сделано»: пустой прогресс
честнее нарисованного.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .economics import EconomicsMode


class StepState(StrEnum):
    """Состояние шага. Совпадает с состояниями компонента WorkflowStepper."""

    COMPLETED = "completed"
    ACTIVE = "active"
    WAITING = "waiting"
    BLOCKED = "blocked"
    ERROR = "error"


class StepKey(StrEnum):
    """Ключи шагов. Порядок объявления — это и есть порядок работы."""

    ONBOARDING = "onboarding"
    RESEARCH = "research"
    ECONOMICS = "economics"
    STRATEGY = "strategy"
    BUILD = "build"
    VALIDATE = "validate"
    LAUNCH = "launch"
    MEASURE = "measure"
    OPTIMIZE = "optimize"
    SCALE = "scale"


#: Подписи шагов. Дублируют словарь design tokens намеренно: у бота нет доступа
#: к CSS, а называться шаг должен одинаково везде.
STEP_LABELS: dict[StepKey, str] = {
    StepKey.ONBOARDING: "Онбординг",
    StepKey.RESEARCH: "Исследование",
    StepKey.ECONOMICS: "Экономика",
    StepKey.STRATEGY: "Стратегия",
    StepKey.BUILD: "Сборка",
    StepKey.VALIDATE: "Проверка",
    StepKey.LAUNCH: "Запуск",
    StepKey.MEASURE: "Измерение",
    StepKey.OPTIMIZE: "Оптимизация",
    StepKey.SCALE: "Рост и масштаб",
}


@dataclass(frozen=True, slots=True)
class ProgressInput:
    """Факты, по которым определяется прогресс.

    Ровно то, что система знает сейчас. По мере появления модулей список
    расширяется, а правила ниже уточняются — но состав фактов всегда явный, а не
    «посмотрим в базе».
    """

    has_website: bool = False
    #: Аудит сайта: завершён, выполняется, упал или не запускался.
    audit_status: str | None = None
    #: Есть ли критические находки. Они запрещают запуск (v0.3 §15).
    audit_has_blocking_issues: bool = False
    economics_mode: EconomicsMode = EconomicsMode.INSUFFICIENT
    #: Подключён ли рекламный кабинет. До проверок безопасности — всегда False
    #: (v0.4 §2.1).
    ad_account_connected: bool = False
    has_campaigns: bool = False
    has_performance_data: bool = False


@dataclass(frozen=True, slots=True)
class Step:
    key: StepKey
    label: str
    state: StepState
    #: Что нужно сделать, чтобы шаг сдвинулся. Пусто у завершённых шагов.
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class Progress:
    steps: tuple[Step, ...]
    #: Шаг, на котором проект находится сейчас. Именно его показывают первым и
    #: про него спрашивает бот.
    current: StepKey
    completed_count: int
    #: Одно предложение о том, что делать дальше. Отсутствует, только когда
    #: сделано всё.
    next_action: str | None


def evaluate(data: ProgressInput) -> Progress:
    """Определяет состояние всех десяти шагов."""
    steps: list[Step] = []

    # 1. Онбординг. Проект создан — значит шаг пройден. Адрес сайта не
    # обязателен: бывает реклама без сайта, и блокировать её нельзя.
    steps.append(_step(StepKey.ONBOARDING, StepState.COMPLETED))

    # 2. Исследование. Пока это только аудит сайта; анализ конкурентов добавится
    # сюда же и потребует пересмотра правила.
    steps.append(_research(data))

    # 3. Экономика. Ограниченный режим — не ошибка и не «не сделано»: проект
    # ведётся, но без оптимизации по продажам (v0.4 §5).
    steps.append(_economics(data))

    # 4. Стратегия и далее — модули ещё не построены. Показывать их как
    # «ожидает» честнее, чем прятать: пользователь видит весь путь целиком.
    blocked_reason = _launch_blocker(data)

    steps.append(
        _step(
            StepKey.STRATEGY,
            StepState.WAITING,
            "Появится после того, как будут готовы исследование и экономика",
        )
    )
    steps.append(_step(StepKey.BUILD, StepState.WAITING, "Требует стратегии"))
    steps.append(_step(StepKey.VALIDATE, StepState.WAITING, "Требует собранных кампаний"))

    steps.append(
        _step(StepKey.LAUNCH, StepState.BLOCKED, blocked_reason)
        if blocked_reason
        else _step(StepKey.LAUNCH, StepState.WAITING, "Требует проверенных кампаний")
    )

    steps.append(
        _step(
            StepKey.MEASURE,
            StepState.COMPLETED if data.has_performance_data else StepState.WAITING,
            None if data.has_performance_data else "Данные появятся после запуска кампаний",
        )
    )
    steps.append(_step(StepKey.OPTIMIZE, StepState.WAITING, "Требует накопленной статистики"))
    steps.append(_step(StepKey.SCALE, StepState.WAITING, "Требует подтверждённых гипотез"))

    current = _current(steps)
    return Progress(
        steps=tuple(steps),
        current=current,
        completed_count=sum(1 for s in steps if s.state is StepState.COMPLETED),
        next_action=_next_action(steps, current),
    )


def _research(data: ProgressInput) -> Step:
    if not data.has_website:
        # «Ожидает», а не «в процессе», значило бы, что мы ждём чего-то своего.
        # Здесь ждём действия пользователя, и оно ему доступно прямо сейчас.
        return _step(
            StepKey.RESEARCH,
            StepState.ACTIVE,
            "Укажите адрес сайта — без него проверять нечего",
        )

    if data.audit_status == "completed":
        # Критические находки не отменяют самого исследования: оно выполнено,
        # результат получен. Запуск блокируется отдельным шагом.
        return _step(StepKey.RESEARCH, StepState.COMPLETED)

    if data.audit_status in ("queued", "running"):
        return _step(StepKey.RESEARCH, StepState.ACTIVE, "Проверяем сайт")

    if data.audit_status == "failed":
        return _step(
            StepKey.RESEARCH,
            StepState.ERROR,
            "Сайт не удалось проверить — запустите проверку заново",
        )

    return _step(StepKey.RESEARCH, StepState.ACTIVE, "Запустите проверку сайта")


def _economics(data: ProgressInput) -> Step:
    if data.economics_mode is EconomicsMode.COMPLETE:
        return _step(StepKey.ECONOMICS, StepState.COMPLETED)

    if data.economics_mode is EconomicsMode.LIMITED:
        return _step(
            StepKey.ECONOMICS,
            StepState.ACTIVE,
            "Заполнена частично: без маржи и конверсии в продажу считается только CPL",
        )

    return _step(
        StepKey.ECONOMICS,
        StepState.ACTIVE,
        "Укажите месячный бюджет и средний чек",
    )


def _launch_blocker(data: ProgressInput) -> str | None:
    """Причина, по которой запуск запрещён. None — запрета нет.

    Формулировка прямая: мягкая подводит к мысли, что запрет можно обойти.
    """
    if data.audit_has_blocking_issues:
        return "Запуск закрыт: на сайте есть критические замечания"
    if not data.ad_account_connected:
        return "Рекламный кабинет не подключён"
    return None


def _current(steps: list[Step]) -> StepKey:
    """Текущий шаг — первый незавершённый.

    Шаг с ошибкой считается текущим: чинить нужно его, а не идти дальше.
    """
    for step in steps:
        if step.state in (StepState.ACTIVE, StepState.ERROR):
            return step.key
    for step in steps:
        if step.state is not StepState.COMPLETED:
            return step.key
    return steps[-1].key


def _next_action(steps: list[Step], current: StepKey) -> str | None:
    for step in steps:
        if step.key is current:
            return step.hint
    return None


def _step(key: StepKey, state: StepState, hint: str | None = None) -> Step:
    return Step(key=key, label=STEP_LABELS[key], state=state, hint=hint)
