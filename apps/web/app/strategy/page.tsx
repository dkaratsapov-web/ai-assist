"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { ApiError, LaunchPlanRead, ProjectRead } from "@ads-os/schemas";
import {
  Card,
  CardHeader,
  ErrorState,
  ProjectSwitcher,
  Skeleton,
  StatusBadge,
  formatCurrency,
  formatNumber,
  plural,
} from "@ads-os/ui";
import type { Tone } from "@ads-os/tokens";
import { AppShell } from "@/components/AppShell";
import { createApiClient } from "@/lib/api";
import { toApiError } from "@/lib/errors";

const STATUS: Record<string, { label: string; tone: Tone }> = {
  ready: { label: "Можно запускать", tone: "success" },
  risky: { label: "Можно, но с оговорками", tone: "warning" },
  blocked: { label: "Сначала исправить", tone: "critical" },
};

export default function StrategyPage() {
  return (
    <Suspense
      fallback={
        <AppShell title="Стратегия запуска">
          <Skeleton shape="card" />
        </AppShell>
      }
    >
      <StrategyScreen />
    </Suspense>
  );
}

function StrategyScreen() {
  const api = useMemo(() => createApiClient(), []);
  const requestedProject = useSearchParams().get("project");

  const [projects, setProjects] = useState<ProjectRead[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [plan, setPlan] = useState<LaunchPlanRead | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let ignore = false;

    void (async () => {
      try {
        const list = await api.listProjects();
        if (ignore) return;
        setError(null);
        setProjects(list.items);
        setSelectedId((current) => current ?? requestedProject ?? list.items[0]?.id ?? null);
      } catch (err) {
        if (ignore) return;
        setError(toApiError(err));
        setProjects([]);
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, requestedProject]);

  useEffect(() => {
    if (!selectedId) return;
    let ignore = false;

    void (async () => {
      try {
        const result = await api.getStrategy(selectedId);
        if (ignore) return;
        setError(null);
        setPlan(result);
      } catch (err) {
        if (!ignore) setError(toApiError(err));
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, selectedId]);

  // План относится к выбранному проекту, а не «какой-то есть». Пока пришедший
  // план от другого проекта, экран показывает загрузку, а не чужие цифры.
  const current = plan && plan.project_id === selectedId ? plan : null;
  const status = current ? STATUS[current.status] : null;

  return (
    <AppShell title="Стратегия запуска" subtitle="С чего начинать и сколько ждать первых выводов">
      {error ? (
        <Card>
          <ErrorState title="Не удалось построить план" description={error.message} />
        </Card>
      ) : (
        <>
          <div className="w-full max-w-sm">
            {projects === null ? (
              <Skeleton shape="control" />
            ) : (
              <ProjectSwitcher
                projects={projects.map((p) => ({ id: p.id, name: p.name, status: p.status }))}
                selectedId={selectedId ?? ""}
                onSelect={setSelectedId}
              />
            )}
          </div>

          {current === null ? (
            <Card>
              <Skeleton shape="card" />
            </Card>
          ) : (
            <>
              {current.blockers.length > 0 && (
                <Card className="border-critical-border bg-critical-bg">
                  <CardHeader title="Запускаться рано" />
                  <ul className="flex flex-col gap-2">
                    {current.blockers.map((blocker) => (
                      <li key={blocker} className="text-body-sm text-text-primary">
                        {blocker}
                      </li>
                    ))}
                  </ul>
                </Card>
              )}

              {current.strategy_label && (
                <Card>
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <CardHeader title="Стратегия на старте" />
                    {status && <StatusBadge tone={status.tone}>{status.label}</StatusBadge>}
                  </div>
                  <p className="text-body text-text-primary">{current.strategy_label}</p>
                  {/* Обоснование стоит рядом с советом, а не под катом: совет,
                      который нельзя проверить, специалист принимать не должен. */}
                  <p className="text-body-sm text-text-secondary mt-2">{current.strategy_reason}</p>
                </Card>
              )}

              {current.weekly_conversions !== null && (
                <Card>
                  <CardHeader title="Что ожидать" />
                  <ul className="flex flex-col gap-2">
                    <Line
                      label="Заявок в неделю"
                      // Заявок не бывает 102,6 — округляем. Дробная доля здесь
                      // не точность, а видимость точности: она берётся из
                      // деления месяца на 4,33 недели.
                      value={`около ${formatNumber(Math.round(Number(current.weekly_conversions)))}`}
                      note={
                        current.learning_ready === false
                          ? "мало для обучения автостратегии"
                          : undefined
                      }
                    />
                    <Line
                      label="До первых выводов"
                      value={
                        current.test_weeks !== null
                          ? `${current.test_weeks} ${plural(current.test_weeks, "неделя", "недели", "недель")}`
                          : "слишком долго"
                      }
                      note={
                        current.test_weeks === null
                          ? "статистика набирается неразумно медленно"
                          : "накопится 30 заявок — с этого объёма выводы перестают быть случайными"
                      }
                    />
                    {current.test_budget !== null && (
                      <Line
                        label="Бюджет теста"
                        // Копейки в плановом бюджете — ложная точность: сам
                        // бюджет задан круглым числом, и до копеек он всё
                        // равно не соблюдается.
                        value={formatCurrency(Math.round(Number(current.test_budget)))}
                      />
                    )}
                  </ul>
                </Card>
              )}

              {current.advice.length > 0 && (
                <Card>
                  <CardHeader title="Что сделать помимо запуска" />
                  <ul className="flex flex-col gap-2">
                    {current.advice.map((note) => (
                      <li key={note} className="text-body-sm text-text-secondary">
                        {note}
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
            </>
          )}
        </>
      )}
    </AppShell>
  );
}

function Line({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <li className="flex flex-wrap items-baseline justify-between gap-2">
      <span className="text-body-sm text-text-primary">{label}</span>
      <span className="flex items-baseline gap-2">
        {note && <span className="text-caption text-text-secondary">{note}</span>}
        <span className="text-body-sm text-text-primary tabular-nums">{value}</span>
      </span>
    </li>
  );
}
