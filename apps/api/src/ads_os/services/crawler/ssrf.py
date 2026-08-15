"""Защита краулера от обращений внутрь инфраструктуры.

Краулер принимает произвольный URL от пользователя и сам ходит по сети. Это
готовый инструмент для доступа к внутренним адресам изнутри нашего же
периметра: к базе, к Redis, к сервису метаданных облака. Поэтому проверка
адреса — не украшение, а условие существования модуля (v0.3 §97, v0.4 §20).

Проверка выполняется дважды: до запроса и заново после каждого перенаправления.
Одной проверки недостаточно — публичный адрес может увести редиректом на
внутренний.

Остаточный риск, который кодом не закрывается: между проверкой имени и самим
подключением DNS-ответ может смениться на внутренний адрес. Поэтому ТЗ требует
ещё и сетевой изоляции воркера — это второй рубеж, а не дублирование первого.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})

#: Имена, за которыми в облаках стоит сервис метаданных с ключами доступа.
BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)

#: Диапазоны, куда краулеру ходить нельзя ни при каких условиях.
BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8",  # неопределённый адрес
        "10.0.0.0/8",  # приватная сеть
        "100.64.0.0/10",  # операторская трансляция адресов
        "127.0.0.0/8",  # петля
        "169.254.0.0/16",  # link-local, включая метаданные облака
        "172.16.0.0/12",  # приватная сеть
        "192.0.0.0/24",  # служебные назначения
        "192.168.0.0/16",  # приватная сеть
        "198.18.0.0/15",  # тестирование производительности
        "224.0.0.0/4",  # многоадресная рассылка
        "240.0.0.0/4",  # зарезервировано
        "::1/128",  # петля IPv6
        "fc00::/7",  # приватные адреса IPv6
        "fe80::/10",  # link-local IPv6
        "ff00::/8",  # многоадресная рассылка IPv6
    )
)


class UrlNotAllowedError(Exception):
    """Адрес запрещён к загрузке.

    Отдельный тип, а не общая ошибка: такие случаи логируются как попытка
    выхода за периметр и не должны теряться среди обычных сетевых сбоев.
    """

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"адрес отклонён: {reason}")
        self.url = url
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    """Проверенный адрес назначения."""

    url: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


def is_blocked_address(raw: str) -> bool:
    """Лежит ли адрес в запрещённом диапазоне."""
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return True  # не разобрали адрес — считаем небезопасным

    # Стандартные признаки проверяются отдельно: они шире списка сетей и
    # закрывают случаи, которые в него не попали.
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return True

    # Адрес IPv4, завёрнутый в IPv6, обходит проверки выше — разворачиваем.
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return is_blocked_address(str(address.ipv4_mapped))

    return any(address in network for network in BLOCKED_NETWORKS)


def resolve_and_validate(url: str, *, resolver=socket.getaddrinfo) -> ResolvedTarget:
    """Разбирает адрес, резолвит имя и проверяет каждый полученный адрес.

    Проверяются все адреса имени, а не первый: имя может отдавать вперемешку
    публичный и внутренний, и выбор конкретного зависит от порядка ответа.
    """
    parts = urlsplit(url)

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlNotAllowedError(url, f"схема {parts.scheme or 'не указана'!r} запрещена")

    if parts.username or parts.password:
        # Учётные данные в адресе — признак подмены цели, а заодно утечка
        # секрета в логи и историю.
        raise UrlNotAllowedError(url, "учётные данные в адресе запрещены")

    hostname = (parts.hostname or "").strip().rstrip(".")
    if not hostname:
        raise UrlNotAllowedError(url, "не указано имя узла")

    if hostname.lower() in BLOCKED_HOSTNAMES:
        raise UrlNotAllowedError(url, f"имя {hostname!r} запрещено")

    port = parts.port or (443 if parts.scheme.lower() == "https" else 80)

    try:
        infos = resolver(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UrlNotAllowedError(url, "имя не разрешается") from exc

    addresses = tuple(dict.fromkeys(info[4][0] for info in infos))
    if not addresses:
        raise UrlNotAllowedError(url, "имя не разрешается")

    for address in addresses:
        if is_blocked_address(address):
            raise UrlNotAllowedError(url, f"адрес {address} во внутреннем диапазоне")

    return ResolvedTarget(url=url, hostname=hostname, port=port, addresses=addresses)
