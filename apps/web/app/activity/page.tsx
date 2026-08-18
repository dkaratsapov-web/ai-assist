"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ActivityRead, ApiError, ProjectRead } from "@ads-os/schemas";
import { Card, EmptyState, ErrorState, FilterBar, Skeleton } from "@ads-os/ui";
import { IconReport } from "@ads-os/ui/icons";
import { AppShell } from "@/components/AppShell";
import { createApiClient } from "@/lib/api";
import { toApiError } from "@/lib/errors";

/** Значение фильтра, означающее «без разбора по проектам». */
const ALL = "all";

export default function ActivityPage() {
  const api = useMemo(() => createApiClient(), []);

  const [projects, setProjects] = useState<ProjectRead[] | null>(null);
  const [scope, setScope] = useState<string>(ALL);
  const [items, setItems] = useState<ActivityRead[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let ignore = false;

    void (async () => {
      try {
        const list = await api.listProjects();
        if (ignore) return;
        setProjects(list.items);
      } catch {
        // Названия проектов нужны только для фильтра. Если их не удалось
        // получить, журнал всё равно читается — просто без разбивки.
        if (!ignore) setProjects([]);
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, reloadToken]);

  useEffect(() => {
    let ignore = false;

    void (async () => {
      try {
        const list = await api.listActivity(scope === ALL ? null : scope);
        if (ignore) return;
        setError(null);
        setItems(list.items);
      } catch (err) {
        if (ignore) return;
        setError(toApiError(err));
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, scope, reloadToken]);

  const reload = useCallback(() => setReloadToken((token) => token + 1), []);

  const options = [
    { value: ALL, label: "Все проекты" },
    ...(projects ?? []).map((project) => ({ value: project.id, label: project.name })),
  ];

  const days = useMemo(() => groupByDay(items ?? []), [items]);

  return (
    <AppShell title="Журнал действий" subtitle="Кто что изменил и когда">
      {error ? (
        <Card>
          <ErrorState
            title="Не удалось загрузить журнал"
            description={error.message}
            requestId={error.requestId}
            onRetry={reload}
          />
        </Card>
      ) : (
        <>
          {options.length > 1 && (
            <FilterBar
              options={options}
              value={scope}
              onChange={setScope}
              label="Фильтр проектов"
            />
          )}

          {items === null ? (
            <Card>
              <Skeleton shape="card" />
            </Card>
          ) : items.length === 0 ? (
            <Card>
              <EmptyState
                icon={<IconReport size={24} />}
                title="Записей пока нет"
                description="Здесь появятся изменения проектов, экономики, конкурентов и состава команды — с именем того, кто их сделал."
              />
            </Card>
          ) : (
            days.map((day) => (
              <Card key={day.label}>
                <h2 className="text-caption text-text-secondary mb-2 font-medium">{day.label}</h2>
                <div className="flex flex-col">
                  {day.items.map((item) => (
                    <ActivityRow key={item.id} item={item} />
                  ))}
                </div>
              </Card>
            ))
          )}
        </>
      )}
    </AppShell>
  );
}

function ActivityRow({ item }: { item: ActivityRead }) {
  const time = new Date(item.created_at).toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });

  const changes = Object.entries(item.details ?? {});

  return (
    <div className="border-border-subtle flex flex-wrap items-start justify-between gap-3 border-b py-3 last:border-b-0">
      <div className="flex min-w-0 flex-col gap-1">
        <span className="text-body-sm text-text-primary">
          {/* Имя автора выделено: журнал читают ради ответа на вопрос «кто». */}
          <span className="font-medium">{item.user_name}</span> {item.action_label}{" "}
          <span className="text-text-secondary">«{item.subject}»</span>
        </span>
        {changes.length > 0 && (
          <ul className="flex flex-col gap-0.5">
            {changes.map(([field, value]) => (
              <li key={field} className="text-caption text-text-secondary">
                {fieldLabel(field)}: {value}
              </li>
            ))}
          </ul>
        )}
      </div>
      <span className="text-caption text-text-secondary shrink-0 tabular-nums">{time}</span>
    </div>
  );
}

/**
 * Человеческие названия полей.
 *
 * Список неполный намеренно: неизвестное поле показывается как есть, а не
 * прячется. Пропавшая строка была бы хуже английского названия — она выглядела
 * бы как «ничего не менялось».
 */
const FIELD_LABELS: Record<string, string> = {
  name: "название",
  website_url: "сайт",
  region: "регион",
  status: "статус",
  monthly_budget: "бюджет",
  average_check: "средний чек",
  margin_percent: "маржа",
  target_cpa: "целевой CPA",
  main_conversion: "главная конверсия",
  conversion_rate: "конверсия сайта",
  role: "роль",
  is_active: "доступ",
  full_name: "имя",
  email: "почта",
};

function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}

interface Day {
  label: string;
  items: ActivityRead[];
}

/**
 * Разбивка ленты по дням.
 *
 * Сегодняшний и вчерашний дни называются словами: дата в них ничего не
 * добавляет, а «сегодня» сразу отвечает на вопрос, свежая ли запись.
 */
function groupByDay(items: ActivityRead[]): Day[] {
  const today = dayKey(new Date());
  const yesterday = dayKey(new Date(Date.now() - 24 * 60 * 60 * 1000));

  const days: Day[] = [];

  for (const item of items) {
    const moment = new Date(item.created_at);
    const key = dayKey(moment);

    const label =
      key === today
        ? "Сегодня"
        : key === yesterday
          ? "Вчера"
          : moment.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });

    const last = days[days.length - 1];
    if (last && last.label === label) last.items.push(item);
    else days.push({ label, items: [item] });
  }

  return days;
}

function dayKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}
