"""Общие фикстуры тестов.

Тесты изоляции арендаторов идут против настоящего PostgreSQL. Подменять его
SQLite нельзя: проверяется именно поведение запросов и ограничений, а различия
диалектов сделали бы проверку декоративной.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ads_os.db.base import Base
from ads_os.models import Organization, Project, User
from ads_os.tenancy.context import Role, TenantContext

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ads_os@127.0.0.1:5433/ads_os_test",
)

_TABLES = ", ".join(
    f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables) if t.name != "alembic_version"
)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as s:
        # Чистое состояние перед каждым тестом: остатки от соседнего теста
        # исказили бы именно проверку изоляции.
        await s.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))
        await s.commit()
        yield s
        await s.rollback()

    await engine.dispose()


@pytest.fixture
async def two_organizations(session: AsyncSession) -> tuple[Organization, Organization]:
    """Две независимые организации — основа всех проверок изоляции."""
    first = Organization(name="Агентство А", slug=f"a-{uuid.uuid4().hex[:8]}")
    second = Organization(name="Агентство Б", slug=f"b-{uuid.uuid4().hex[:8]}")
    session.add_all([first, second])
    await session.flush()
    return first, second


def make_context(org: Organization, role: Role = Role.SPECIALIST) -> TenantContext:
    return TenantContext(organization_id=org.id, user_id=uuid.uuid4(), role=role)


async def make_user(session: AsyncSession, org: Organization, email: str) -> User:
    user = User(
        organization_id=org.id,
        email=email,
        full_name="Тестовый пользователь",
        role=Role.SPECIALIST,
    )
    session.add(user)
    await session.flush()
    return user


async def make_project(session: AsyncSession, org: Organization, name: str) -> Project:
    project = Project(organization_id=org.id, name=name)
    session.add(project)
    await session.flush()
    return project
