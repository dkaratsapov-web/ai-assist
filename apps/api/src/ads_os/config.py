"""Конфигурация приложения.

Все настройки приходят из окружения. Секреты в коде и в репозитории не
появляются никогда (v0.3 §59, §94) — образец переменных лежит в `.env.example`.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnv = "development"
    app_base_url: str = "http://localhost:3000"
    log_level: str = "info"

    database_url: str = "postgresql+asyncpg://ads_os@127.0.0.1:5433/ads_os"
    database_echo: bool = False

    redis_url: str = "redis://localhost:6379/0"

    # Провайдер AI не выбран: разработка идёт на детерминированной заглушке,
    # конкретный провайдер подключается конфигурацией (v0.3 §98).
    ai_provider: str = "stub"
    # Для чувствительных данных внешний провайдер запрещён по умолчанию
    # (v0.4 §2.3). Ослабляется только явным решением по обработке ПДн.
    ai_sensitive_provider: str = "none"

    # До прохождения Security Acceptance Criteria (v0.3 §114) работа с рекламной
    # площадкой идёт только через заглушку, даже если токен уже получен
    # (v0.4 §2.1).
    ad_platform_adapter: Literal["mock", "yandex_direct"] = "mock"

    # ─── Вход через Яндекс ID ─────────────────────────────────────────────────
    # Паролей система не хранит: личность подтверждает Яндекс, второй фактор —
    # тоже его забота (v0.3 §91).
    yandex_oauth_client_id: str = ""
    yandex_oauth_client_secret: str = ""

    #: Сколько живёт сессия. Две недели — компромисс: не заставляет входить
    #: каждый день и не оставляет забытую вкладку открытой месяцами.
    session_ttl_days: int = 14

    #: Почта первого владельца. Работает ровно один раз: пока в организации нет
    #: ни одного владельца, вход с этой почтой создаёт его. Дальше участники
    #: заводятся только изнутри, и эта дверь закрывается сама.
    bootstrap_owner_email: str = ""

    # ─── Яндекс Директ ────────────────────────────────────────────────────────
    # Схема доступа — представитель: токен выпускается на один главный аккаунт,
    # а конкретный рекламодатель указывается в каждом запросе заголовком
    # Client-Login. Отдельный токен на каждого клиента не нужен.
    #
    # Значения приходят из окружения и в репозиторий не попадают никогда: токен
    # даёт доступ к чужим рекламным бюджетам (v0.3 §94).
    yandex_direct_token: str = ""
    #: Логин главного аккаунта, на который выпущен токен.
    yandex_direct_login: str = ""
    #: Песочница изолирована от настоящих данных. Пока не пройдены проверки
    #: безопасности, работа идёт только в ней — отсюда значение по умолчанию.
    yandex_direct_sandbox: bool = True

    # ─── Яндекс Метрика ───────────────────────────────────────────────────────
    # Отдельный доступ: он не приходит вместе с Директом. Счётчик клиента
    # открывается главному аккаунту гостевым доступом, после чего становится
    # «доверенным» и виден по тому же токену.
    yandex_metrica_token: str = ""

    autopilot_enabled: bool = Field(
        default=False,
        description="Глобальный выключатель автопилота. По умолчанию выключен (v0.4 §10).",
    )

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Настройки читаются один раз за процесс."""
    return Settings()
