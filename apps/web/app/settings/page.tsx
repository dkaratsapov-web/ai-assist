"use client";

import { useEffect, useMemo, useState } from "react";
import type { ApiError, MemberRead, OrganizationRead } from "@ads-os/schemas";
import { Card, CardHeader, EmptyState, ErrorState, Skeleton, StatusBadge } from "@ads-os/ui";
import { AppShell } from "@/components/AppShell";
import { createApiClient, isApiConfigured } from "@/lib/api";
import { toApiError } from "@/lib/errors";

const ROLE_LABEL: Record<string, string> = {
  owner: "Владелец",
  specialist: "Специалист",
  viewer: "Просмотр",
};

export default function SettingsPage() {
  const api = useMemo(() => createApiClient(), []);
  const configured = isApiConfigured();

  const [organization, setOrganization] = useState<OrganizationRead | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!configured) return;
    let ignore = false;

    void (async () => {
      try {
        const result = await api.getOrganization();
        if (ignore) return;
        setError(null);
        setOrganization(result);
      } catch (err) {
        if (ignore) return;
        setError(toApiError(err));
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, configured, reloadToken]);

  return (
    <AppShell title="Настройки" subtitle="Организация, участники и режим работы">
      {!configured ? (
        <Card>
          <EmptyState
            title="Стенд не настроен"
            description="Не заданы NEXT_PUBLIC_DEMO_ORG_ID и NEXT_PUBLIC_DEMO_USER_ID. Запустите backend и скрипт seed_demo.py."
          />
        </Card>
      ) : error ? (
        <Card>
          <ErrorState
            title="Не удалось загрузить настройки"
            description={error.message}
            requestId={error.requestId}
            onRetry={() => setReloadToken((token) => token + 1)}
          />
        </Card>
      ) : organization === null ? (
        <div className="flex flex-col gap-4">
          <Skeleton shape="card" />
          <Skeleton shape="card" />
        </div>
      ) : (
        <>
          <Card>
            <CardHeader title="Организация" />
            <dl className="text-body-sm grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Row label="Название" value={organization.name} />
              <Row label="Идентификатор" value={organization.slug} />
              <Row label="Проектов" value={String(organization.projects_count)} />
            </dl>
          </Card>

          {/* Режим работы показывается прямо, а не прячется в конфиге сервера:
              по нему видно, что результаты не являются выводами настоящей
              модели и что рекламный кабинет не подключён. */}
          <Card>
            <CardHeader
              title="Режим работы"
              description="В каком состоянии сейчас находится система"
            />
            <div className="flex flex-col gap-3">
              <ModeRow
                label="Контур"
                value={organization.app_env}
                note={
                  organization.app_env === "production"
                    ? undefined
                    : "Тестовый стенд. Аутентификация ещё не подключена, доступ закрыт паролем"
                }
                tone={organization.app_env === "production" ? "success" : "warning"}
              />
              <ModeRow
                label="Нейросеть"
                value={organization.ai_provider}
                note={
                  organization.ai_provider === "stub"
                    ? "Работает заглушка: ответы формируются по фиксированным правилам и не являются выводами модели"
                    : undefined
                }
                tone={organization.ai_provider === "stub" ? "warning" : "success"}
              />
              <ModeRow
                label="Рекламный кабинет"
                value={organization.ad_platform_adapter}
                note={
                  organization.ad_platform_adapter === "mock"
                    ? "Работает заглушка. Настоящий кабинет подключается только после проверок безопасности"
                    : undefined
                }
                tone={organization.ad_platform_adapter === "mock" ? "warning" : "success"}
              />
            </div>
          </Card>

          <Card>
            <CardHeader title="Участники" description={`Всего: ${organization.members.length}`} />
            <div className="flex flex-col">
              {organization.members.map((member) => (
                <MemberRow key={member.id} member={member} />
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Лимиты"
              description="Платёжная система не подключена, но потолки существуют с первого дня"
            />
            {organization.plan === null ? (
              // Пусто — значит тариф не задан. Придумывать значения по
              // умолчанию и показывать их как настоящие нельзя.
              <p className="text-body-sm text-text-secondary">
                Тариф не назначен, ограничения не применяются.
              </p>
            ) : (
              <dl className="text-body-sm grid grid-cols-1 gap-3 sm:grid-cols-3">
                <Row label="Проектов" value={String(organization.plan.max_projects)} />
                <Row label="Пользователей" value={String(organization.plan.max_users)} />
                <Row
                  label="Страниц краулера в месяц"
                  value={String(organization.plan.crawler_pages_limit)}
                />
                <Row label="Токенов нейросети" value={String(organization.plan.ai_usage_limit)} />
                <Row
                  label="Хранение данных, дней"
                  value={String(organization.plan.retention_days)}
                />
              </dl>
            )}
          </Card>
        </>
      )}
    </AppShell>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <dt className="text-caption text-text-secondary">{label}</dt>
      <dd className="text-text-primary break-all">{value}</dd>
    </div>
  );
}

function ModeRow({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string;
  tone: "success" | "warning";
}) {
  return (
    <div className="border-border flex flex-col gap-1 border-b pb-3 last:border-b-0 last:pb-0">
      <div className="flex items-center justify-between gap-3">
        <span className="text-body-sm text-text-primary">{label}</span>
        <StatusBadge tone={tone}>{value}</StatusBadge>
      </div>
      {note && <p className="text-caption text-text-secondary">{note}</p>}
    </div>
  );
}

function MemberRow({ member }: { member: MemberRead }) {
  return (
    <div className="border-border flex flex-wrap items-center justify-between gap-2 border-b py-3 last:border-b-0">
      <div className="flex flex-col">
        <span className="text-body-sm text-text-primary">{member.full_name}</span>
        <span className="text-caption text-text-secondary break-all">{member.email}</span>
      </div>
      <div className="flex items-center gap-2">
        <StatusBadge tone="neutral">{ROLE_LABEL[member.role] ?? member.role}</StatusBadge>
        {/* Второй фактор — требование к боевому контуру (v0.3 §91). Пока его
            нет ни у кого, и молчать об этом на экране настроек неправильно. */}
        <StatusBadge tone={member.mfa_enabled ? "success" : "warning"}>
          {member.mfa_enabled ? "MFA включён" : "MFA выключен"}
        </StatusBadge>
      </div>
    </div>
  );
}
