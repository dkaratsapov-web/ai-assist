"""Вход через Яндекс ID.

Мы не храним паролей вообще. Личность подтверждает Яндекс, а второй фактор —
его же забота, и там он у людей обычно уже настроен. Для системы, которая
управляет рекламными бюджетами, это заметно надёжнее собственной формы входа:
паролей, которые можно подобрать или украсть из нашей базы, просто не
существует.

Модуль отвечает только за разговор с Яндексом. Что делать с полученным
человеком — решает уровень выше.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
TOKEN_URL = "https://oauth.yandex.ru/token"
USER_INFO_URL = "https://login.yandex.ru/info"

#: Сколько ждём ответа Яндекса. Вход — интерактивная операция: висеть на ней
#: полминуты хуже, чем честно сказать «попробуйте ещё раз».
TIMEOUT_SECONDS = 10.0


class YandexAuthError(Exception):
    """Вход через Яндекс не состоялся.

    Причина пишется в лог, наружу уходит общая формулировка: детали ответа
    чужого сервиса пользователю ничего не объясняют.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class YandexUser:
    """Кто вошёл, по данным Яндекса."""

    id: str
    email: str
    display_name: str


def new_state() -> str:
    """Случайное значение против подмены ответа.

    Без него злоумышленник может подсунуть свой код авторизации и войти в
    систему под собой, но в чужой вкладке. Значение кладётся в куку и
    сверяется при возврате.
    """
    return secrets.token_urlsafe(24)


#: Права, которые запрашиваются при входе. Ровно два: опознать человека по
#: почте и показать его имя в интерфейсе.
#:
#: Список задан явно, а не отдан на откуп настройкам приложения. Без параметра
#: `scope` Яндекс запрашивает у человека все права, какие есть у приложения, —
#: и стоит однажды добавить туда доступ к Директу, как обычный вход начнёт
#: спрашивать разрешение на управление рекламными бюджетами. Человек, который
#: зашёл посмотреть отчёт, такого разрешения не давал и давать не должен, а
#: выданный токен оказался бы мощнее, чем нужно кому-либо для входа.
LOGIN_SCOPES = ("login:email", "login:info")


def authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    """Адрес, куда отправляем человека для входа."""
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": " ".join(LOGIN_SCOPES),
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


async def exchange_code(
    code: str, *, client_id: str, client_secret: str, redirect_uri: str
) -> str:
    """Меняет одноразовый код на токен доступа."""
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                },
            )
        except httpx.HTTPError as exc:
            raise YandexAuthError(f"сеть: {type(exc).__name__}") from exc

    if response.status_code != 200:
        raise YandexAuthError(f"обмен кода: код ответа {response.status_code}")

    token = response.json().get("access_token")
    if not token:
        raise YandexAuthError("обмен кода: в ответе нет токена")

    return str(token)


async def fetch_user(access_token: str) -> YandexUser:
    """Узнаёт, кто именно вошёл."""
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        try:
            response = await client.get(
                USER_INFO_URL,
                params={"format": "json"},
                headers={"Authorization": f"OAuth {access_token}"},
            )
        except httpx.HTTPError as exc:
            raise YandexAuthError(f"сеть: {type(exc).__name__}") from exc

    if response.status_code != 200:
        raise YandexAuthError(f"данные пользователя: код ответа {response.status_code}")

    data = response.json()

    # Почта может прийти в двух полях. Берём основную, иначе первую из списка:
    # без почты сопоставить человека с участником невозможно.
    email = data.get("default_email") or next(iter(data.get("emails") or []), None)
    if not email:
        raise YandexAuthError("аккаунт без почты")

    identifier = data.get("id")
    if not identifier:
        raise YandexAuthError("в ответе нет идентификатора пользователя")

    return YandexUser(
        id=str(identifier),
        email=str(email).strip().lower(),
        display_name=str(
            data.get("real_name") or data.get("display_name") or data.get("login") or email
        ),
    )


# Состояние второго фактора Яндекс нам не сообщает, и выводить его косвенно из
# других полей значит показывать догадку под видом факта. Поэтому в системе нет
# признака «MFA включён» у участника: второй фактор настраивается в аккаунте
# Яндекса, и там же проверяется (v0.3 §91).
