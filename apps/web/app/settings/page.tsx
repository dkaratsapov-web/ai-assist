"use client";

import { useEffect, useMemo, useState } from "react";
import type { ApiError, MemberRead, OrganizationRead } from "@ads-os/schemas";
import {
  Button,
  Card,
  CardHeader,
  ErrorState,
  Input,
  Modal,
  Skeleton,
  StatusBadge,
} from "@ads-os/ui";
import { AppShell } from "@/components/AppShell";
import { useCurrentUser } from "@/components/AuthGate";
import { createApiClient } from "@/lib/api";
import { toApiError } from "@/lib/errors";

const ROLE_LABEL: Record<string, string> = {
  owner: "Владелец",
  specialist: "Специалист",
  viewer: "Просмотр",
};

export default function SettingsPage() {
  const api = useMemo(() => createApiClient(), []);
  const me = useCurrentUser();
  const isOwner = me.role === "owner";

  const [organization, setOrganization] = useState<OrganizationRead | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState({ email: "", full_name: "", role: "specialist" });

  useEffect(() => {
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
  }, [api, reloadToken]);

  const reload = () => setReloadToken((token) => token + 1);

  const addMember = async () => {
    setSaving(true);
    try {
      await api.addMember({
        email: draft.email.trim(),
        full_name: draft.full_name.trim(),
        role: draft.role as "owner" | "specialist" | "viewer",
      });
      setAdding(false);
      setDraft({ email: "", full_name: "", role: "specialist" });
      reload();
    } catch (err) {
      setError(toApiError(err));
      setAdding(false);
    } finally {
      setSaving(false);
    }
  };

  const setActive = async (member: MemberRead, isActive: boolean) => {
    try {
      await api.updateMember(member.id, { is_active: isActive });
      reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

  return (
    <AppShell
      title="Настройки"
      subtitle="Организация, участники и режим работы"
      actions={
        isOwner && organization ? (
          <Button size="sm" onClick={() => setAdding(true)}>
            Добавить участника
          </Button>
        ) : undefined
      }
    >
      {error ? (
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
            <CardHeader
              title="Участники"
              description={
                isOwner
                  ? "Доступ выдаётся добавлением почты. Приглашение по ссылке не нужно: личность подтверждает Яндекс"
                  : `Всего: ${organization.members.length}`
              }
            />
            <div className="flex flex-col">
              {organization.members.map((member) => (
                <MemberRow
                  key={member.id}
                  member={member}
                  isSelf={member.id === me.id}
                  canManage={isOwner}
                  onToggle={(next) => void setActive(member, next)}
                />
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

      <Modal
        open={adding}
        onClose={() => setAdding(false)}
        title="Добавить участника"
        description="Укажите почту того аккаунта Яндекса, под которым человек будет входить."
        footer={
          <>
            <Button variant="secondary" onClick={() => setAdding(false)}>
              Отмена
            </Button>
            <Button
              onClick={() => void addMember()}
              loading={saving}
              disabled={draft.email.trim() === "" || draft.full_name.trim() === ""}
            >
              Добавить
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Input
            label="Почта в Яндексе"
            value={draft.email}
            onChange={(e) => setDraft((d) => ({ ...d, email: e.target.value }))}
            placeholder="ivan@yandex.ru"
            hint="Должна совпадать с почтой аккаунта, иначе человек не будет опознан"
          />
          <Input
            label="Имя"
            value={draft.full_name}
            onChange={(e) => setDraft((d) => ({ ...d, full_name: e.target.value }))}
          />
          <label className="flex flex-col gap-1.5">
            <span className="text-caption text-text-secondary">Роль</span>
            <select
              value={draft.role}
              onChange={(e) => setDraft((d) => ({ ...d, role: e.target.value }))}
              className="border-border-input rounded-control text-body-sm text-text-primary bg-bg focus-visible:outline-focus h-10 border px-3 focus-visible:outline-2"
            >
              <option value="specialist">Специалист — ведёт проекты</option>
              <option value="viewer">Просмотр — только читает</option>
              <option value="owner">Владелец — управляет доступами</option>
            </select>
          </label>
        </div>
      </Modal>
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

function MemberRow({
  member,
  isSelf,
  canManage,
  onToggle,
}: {
  member: MemberRead;
  isSelf: boolean;
  canManage: boolean;
  onToggle: (isActive: boolean) => void;
}) {
  return (
    <div className="border-border flex flex-wrap items-center justify-between gap-2 border-b py-3 last:border-b-0">
      <div className="flex flex-col">
        <span className="text-body-sm text-text-primary">
          {member.full_name}
          {isSelf && <span className="text-text-secondary"> — это вы</span>}
        </span>
        <span className="text-caption text-text-secondary break-all">{member.email}</span>
      </div>
      <div className="flex items-center gap-2">
        <StatusBadge tone="neutral">{ROLE_LABEL[member.role] ?? member.role}</StatusBadge>

        {/* Состояние второго фактора Яндекс нам не сообщает, поэтому его здесь
            и нет: показывать догадку под видом факта хуже, чем не показывать
            ничего. Вместо этого видно то, что мы действительно знаем, —
            входил человек хоть раз или доступ пока не использован. */}
        {!member.has_logged_in && member.is_active && (
          <StatusBadge tone="neutral">Ещё не входил</StatusBadge>
        )}

        {!member.is_active && <StatusBadge tone="warning">Отключён</StatusBadge>}

        {canManage && !isSelf && (
          <Button size="sm" variant="ghost" onClick={() => onToggle(!member.is_active)}>
            {member.is_active ? "Отключить" : "Включить"}
          </Button>
        )}
      </div>
    </div>
  );
}
