"""Изоляция арендаторов — SEC-001 и SEC-015 из плана безопасности v0.3 §115.

Это не обычные функциональные тесты. Утечка данных чужого клиента разрушает
продукт целиком, поэтому проверяется не «обычно работает», а «нельзя обойти»:
у репозитория нет способа получить незаполненный запрос, а попытка обратиться к
данным вне контекста организации падает, а не возвращает всё подряд.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.errors import NotFoundError
from ads_os.models import Organization, Project
from ads_os.tenancy.context import (
    MissingTenantContextError,
    Role,
    current_context,
    use_context,
)
from ads_os.tenancy.repository import TenantRepository

from .conftest import make_context, make_project


class ProjectRepository(TenantRepository[Project]):
    model = Project


class TestSEC001ЧужойПроект:
    async def test_чужой_проект_не_виден_в_списке(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        org_a, org_b = two_organizations
        await make_project(session, org_a, "Проект А")
        await make_project(session, org_b, "Проект Б")

        repo = ProjectRepository(session, make_context(org_a))
        names = [p.name for p in await repo.list()]

        assert names == ["Проект А"]

    async def test_чужой_проект_по_прямому_идентификатору_даёт_не_найдено(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        """Ответ должен совпадать с ответом для несуществующего объекта.

        Разница между «нет доступа» и «не существует» позволила бы перебором
        выяснять, какие идентификаторы есть у других организаций.
        """
        org_a, org_b = two_organizations
        foreign = await make_project(session, org_b, "Проект Б")

        repo = ProjectRepository(session, make_context(org_a))

        assert await repo.get(foreign.id) is None
        with pytest.raises(NotFoundError):
            await repo.get_or_404(foreign.id)

        missing_id = uuid.uuid4()
        with pytest.raises(NotFoundError):
            await repo.get_or_404(missing_id)

    async def test_чужой_проект_нельзя_удалить(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        org_a, org_b = two_organizations
        foreign = await make_project(session, org_b, "Проект Б")

        repo = ProjectRepository(session, make_context(org_a))
        with pytest.raises(NotFoundError):
            await repo.soft_delete(foreign.id)

        await session.refresh(foreign)
        assert foreign.deleted_at is None

    async def test_счётчик_не_учитывает_чужие_записи(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        org_a, org_b = two_organizations
        await make_project(session, org_a, "Проект А")
        for i in range(3):
            await make_project(session, org_b, f"Проект Б{i}")

        repo = ProjectRepository(session, make_context(org_a))
        assert await repo.count() == 1


class TestСозданиеОбъектов:
    async def test_организация_подставляется_из_контекста(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        org_a, _ = two_organizations
        repo = ProjectRepository(session, make_context(org_a))

        created = await repo.add(Project(name="Новый проект"))

        assert created.organization_id == org_a.id

    async def test_нельзя_создать_объект_в_чужой_организации(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        """Идентификатор организации из запроса клиента не является основанием.

        Прямое требование v0.3 §93: не принимать organization_id от клиента как
        единственный источник авторизации.
        """
        org_a, org_b = two_organizations
        repo = ProjectRepository(session, make_context(org_a))

        with pytest.raises(NotFoundError):
            await repo.add(Project(name="Подложенный проект", organization_id=org_b.id))


class TestОтсутствиеКонтекста:
    async def test_обращение_без_контекста_падает(self, session: AsyncSession) -> None:
        """Молча вернуть все записи здесь недопустимо.

        Если контекст не установлен — это дефект кода, и он должен быть шумным,
        а не превращаться в выдачу данных всех организаций сразу.
        """
        repo = ProjectRepository(session)
        with pytest.raises(MissingTenantContextError):
            await repo.list()

    async def test_контекст_живёт_только_внутри_блока(
        self, two_organizations: tuple[Organization, Organization]
    ) -> None:
        org_a, _ = two_organizations

        with use_context(make_context(org_a)):
            assert current_context().organization_id == org_a.id

        with pytest.raises(MissingTenantContextError):
            current_context()

    async def test_вложенный_контекст_восстанавливается(
        self, two_organizations: tuple[Organization, Organization]
    ) -> None:
        org_a, org_b = two_organizations

        with use_context(make_context(org_a)):
            with use_context(make_context(org_b)):
                assert current_context().organization_id == org_b.id
            # После выхода из вложенного блока действует прежняя организация,
            # иначе фоновая обработка могла бы «залипнуть» на чужом контексте.
            assert current_context().organization_id == org_a.id


class TestМягкоеУдаление:
    async def test_удалённый_проект_исчезает_из_выдачи(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        org_a, _ = two_organizations
        project = await make_project(session, org_a, "Проект А")

        repo = ProjectRepository(session, make_context(org_a))
        await repo.soft_delete(project.id)

        assert await repo.list() == []
        assert await repo.get(project.id) is None
        # Запись остаётся в базе: мягкое удаление обратимо (v0.3 §61).
        assert len(await repo.list(include_deleted=True)) == 1


class TestРоли:
    async def test_viewer_не_имеет_права_записи(
        self, two_organizations: tuple[Organization, Organization]
    ) -> None:
        org_a, _ = two_organizations
        viewer = make_context(org_a, Role.VIEWER)
        specialist = make_context(org_a, Role.SPECIALIST)
        owner = make_context(org_a, Role.OWNER)

        assert viewer.can_write is False
        assert specialist.can_write is True
        assert owner.can_write is True
        assert owner.is_owner is True
        assert specialist.is_owner is False
