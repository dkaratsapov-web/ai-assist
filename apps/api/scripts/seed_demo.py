#!/usr/bin/env python
"""Демонстрационные данные (v0.3 §76).

Создаёт организацию, специалиста и проекты по образцу «ремонт техники Apple,
регион Тверь». Данные синтетические: реальные рекламные кабинеты не подключены
и до прохождения проверок безопасности подключены не будут (v0.4 §2.1).

Экономика заполнена намеренно частично — чтобы на демонстрации было видно
Limited Economics Mode, а не только благополучный случай.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select  # noqa: E402

from ads_os.db.session import dispose_engine, session_scope  # noqa: E402
from ads_os.models import (  # noqa: E402
    MainConversion,
    Organization,
    OrganizationPlan,
    Project,
    ProjectEconomics,
    ProjectStatus,
    User,
)
from ads_os.tenancy.context import Role  # noqa: E402

DEMO_SLUG = "demo-apple-service"


async def seed() -> None:
    async with session_scope() as session:
        existing = (
            await session.execute(select(Organization).where(Organization.slug == DEMO_SLUG))
        ).scalar_one_or_none()

        if existing is not None:
            org = existing
            print(f"Организация уже существует: {org.id}")
        else:
            org = Organization(name="Демо-агентство", slug=DEMO_SLUG)
            session.add(org)
            await session.flush()
            session.add(OrganizationPlan(organization_id=org.id))
            print(f"Организация создана: {org.id}")

        user = (
            await session.execute(
                select(User).where(User.organization_id == org.id, User.email == "ivan@example.com")
            )
        ).scalar_one_or_none()

        if user is None:
            user = User(
                organization_id=org.id,
                email="ivan@example.com",
                full_name="Иван Петров",
                role=Role.SPECIALIST,
            )
            session.add(user)
            await session.flush()

        projects = [
            ("Apple Service Тверь", "https://example-apple-service.ru", "Тверь", ProjectStatus.ACTIVE),
            ("Ремонт iPhone Москва", None, "Москва", ProjectStatus.ACTIVE),
            ("Запчасти iPhone СПб", None, "Санкт-Петербург", ProjectStatus.PAUSED),
            ("Trade-in iPhone", None, "Тверь", ProjectStatus.DRAFT),
        ]

        created: list[Project] = []
        for name, url, region, status in projects:
            found = (
                await session.execute(
                    select(Project).where(
                        Project.organization_id == org.id, Project.name == name
                    )
                )
            ).scalar_one_or_none()
            if found is not None:
                created.append(found)
                continue

            project = Project(
                organization_id=org.id,
                name=name,
                website_url=url,
                primary_region=region,
                status=status,
                created_by_id=user.id,
            )
            session.add(project)
            await session.flush()
            created.append(project)

        # У первого проекта экономика заполнена целиком, у второго — частично.
        # Демонстрация обязана показывать оба состояния: продукт заявляет, что
        # работает без полной экономики, и это должно быть видно.
        await _ensure_economics(
            session,
            org.id,
            created[0].id,
            monthly_budget=Decimal("150000"),
            average_order_value=Decimal("6000"),
            main_conversion=MainConversion.LEAD,
            margin_percent=Decimal("45"),
            lead_to_sale_rate=Decimal("0.22"),
        )
        await _ensure_economics(
            session,
            org.id,
            created[1].id,
            monthly_budget=Decimal("98000"),
            average_order_value=Decimal("5200"),
            main_conversion=MainConversion.LEAD,
        )

        print("\nКонтекст для фронтенда:")
        print(f"  NEXT_PUBLIC_DEMO_ORG_ID={org.id}")
        print(f"  NEXT_PUBLIC_DEMO_USER_ID={user.id}")
        print("\nПроекты:")
        for project in created:
            print(f"  {project.id}  {project.name}")

    await dispose_engine()


async def _ensure_economics(
    session: object, org_id: uuid.UUID, project_id: uuid.UUID, **fields: object
) -> None:
    found = (
        await session.execute(  # type: ignore[attr-defined]
            select(ProjectEconomics).where(ProjectEconomics.project_id == project_id)
        )
    ).scalar_one_or_none()
    if found is not None:
        return
    session.add(  # type: ignore[attr-defined]
        ProjectEconomics(organization_id=org_id, project_id=project_id, version=1, **fields)
    )


if __name__ == "__main__":
    asyncio.run(seed())
