"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { ApiError, OverviewRead, ProjectSummaryRead } from "@ads-os/schemas";
import {
  Card,
  CardHeader,
  DataTable,
  ErrorState,
  FilterBar,
  ProjectStatusBadge,
  StatusBadge,
  type DataTableColumn,
} from "@ads-os/ui";
import { AppShell } from "@/components/AppShell";
import { createApiClient } from "@/lib/api";
import { toApiError } from "@/lib/errors";

/**
 * Обзор всех проектов.
 *
 * Главная отвечает на вопрос «что делать сейчас» и показывает проекты списком
 * с подсказками. Этот экран отвечает на другой вопрос — «где мы отстаём» — и
 * потому устроен таблицей: у агентства с тридцатью клиентами вопросы вида «у
 * кого не проверен сайт» и «кого нельзя запускать» решаются сравнением
 * одинаковых колонок, а не чтением тридцати карточек подряд.
 *
 * Расходов, лидов и продаж здесь нет по той же причине, что и на главной:
 * рекламный кабинет не подключён, и любые цифры на этом месте были бы
 * выдуманными (v0.3 §140).
 */

type Filter = "all" | "attention" | "blocked" | "no_site" | "ready";

const ECONOMICS_LABEL: Record<string, string> = {
  complete: "Заполнена",
  limited: "Частично",
  insufficient: "Пусто",
};

const ECONOMICS_TONE: Record<string, "success" | "warning" | "neutral"> = {
  complete: "success",
  limited: "warning",
  insufficient: "neutral",
};

/** Проект требует действия, если он не дошёл до конца пути. */
function needsAttention(p: ProjectSummaryRead): boolean {
  return p.completed_count < p.total_count;
}

/** Сайт проверен и разрешает запуск. */
function isReady(p: ProjectSummaryRead): boolean {
  return p.audit_status === "completed" && p.can_launch && p.economics_mode === "complete";
}

/** Аудит прошёл и нашёл то, из-за чего запускаться нельзя. */
function isBlocked(p: ProjectSummaryRead): boolean {
  return p.audit_status === "completed" && !p.can_launch;
}

const MATCHES: Record<Filter, (p: ProjectSummaryRead) => boolean> = {
  all: () => true,
  attention: needsAttention,
  blocked: isBlocked,
  no_site: (p) => !p.website_url,
  ready: isReady,
};

export default function OverviewPage() {
  const api = useMemo(() => createApiClient(), []);
  const router = useRouter();

  const [overview, setOverview] = useState<OverviewRead | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let ignore = false;

    void (async () => {
      try {
        const result = await api.getOverview();
        if (ignore) return;
        setError(null);
        setOverview(result);
      } catch (err) {
        if (ignore) return;
        setError(toApiError(err));
      } finally {
        if (!ignore) setLoading(false);
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, reloadToken]);

  const projects = overview?.projects ?? [];
  const rows = projects.filter(MATCHES[filter]);

  const columns: DataTableColumn<ProjectSummaryRead>[] = [
    {
      key: "name",
      header: "Проект",
      width: "16rem",
      render: (p) => (
        <span className="flex flex-col gap-0.5">
          <span className="text-body-sm text-text-primary font-medium">{p.name}</span>
          {p.website_url ? (
            <span className="text-caption text-text-secondary truncate">{p.website_url}</span>
          ) : (
            <span className="text-caption text-text-secondary">Сайт не указан</span>
          )}
        </span>
      ),
    },
    {
      key: "status",
      header: "Статус",
      render: (p) => <ProjectStatusBadge status={p.status} />,
    },
    {
      key: "step",
      header: "Шаг",
      width: "13rem",
      render: (p) => (
        <span className="flex flex-col gap-0.5">
          <span className="text-body-sm text-text-primary">{p.current_step_label}</span>
          <span className="text-caption text-text-secondary">
            {p.completed_count} из {p.total_count}
          </span>
        </span>
      ),
    },
    {
      key: "audit",
      header: "Сайт",
      render: (p) => <AuditCell project={p} />,
    },
    {
      key: "economics",
      header: "Экономика",
      render: (p) => (
        <StatusBadge tone={ECONOMICS_TONE[p.economics_mode] ?? "neutral"}>
          {ECONOMICS_LABEL[p.economics_mode] ?? p.economics_mode}
        </StatusBadge>
      ),
    },
    {
      key: "competitors",
      header: "Конкуренты",
      numeric: true,
      render: (p) => p.competitors_checked,
    },
    {
      key: "next",
      header: "Что дальше",
      width: "20rem",
      render: (p) => (
        <span className="text-body-sm text-text-secondary">{p.next_action ?? "—"}</span>
      ),
    },
  ];

  return (
    <AppShell title="Обзор проектов" subtitle="Все клиенты в одной таблице">
      {error ? (
        <Card>
          <ErrorState
            title="Не удалось загрузить сводку"
            requestId={error.requestId}
            onRetry={() => {
              setLoading(true);
              setReloadToken((token) => token + 1);
            }}
          />
        </Card>
      ) : (
        <Card>
          <CardHeader
            title="Проекты"
            description="Одинаковые колонки для всех: так видно, где именно вы отстаёте"
          />

          <FilterBar
            label="Фильтр проектов"
            value={filter}
            onChange={(value) => setFilter(value as Filter)}
            className="mb-3"
            options={[
              { value: "all", label: "Все", count: projects.length },
              {
                value: "attention",
                label: "Требуют действия",
                count: projects.filter(needsAttention).length,
              },
              {
                value: "blocked",
                label: "Запуск запрещён",
                count: projects.filter(isBlocked).length,
              },
              {
                value: "no_site",
                label: "Без сайта",
                count: projects.filter((p) => !p.website_url).length,
              },
              { value: "ready", label: "Готовы", count: projects.filter(isReady).length },
            ]}
          />

          <DataTable
            caption="Сводка по всем проектам"
            columns={columns}
            rows={rows}
            rowKey={(p) => p.id}
            loading={loading}
            onRowClick={(p) => router.push(`/projects/${p.id}`)}
            empty={{
              title: filter === "all" ? "Проектов пока нет" : "В этой группе пусто",
              description:
                filter === "all"
                  ? "Заведите первый проект — дальше система подскажет каждый шаг"
                  : "Смените фильтр, чтобы увидеть остальные проекты",
            }}
          />
        </Card>
      )}
    </AppShell>
  );
}

/**
 * Состояние сайта одной ячейкой.
 *
 * Балл и разрешение на запуск — разные вещи, и показываются они вместе
 * намеренно: сайт с баллом 78 и критической находкой запускать нельзя, а по
 * одному баллу это выглядело бы хорошо.
 */
function AuditCell({ project }: { project: ProjectSummaryRead }) {
  if (project.audit_status !== "completed") {
    return (
      <StatusBadge tone="neutral">
        {project.audit_status === "running" ? "Проверяется" : "Не проверен"}
      </StatusBadge>
    );
  }

  return (
    <span className="flex items-center gap-2">
      <span className="text-body-sm text-text-primary tabular-nums">{project.audit_score}</span>
      <StatusBadge tone={project.can_launch ? "success" : "critical"}>
        {project.can_launch ? "Можно" : "Нельзя"}
      </StatusBadge>
    </span>
  );
}
