"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ApiError, NotificationRead } from "@ads-os/schemas";
import { Button, Card, EmptyState, ErrorState, Skeleton, StatusBadge } from "@ads-os/ui";
import type { Tone } from "@ads-os/tokens";
import { IconBell } from "@ads-os/ui/icons";
import { AppShell } from "@/components/AppShell";
import { createApiClient } from "@/lib/api";
import { toApiError } from "@/lib/errors";

const INFO = { label: "К сведению", tone: "info" as Tone };

const LEVEL: Record<string, { label: string; tone: Tone }> = {
  critical: { label: "Срочно", tone: "critical" },
  warning: { label: "Важно", tone: "warning" },
  info: INFO,
};

export default function NotificationsPage() {
  const api = useMemo(() => createApiClient(), []);

  const [items, setItems] = useState<NotificationRead[] | null>(null);
  const [unread, setUnread] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let ignore = false;

    void (async () => {
      try {
        const list = await api.listNotifications();
        if (ignore) return;
        setError(null);
        setItems(list.items);
        setUnread(list.unread);
      } catch (err) {
        if (!ignore) setError(toApiError(err));
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, reloadToken]);

  const reload = useCallback(() => setReloadToken((token) => token + 1), []);

  const markRead = async (id: string) => {
    try {
      await api.markNotificationRead(id);
      reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

  const markAll = async () => {
    try {
      await api.markAllNotificationsRead();
      reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

  return (
    <AppShell
      title="Уведомления"
      subtitle="То, что система заметила сама"
      actions={
        unread > 0 ? (
          <Button size="sm" variant="secondary" onClick={() => void markAll()}>
            Прочитать все
          </Button>
        ) : undefined
      }
    >
      {error ? (
        <Card>
          <ErrorState
            title="Не удалось загрузить уведомления"
            description={error.message}
            onRetry={reload}
          />
        </Card>
      ) : items === null ? (
        <Card>
          <Skeleton shape="card" />
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconBell size={24} />}
            title="Пока всё спокойно"
            description="Здесь появятся сообщения о том, что на сайте клиента что-то сломалось или перестало открываться. Пустой список — это хорошая новость, а не отсутствие проверок."
          />
        </Card>
      ) : (
        items.map((item) => <NotificationCard key={item.id} item={item} onRead={markRead} />)
      )}
    </AppShell>
  );
}

function NotificationCard({
  item,
  onRead,
}: {
  item: NotificationRead;
  onRead: (id: string) => void;
}) {
  const level = LEVEL[item.level] ?? INFO;
  const when = new Date(item.created_at).toLocaleString("ru-RU", {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    // Прочитанное не прячется, а бледнеет: список должен оставаться историей
    // событий, а не только очередью дел.
    <Card className={item.is_read ? "opacity-60" : ""}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={level.tone}>{level.label}</StatusBadge>
            <span className="text-body-sm text-text-primary font-medium">{item.title}</span>
          </div>
          {/* Что делать — обязательная часть: тревога без выхода вредит
              больше, чем помогает. */}
          <p className="text-body-sm text-text-secondary">{item.body}</p>
          <p className="text-caption text-text-secondary">
            {item.project_name} · {when}
          </p>
        </div>
        {!item.is_read && (
          <Button size="sm" variant="ghost" onClick={() => onRead(item.id)}>
            Прочитано
          </Button>
        )}
      </div>
    </Card>
  );
}
