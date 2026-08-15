"""Уведомления: когда система обязана сообщить сама.

Проверяется прежде всего то, из-за чего уведомления перестают читать: повторы,
сообщения о том, что и так в порядке, и тревога без указания, что делать.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ads_os.api.deps import get_session
from ads_os.main import create_app
from ads_os.models import Notification, Organization, Project, User
from ads_os.models.notification import NotificationKind, NotificationLevel
from ads_os.services.audit import Category, Issue, IssueChanges, IssueKey, Severity
from ads_os.services.notifications import SIGNIFICANT_DROP, evaluate_audit, push

from .conftest import make_user


def issue(key: IssueKey, severity: Severity) -> Issue:
    return Issue(key, Category.TECHNICAL, severity, "Замечание", "Действие" * 5)


class TestОтборСобытий:
    def test_появление_блокирующего_замечания_это_событие(self) -> None:
        changes = IssueChanges(appeared=(issue(IssueKey.NO_METRICA, Severity.CRITICAL),))

        alert = evaluate_audit(changes=changes, score=40, previous_score=90)

        assert alert is not None
        assert alert.kind is NotificationKind.SITE_BROKEN
        assert alert.level is NotificationLevel.CRITICAL

    def test_появление_мелкого_замечания_событием_не_считается(self) -> None:
        """Иначе список за месяц превратится в то, что не читают."""
        changes = IssueChanges(appeared=(issue(IssueKey.NO_PRICES, Severity.RECOMMENDATION),))

        assert evaluate_audit(changes=changes, score=88, previous_score=90) is None

    def test_исправление_событием_не_считается(self) -> None:
        """«Стало лучше» человек увидит сам, когда откроет проект."""
        changes = IssueChanges(fixed=(issue(IssueKey.NO_MOBILE, Severity.WARNING),))

        assert evaluate_audit(changes=changes, score=95, previous_score=80) is None

    def test_заметное_падение_балла_это_событие(self) -> None:
        alert = evaluate_audit(
            changes=IssueChanges(), score=60, previous_score=60 + SIGNIFICANT_DROP
        )

        assert alert is not None
        assert alert.kind is NotificationKind.SITE_DEGRADED

    def test_мелкое_колебание_балла_игнорируется(self) -> None:
        """Три пункта — это разброс, а не изменение."""
        assert evaluate_audit(changes=IssueChanges(), score=87, previous_score=90) is None

    def test_недоступный_сайт_это_событие(self) -> None:
        alert = evaluate_audit(
            changes=None, score=None, previous_score=90, failed_reason="сервер не ответил вовремя"
        )

        assert alert is not None
        assert alert.kind is NotificationKind.SITE_UNREACHABLE

    def test_на_одну_проверку_не_больше_одного_уведомления(self) -> None:
        """Три сообщения об одной поломке — втрое больше шума, а не информации."""
        changes = IssueChanges(appeared=(issue(IssueKey.NO_METRICA, Severity.CRITICAL),))

        alert = evaluate_audit(changes=changes, score=20, previous_score=95)

        assert alert is not None
        assert alert.kind is NotificationKind.SITE_BROKEN

    def test_у_события_всегда_есть_что_делать(self) -> None:
        """Тревога без выхода вредит больше, чем помогает."""
        cases = (
            evaluate_audit(
                changes=IssueChanges(appeared=(issue(IssueKey.NO_METRICA, Severity.CRITICAL),)),
                score=20,
                previous_score=95,
            ),
            evaluate_audit(changes=IssueChanges(), score=50, previous_score=90),
            evaluate_audit(changes=None, score=None, previous_score=90, failed_reason="нет ответа"),
        )

        for alert in cases:
            assert alert is not None
            assert len(alert.body) > 40


class TestПовторы:
    async def test_та_же_поломка_не_создаёт_второе_уведомление(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        """Ежедневная проверка иначе дала бы семь копий за неделю."""
        org, _ = two_organizations
        project = Project(organization_id=org.id, name="Проект")
        session.add(project)
        await session.commit()

        alert = evaluate_audit(
            changes=IssueChanges(appeared=(issue(IssueKey.NO_METRICA, Severity.CRITICAL),)),
            score=20,
            previous_score=95,
        )
        assert alert is not None

        first = await push(
            session, alert, organization_id=org.id, project_id=project.id, project_name="Проект"
        )
        second = await push(
            session, alert, organization_id=org.id, project_id=project.id, project_name="Проект"
        )
        await session.commit()

        assert first is not None
        assert second is None

    async def test_после_прочтения_повтор_снова_уведомляет(
        self, session: AsyncSession, two_organizations: tuple[Organization, Organization]
    ) -> None:
        """Прочитали и не починили — через неделю напомнить нужно."""
        org, _ = two_organizations
        project = Project(organization_id=org.id, name="Проект")
        session.add(project)
        await session.commit()

        alert = evaluate_audit(changes=IssueChanges(), score=50, previous_score=90)
        assert alert is not None

        first = await push(
            session, alert, organization_id=org.id, project_id=project.id, project_name="Проект"
        )
        assert first is not None
        first.is_read = True
        await session.commit()

        second = await push(
            session, alert, organization_id=org.id, project_id=project.id, project_name="Проект"
        )
        await session.commit()

        assert second is not None


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def headers(org: Organization, user: User) -> dict[str, str]:
    return {
        "X-Organization-Id": str(org.id),
        "X-User-Id": str(user.id),
        "X-User-Role": "specialist",
    }


class TestЛента:
    async def test_непрочитанные_считаются_целиком(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        """Число на колокольчике не должно зависеть от размера выдачи."""
        org, _ = two_organizations
        user = await make_user(session, org, "s@example.com")
        for index in range(3):
            session.add(
                Notification(
                    organization_id=org.id,
                    project_name="Проект",
                    kind=NotificationKind.SITE_BROKEN,
                    level=NotificationLevel.CRITICAL,
                    title=f"Событие {index}",
                    body="Что-то случилось, вот что делать.",
                    dedup_key=f"key-{index}",
                )
            )
        await session.commit()

        body = (
            await client.get("/api/v1/notifications?limit=1", headers=headers(org, user))
        ).json()

        assert len(body["items"]) == 1
        assert body["unread"] == 3

    async def test_чужие_уведомления_недоступны(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, other_org = two_organizations
        other_user = await make_user(session, other_org, "other@example.com")
        session.add(
            Notification(
                organization_id=org.id,
                project_name="Чужой проект",
                kind=NotificationKind.SITE_BROKEN,
                level=NotificationLevel.CRITICAL,
                title="Событие",
                body="Что-то случилось, вот что делать.",
                dedup_key="key",
            )
        )
        await session.commit()

        body = (
            await client.get("/api/v1/notifications", headers=headers(other_org, other_user))
        ).json()

        assert body["total"] == 0
        assert body["unread"] == 0

    async def test_отметка_прочтения_убирает_из_счётчика(
        self,
        client: AsyncClient,
        session: AsyncSession,
        two_organizations: tuple[Organization, Organization],
    ) -> None:
        org, _ = two_organizations
        user = await make_user(session, org, "s@example.com")
        row = Notification(
            organization_id=org.id,
            project_name="Проект",
            kind=NotificationKind.SITE_BROKEN,
            level=NotificationLevel.CRITICAL,
            title="Событие",
            body="Что-то случилось, вот что делать.",
            dedup_key="key",
        )
        session.add(row)
        await session.commit()

        await client.post(
            f"/api/v1/notifications/{row.id}/read", headers=headers(org, user)
        )

        body = (await client.get("/api/v1/notifications", headers=headers(org, user))).json()

        assert body["unread"] == 0
