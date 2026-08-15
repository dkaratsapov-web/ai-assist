"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { ApiError, OverviewRead, ProjectSummaryRead } from "@ads-os/schemas";
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  KpiCard,
  ProjectStatusBadge,
  Skeleton,
  StatusBadge,
} from "@ads-os/ui";
import { IconFolder, IconInfo } from "@ads-os/ui/icons";
import { AppShell } from "@/components/AppShell";
import { createApiClient, isApiConfigured } from "@/lib/api";
import { toApiError } from "@/lib/errors";

/**
 * Главный экран (v0.3 §125).
 *
 * Отвечает на три вопроса: что происходит, что требует внимания, что делать
 * дальше.
 *
 * До этого экран был собран на выдуманных данных: расход, лиды, продажи,
 * AI-рекомендации. Выглядело убедительно и означало ровно обратное тому, что
 * есть на самом деле, — будто реклама идёт и приносит результат. Пока
 * рекламный кабинет не подключён, показывать нечего, и сказать об этом нужно
 * прямо (v0.3 §140).
 */
export default function DashboardPage() {
  const api = useMemo(() => createApiClient(), []);
  const configured = isApiConfigured();

  const [overview, setOverview] = useState<OverviewRead | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!configured) return;
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
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, configured, reloadToken]);

  const projects = overview?.projects ?? [];
  const withSite = projects.filter((p) => p.website_url).length;
  const checked = projects.filter((p) => p.audit_status === "completed").length;
  const readyEconomics = projects.filter((p) => p.economics_mode === "complete").length;

  return (
    <AppShell
      title="Главная"
      subtitle="Состояние проектов и ближайшие действия"
      actions={
        <Link href="/projects">
          <Button size="sm" variant="secondary">
            Все проекты
          </Button>
        </Link>
      }
    >
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
            title="Не удалось загрузить сводку"
            description={error.message}
            requestId={error.requestId}
            onRetry={() => setReloadToken((token) => token + 1)}
          />
        </Card>
      ) : overview === null ? (
        <div className="flex flex-col gap-4">
          <Skeleton shape="card" />
          <Skeleton shape="card" />
        </div>
      ) : overview.total === 0 ? (
        <Card>
          <EmptyState
            icon={<IconFolder size={24} />}
            title="Проектов пока нет"
            description="Создайте первый проект — дальше система подскажет, что делать на каждом шаге."
          />
        </Card>
      ) : (
        <>
          {/* Счётчики считают то, что система действительно знает: сколько
              проектов заведено и на каком они шаге. Денежных показателей здесь
              нет и не будет, пока не подключён рекламный кабинет. */}
          <section aria-labelledby="counters">
            <h2 id="counters" className="sr-only">
              Состояние проектов
            </h2>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <KpiCard label="Проектов" value={String(overview.total)} />
              <KpiCard label="Требуют действия" value={String(overview.needs_attention)} />
              <KpiCard label="Сайт проверен" value={`${checked} из ${withSite || 0}`} />
              <KpiCard
                label="Экономика заполнена"
                value={`${readyEconomics} из ${overview.total}`}
              />
            </div>
          </section>

          {!overview.ad_platform_connected && (
            <Card>
              <div className="flex items-start gap-3">
                <span className="text-text-secondary mt-0.5">
                  <IconInfo size={18} />
                </span>
                <div className="flex flex-col gap-1">
                  <p className="text-body-sm text-text-primary font-medium">
                    Рекламный кабинет не подключён
                  </p>
                  <p className="text-body-sm text-text-secondary">
                    Поэтому здесь нет расходов, лидов и продаж. Появятся они только вместе с
                    настоящими данными из Яндекс Директа и Метрики — до тех пор любые цифры на этом
                    месте были бы выдуманными.
                  </p>
                </div>
              </div>
            </Card>
          )}

          <Card>
            <CardHeader
              title="Проекты"
              description="Что нужно сделать в каждом — по порядку работы"
            />
            <div className="flex flex-col">
              {projects.map((project) => (
                <ProjectRow key={project.id} project={project} />
              ))}
            </div>
          </Card>
        </>
      )}
    </AppShell>
  );
}

const ECONOMICS_LABEL: Record<string, string> = {
  complete: "Экономика заполнена",
  limited: "Экономика частично",
  insufficient: "Экономика не заполнена",
};

function ProjectRow({ project }: { project: ProjectSummaryRead }) {
  return (
    <Link
      href={`/projects/${project.id}`}
      className="border-border focus-visible:outline-focus hover:bg-surface-hover -mx-2 flex flex-col gap-2 border-b px-2 py-3 last:border-b-0 focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-body text-text-primary font-medium">{project.name}</span>
        <div className="flex items-center gap-2">
          <ProjectStatusBadge status={project.status} />
          <StatusBadge tone="neutral">
            {project.completed_count} из {project.total_count}
          </StatusBadge>
        </div>
      </div>

      {/* Одна строка о том, что делать дальше, вместо набора метрик: пока
          рекламных данных нет, полезен именно следующий шаг. */}
      <p className="text-body-sm text-text-secondary">
        {project.next_action ?? `Шаг «${project.current_step_label}» — всё сделано`}
      </p>

      <div className="text-caption text-text-secondary flex flex-wrap items-center gap-x-4 gap-y-1">
        <span>
          {project.audit_status === "completed"
            ? `Сайт: ${project.audit_score} из 100`
            : project.audit_status === "failed"
              ? "Сайт: проверить не удалось"
              : project.website_url
                ? "Сайт: не проверялся"
                : "Сайт не указан"}
        </span>
        <span>Конкурентов: {project.competitors_checked}</span>
        <span>{ECONOMICS_LABEL[project.economics_mode]}</span>
        {!project.can_launch && (
          <span className="text-critical">Запуск закрыт: критические замечания</span>
        )}
      </div>
    </Link>
  );
}
