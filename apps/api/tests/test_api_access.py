"""Доступ к отдельным проектам.

Главное здесь — не то, что доступ выдаётся, а то, что он ограничивает.
Специалист, которому открыли один проект, не должен видеть остальные: ни в
списке, ни по прямой ссылке, ни через фразы и конкурентов чужого проекта.
Поэтому большая часть проверок обращается к репозиторию напрямую — именно там
проходит граница, и проверять её через экраны значило бы проверять экраны.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.api.deps import get_session
from ads_os.main import create_app
from ads_os.models import Keyword, Organization, Project, ProjectAccess, User
from ads_os.services.auth import allowed_projects
from ads_os.services.semantics import Intent
from ads_os.tenancy.context import Role, TenantContext
from ads_os.tenancy.repository import TenantRepository

from .conftest import make_project, make_user


class ProjectRepo(TenantRepository[Project]):
    model = Project


class KeywordRepo(TenantRepository[Keyword]):
    model = Keyword


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def owner_ctx(
    session: AsyncSession, two_organizations: tuple[Organization, Organization]
) -> tuple[Organization, User, Project, Project]:
    org, _ = two_organizations
    owner = await make_user(session, org, "owner@example.com")
    owner.role = Role.OWNER
    first = await make_project(session, org, "Потолки")
    second = await make_project(session, org, "Окна")
    await session.commit()
    return org, owner, first, second


def headers(org: Organization, user: User, role: str = "owner") -> dict[str, str]:
    return {
        "X-Organization-Id": str(org.id),
        "X-User-Id": str(user.id),
        "X-User-Role": role,
    }


def context(org: Organization, user: User, allowed: object = None) -> TenantContext:
    return TenantContext(
        organization_id=org.id,
        user_id=user.id,
        role=user.role,
        allowed_projects=allowed,  # type: ignore[arg-type]
    )


class TestВыдачаПоПочте:
    async def test_доступ_выдаётся_одной_почтой(
        self,
        client: AsyncClient,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        """Учётную запись заводить отдельно не нужно: личность подтвердит
        Яндекс при первом входе."""
        org, owner, project, _ = owner_ctx

        response = await client.post(
            f"/api/v1/projects/{project.id}/access",
            headers=headers(org, owner),
            json={"email": "client@yandex.ru"},
        )

        assert response.status_code == 201
        assert response.json()["email"] == "client@yandex.ru"

    async def test_заведённый_человек_видит_только_свой_проект(
        self,
        client: AsyncClient,
        session: AsyncSession,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        """Ради этого всё и затевалось."""
        org, owner, project, other = owner_ctx
        await client.post(
            f"/api/v1/projects/{project.id}/access",
            headers=headers(org, owner),
            json={"email": "client@yandex.ru"},
        )

        guest = (
            await session.execute(select(User).where(User.email == "client@yandex.ru"))
        ).scalar_one()
        guest_ctx = context(org, guest, await allowed(session, guest))
        visible = await ProjectRepo(session, guest_ctx).list()

        assert [p.id for p in visible] == [project.id]
        assert other.id not in [p.id for p in visible]

    async def test_повторная_выдача_не_плодит_записей(
        self,
        client: AsyncClient,
        session: AsyncSession,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        """Владелец мог просто не увидеть человека в списке."""
        org, owner, project, _ = owner_ctx
        for _ in range(3):
            await client.post(
                f"/api/v1/projects/{project.id}/access",
                headers=headers(org, owner),
                json={"email": "client@yandex.ru"},
            )

        rows = (await session.execute(select(ProjectAccess))).scalars().all()

        assert len(rows) == 1

    async def test_разные_написания_почты_это_один_человек(
        self,
        client: AsyncClient,
        session: AsyncSession,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        """Иначе владелец заведёт двоих, а войдёт один — и не туда."""
        org, owner, project, other = owner_ctx
        await client.post(
            f"/api/v1/projects/{project.id}/access",
            headers=headers(org, owner),
            json={"email": "ivan.petrov@ya.ru"},
        )
        await client.post(
            f"/api/v1/projects/{other.id}/access",
            headers=headers(org, owner),
            json={"email": "ivan-petrov@yandex.ru"},
        )

        people = (
            (await session.execute(select(User).where(User.email.like("ivan%"))))
            .scalars()
            .all()
        )

        assert len(people) == 1

    async def test_не_почта_отклоняется(
        self,
        client: AsyncClient,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        org, owner, project, _ = owner_ctx

        response = await client.post(
            f"/api/v1/projects/{project.id}/access",
            headers=headers(org, owner),
            json={"email": "просто текст"},
        )

        assert response.status_code == 422

    async def test_доступ_раздаёт_только_владелец(
        self,
        client: AsyncClient,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        """Специалист, который может открыть проект кому угодно, — это
        отсутствие разграничения, просто в два шага."""
        org, owner, project, _ = owner_ctx

        response = await client.post(
            f"/api/v1/projects/{project.id}/access",
            headers=headers(org, owner, role="specialist"),
            json={"email": "client@yandex.ru"},
        )

        assert response.status_code == 403


class TestСписокИОтзыв:
    async def test_список_показывает_кому_открыт_проект(
        self,
        client: AsyncClient,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        org, owner, project, _ = owner_ctx
        await client.post(
            f"/api/v1/projects/{project.id}/access",
            headers=headers(org, owner),
            json={"email": "client@yandex.ru", "full_name": "Клиент"},
        )

        body = (
            await client.get(
                f"/api/v1/projects/{project.id}/access", headers=headers(org, owner)
            )
        ).json()

        assert body["total"] == 1
        assert body["items"][0]["full_name"] == "Клиент"
        # Пока человек не входил, отметки нет — по ней и видно, дошло ли
        # приглашение.
        assert body["items"][0]["last_login_at"] is None

    async def test_отзыв_закрывает_проект(
        self,
        client: AsyncClient,
        session: AsyncSession,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        org, owner, project, _ = owner_ctx
        created = (
            await client.post(
                f"/api/v1/projects/{project.id}/access",
                headers=headers(org, owner),
                json={"email": "client@yandex.ru"},
            )
        ).json()

        response = await client.delete(
            f"/api/v1/projects/{project.id}/access/{created['user_id']}",
            headers=headers(org, owner),
        )

        assert response.status_code == 204
        guest = (
            await session.execute(select(User).where(User.email == "client@yandex.ru"))
        ).scalar_one()
        assert await allowed(session, guest) == frozenset()

    async def test_отзыв_несуществующего_доступа_это_не_найдено(
        self,
        client: AsyncClient,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        org, owner, project, _ = owner_ctx

        response = await client.delete(
            f"/api/v1/projects/{project.id}/access/{owner.id}", headers=headers(org, owner)
        )

        assert response.status_code == 404


class TestГраницаВидимости:
    """Ограничение проходит в репозитории, а не в проверках по месту."""

    async def test_чужой_проект_не_открывается_по_прямой_ссылке(
        self,
        session: AsyncSession,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        """Ответ тот же, что и для несуществующего: иначе перебором можно
        выяснить, какие проекты вообще есть."""
        from ads_os.errors import NotFoundError

        org, _, project, other = owner_ctx
        guest = await make_user(session, org, "guest@yandex.ru")
        await session.commit()

        repo = ProjectRepo(session, context(org, guest, frozenset({project.id})))

        with pytest.raises(NotFoundError):
            await repo.get_or_404(other.id)

    async def test_фразы_чужого_проекта_не_видны(
        self,
        session: AsyncSession,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        """Сужение должно работать не только на самих проектах, иначе через
        фразы и конкурентов чужой проект виден насквозь."""
        org, _, project, other = owner_ctx
        guest = await make_user(session, org, "guest@yandex.ru")
        session.add_all(
            [
                Keyword(
                    organization_id=org.id,
                    project_id=project.id,
                    phrase="свои",
                    intent=Intent.COMMERCIAL,
                ),
                Keyword(
                    organization_id=org.id,
                    project_id=other.id,
                    phrase="чужие",
                    intent=Intent.COMMERCIAL,
                ),
            ]
        )
        await session.commit()

        # include_deleted: у фраз нет мягкого удаления, и общий фильтр к ним
        # не применяется — проверяем именно сужение по проекту.
        rows = await KeywordRepo(session, context(org, guest, frozenset({project.id}))).list(
            include_deleted=True
        )

        assert [k.phrase for k in rows] == ["свои"]

    async def test_пустой_список_доступов_не_значит_все_проекты(
        self,
        session: AsyncSession,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        """Разница между «открыты все» и «не открыт ни один» стоила бы либо
        пустого экрана, либо чужих бюджетов на виду."""
        org = owner_ctx[0]
        guest = await make_user(session, org, "guest@yandex.ru")
        await session.commit()

        rows = await ProjectRepo(session, context(org, guest, frozenset())).list()

        assert rows == []

    async def test_владелец_видит_всё(
        self,
        session: AsyncSession,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        """Проект, скрытый от владельца, — это проект, за который никто не
        отвечает."""
        owner = owner_ctx[1]

        assert await allowed(session, owner) is None

    async def test_прежние_участники_ничего_не_потеряли(
        self,
        session: AsyncSession,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        """Появление списка доступов никого ничего не лишает."""
        org = owner_ctx[0]
        old = await make_user(session, org, "old@example.com")
        await session.commit()

        assert old.all_projects is True
        assert await allowed(session, old) is None

    async def test_участники_организации_остаются_видны(
        self,
        session: AsyncSession,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        """Сущности без привязки к проекту сужать не от чего: прятать
        участников по признаку проекта бессмысленно."""

        class UserRepo(TenantRepository[User]):
            model = User

        org, owner, project, _ = owner_ctx
        guest = await make_user(session, org, "guest@yandex.ru")
        await session.commit()

        rows = await UserRepo(session, context(org, guest, frozenset({project.id}))).list()

        assert owner.id in [u.id for u in rows]


async def allowed(session: AsyncSession, user: User) -> object:
    return await allowed_projects(session, user)


class TestРоль:
    """Роль выданного доступа должна меняться на месте.

    Иначе поправить ошибку можно только закрыв доступ и выдав заново — а это
    отзыв сессий человека и запись в журнале о том, чего не происходило.
    """

    async def test_роль_выбирается_при_выдаче(
        self,
        client: AsyncClient,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        org, owner, project, _ = owner_ctx

        body = (
            await client.post(
                f"/api/v1/projects/{project.id}/access",
                headers=headers(org, owner),
                json={"email": "client@yandex.ru", "role": "specialist"},
            )
        ).json()

        assert body["role"] == "specialist"

    async def test_роль_меняется_после_выдачи(
        self,
        client: AsyncClient,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        org, owner, project, _ = owner_ctx
        created = (
            await client.post(
                f"/api/v1/projects/{project.id}/access",
                headers=headers(org, owner),
                json={"email": "client@yandex.ru"},
            )
        ).json()
        assert created["role"] == "viewer"

        body = (
            await client.patch(
                f"/api/v1/projects/{project.id}/access/{created['user_id']}",
                headers=headers(org, owner),
                json={"role": "specialist"},
            )
        ).json()

        assert body["role"] == "specialist"

    async def test_владельца_отсюда_не_понизить(
        self,
        client: AsyncClient,
        session: AsyncSession,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        """Иначе организация осталась бы без ответственного."""
        org, owner, project, _ = owner_ctx
        session.add(
            ProjectAccess(organization_id=org.id, user_id=owner.id, project_id=project.id)
        )
        await session.commit()

        response = await client.patch(
            f"/api/v1/projects/{project.id}/access/{owner.id}",
            headers=headers(org, owner),
            json={"role": "viewer"},
        )

        assert response.status_code == 403

    async def test_роль_меняет_только_владелец(
        self,
        client: AsyncClient,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        org, owner, project, _ = owner_ctx
        created = (
            await client.post(
                f"/api/v1/projects/{project.id}/access",
                headers=headers(org, owner),
                json={"email": "client@yandex.ru"},
            )
        ).json()

        response = await client.patch(
            f"/api/v1/projects/{project.id}/access/{created['user_id']}",
            headers=headers(org, owner, role="specialist"),
            json={"role": "specialist"},
        )

        assert response.status_code == 403


class TestСозданиеПроекта:
    async def test_созданный_проект_виден_создателю(
        self,
        client: AsyncClient,
        session: AsyncSession,
        owner_ctx: tuple[Organization, User, Project, Project],
    ) -> None:
        """Человек с доступом к отдельным проектам создал бы проект и тут же
        его потерял: проект есть, а в списке пусто."""
        org, _, project, _ = owner_ctx
        guest = await make_user(session, org, "guest@yandex.ru")
        guest.all_projects = False
        session.add(ProjectAccess(organization_id=org.id, user_id=guest.id, project_id=project.id))
        await session.commit()

        created = (
            await client.post(
                "/api/v1/projects",
                headers=headers(org, guest, role="specialist"),
                json={"name": "Новый проект"},
            )
        ).json()

        visible = await ProjectRepo(
            session, context(org, guest, await allowed(session, guest))
        ).list()

        assert created["id"] in [str(p.id) for p in visible]
