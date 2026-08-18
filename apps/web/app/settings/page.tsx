"use client";

import { useEffect, useMemo, useState } from "react";
import type {
  AdPlatformStatusRead,
  ApiError,
  MemberRead,
  OrganizationRead,
  SessionRead,
} from "@ads-os/schemas";
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
  const [adPlatform, setAdPlatform] = useState<AdPlatformStatusRead | null>(null);
  const [sessions, setSessions] = useState<SessionRead[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState({ email: "", full_name: "", role: "specialist" });

  useEffect(() => {
    let ignore = false;

    void (async () => {
      try {
        const [result, mySessions, platform] = await Promise.all([
          api.getOrganization(),
          api.listSessions(),
          // Проверка доступа отдаёт причину отказа ответом, а не ошибкой,
          // поэтому не роняет остальной экран.
          api.getAdPlatformStatus(),
        ]);
        if (ignore) return;
        setError(null);
        setOrganization(result);
        setSessions(mySessions.items);
        setAdPlatform(platform);
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

  const endSession = async (sessionId: string) => {
    try {
      await api.revokeSession(sessionId);
      reload();
    } catch (err) {
      setError(toApiError(err));
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

          <AdPlatformCard status={adPlatform} />

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
              title="Ваши входы"
              description="Устройства, с которых вы сейчас вошли. Если видите чужое — завершите его"
            />
            <div className="flex flex-col">
              {sessions.map((item) => (
                <SessionRow key={item.id} session={item} onEnd={() => void endSession(item.id)} />
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Потребление за 30 дней"
              description="Окно скользящее: лимит не обнуляется первого числа, иначе на стыке месяцев тратится двойная норма"
            />
            <div className="flex flex-col gap-3">
              <UsageBar
                label="Проверено страниц"
                used={organization.usage.crawler_pages}
                limit={organization.usage.crawler_pages_limit}
              />
              <UsageBar
                label="Токенов нейросети"
                used={organization.usage.ai_tokens}
                limit={organization.usage.ai_tokens_limit}
              />
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

/**
 * Расход с потолком.
 *
 * Полоса показывается только при заданном лимите. Без него доля неопределена,
 * а полоса на всю ширину читалась бы как «всё израсходовано» — то есть ровно
 * наоборот тому, что происходит.
 */
function UsageBar({ label, used, limit }: { label: string; used: number; limit: number }) {
  const share = limit > 0 ? Math.min(used / limit, 1) : null;
  const tone =
    share === null ? "" : share >= 1 ? "bg-critical" : share >= 0.8 ? "bg-warning" : "bg-success";

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-body-sm text-text-primary">{label}</span>
        <span className="text-caption text-text-secondary tabular-nums">
          {used}
          {limit > 0 ? ` из ${limit}` : " · лимит не задан"}
        </span>
      </div>
      {share !== null && (
        <div className="bg-surface-hover h-1.5 w-full overflow-hidden rounded-full">
          <div className={`h-full rounded-full ${tone}`} style={{ width: `${share * 100}%` }} />
        </div>
      )}
    </div>
  );
}

/**
 * Подключение к Директу.
 *
 * Проверка настоящая: сервер спрашивает у площадки список рекламодателей.
 * Судить по наличию токена в настройках нельзя — истёкший, отозванный и
 * выпущенный не на то приложение токен выглядят одинаково, пока не спросишь.
 *
 * Остаток баллов API показывается всегда, когда он известен: узнать об
 * исчерпании суточного лимита в момент, когда работа уже встала, поздно —
 * лимит обновится только в полночь по Москве.
 */
function AdPlatformCard({ status }: { status: AdPlatformStatusRead | null }) {
  if (!status) return null;

  const isMock = status.adapter === "mock";

  return (
    <Card>
      <CardHeader
        title="Подключение к Директу"
        description="Проверяется настоящим запросом к площадке, а не наличием токена в настройках"
      />
      <div className="flex flex-col gap-3">
        <ModeRow
          label="Доступ"
          value={status.connected ? "Отвечает" : "Нет связи"}
          note={status.error ?? undefined}
          tone={status.connected && !isMock ? "success" : "warning"}
        />

        {!isMock && (
          <ModeRow
            label="Деньги"
            value={status.is_live ? "Боевой аккаунт" : "Песочница"}
            note={
              status.is_live
                ? "Действия касаются настоящих рекламных бюджетов"
                : "Изолирована от настоящих данных и денег"
            }
            tone={status.is_live ? "critical" : "warning"}
          />
        )}

        {status.units_limit > 0 && (
          <ModeRow
            label="Баллы API"
            value={`${status.units_rest} из ${status.units_limit}`}
            note={
              status.units_low
                ? "Осталось меньше десятой части. Лимит обновится в полночь по Москве"
                : undefined
            }
            tone={status.units_low ? "warning" : "success"}
          />
        )}

        {status.advertisers.length > 0 && (
          <div className="border-border flex flex-col gap-1.5 border-t pt-3">
            <span className="text-caption text-text-secondary">Доступные рекламодатели</span>
            {status.advertisers.map((advertiser) => (
              <div key={advertiser.login} className="flex flex-wrap items-center gap-2">
                <span className="text-body-sm text-text-primary">{advertiser.name}</span>
                <span className="text-caption text-text-secondary">{advertiser.login}</span>
                <StatusBadge tone={advertiser.can_edit ? "success" : "neutral"} size="sm">
                  {advertiser.can_edit ? "Можно менять" : "Только чтение"}
                </StatusBadge>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
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
  // Красный нужен ровно одному состоянию — боевому рекламному аккаунту.
  // «Действия касаются настоящих денег» не предупреждение, а другой уровень
  // ответственности, и цвет должен отличаться от обычной оговорки.
  tone: "success" | "warning" | "critical";
}) {
  return (
    <div className="border-border-subtle flex flex-col gap-1 border-b pb-3 last:border-b-0 last:pb-0">
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
    <div className="border-border-subtle flex flex-wrap items-center justify-between gap-2 border-b py-3 last:border-b-0">
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

/**
 * Строка активного входа.
 *
 * Текущий вход помечен и не имеет кнопки завершения: для выхода есть отдельная
 * кнопка в меню пользователя, которая ещё и убирает куку. Иначе человек
 * «завершил бы» сам себя и остался с нерабочей вкладкой, не понимая, почему.
 */
function SessionRow({ session, onEnd }: { session: SessionRead; onEnd: () => void }) {
  const seen = session.last_seen_at
    ? new Date(session.last_seen_at).toLocaleString("ru-RU", {
        day: "numeric",
        month: "long",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  return (
    <div className="border-border-subtle flex flex-wrap items-center justify-between gap-2 border-b py-3 last:border-b-0">
      <div className="flex flex-col">
        <span className="text-body-sm text-text-primary">{session.device}</span>
        <span className="text-caption text-text-secondary">
          {session.ip_address ?? "адрес неизвестен"}
          {seen && ` · был(а) ${seen}`}
        </span>
      </div>
      {session.is_current ? (
        <StatusBadge tone="success">Это устройство</StatusBadge>
      ) : (
        <Button size="sm" variant="ghost" onClick={onEnd}>
          Завершить
        </Button>
      )}
    </div>
  );
}
