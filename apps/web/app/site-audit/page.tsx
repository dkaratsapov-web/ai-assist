"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  type ApiError,
  type AuditIssueRead,
  type AuditRead,
  type CategoryRead,
  type ProjectRead,
} from "@ads-os/schemas";
import {
  AlertCard,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  KpiCard,
  ModuleStatusBadge,
  ProjectSwitcher,
  Skeleton,
  StatusBadge,
} from "@ads-os/ui";
import type { Tone } from "@ads-os/tokens";
import { IconGlobe } from "@ads-os/ui/icons";
import { AppShell } from "@/components/AppShell";
import { createApiClient, isApiConfigured } from "@/lib/api";
import { toApiError } from "@/lib/errors";

/** Человеческие названия категорий. Ключи приходят с backend. */
const CATEGORY_LABELS: Record<string, string> = {
  technical: "Техническое состояние",
  offer: "Предложение",
  conversion: "Конверсия",
  trust: "Доверие",
  tracking: "Аналитика",
};

const VERDICT: Record<string, { label: string; tone: Tone }> = {
  ready: { label: "Можно запускать рекламу", tone: "success" },
  ready_with_warnings: { label: "Запускать можно, есть замечания", tone: "warning" },
  not_ready: { label: "Запускать рано", tone: "critical" },
};

/** Как часто перечитывать статус, пока аудит выполняется. */
const POLL_INTERVAL_MS = 3000;

function isRunning(audit: AuditRead | null): boolean {
  return audit?.status === "queued" || audit?.status === "running";
}

export default function SiteAuditPage() {
  // useSearchParams требует границы Suspense при пререндере страницы.
  return (
    <Suspense
      fallback={
        <AppShell title="Аудит сайта">
          <Skeleton shape="card" />
        </AppShell>
      }
    >
      <SiteAuditScreen />
    </Suspense>
  );
}

function SiteAuditScreen() {
  const api = useMemo(() => createApiClient(), []);
  // Проект может прийти ссылкой из карточки проекта.
  const requestedProject = useSearchParams().get("project");
  const configured = isApiConfigured();

  const [projects, setProjects] = useState<ProjectRead[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [audit, setAudit] = useState<AuditRead | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [starting, setStarting] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!configured) return;
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
  }, [api, configured, reloadToken, requestedProject]);

  // Пока аудит в очереди или выполняется, статус перечитывается по таймеру.
  // Опрос останавливается сразу после завершения: держать вечный таймер на
  // готовом результате незачем.
  const projectRef = useRef<string | null>(null);
  useEffect(() => {
    if (!selectedId) return;
    let ignore = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    // Смена проекта обнуляет прежний результат: показывать чужой аудит, пока
    // грузится нужный, нельзя.
    if (projectRef.current !== selectedId) {
      projectRef.current = selectedId;
      setAudit(null);
      setLoaded(false);
    }

    const poll = async () => {
      try {
        const result = await api.getAudit(selectedId);
        if (ignore) return;
        setError(null);
        setAudit(result);
        setLoaded(true);
        if (isRunning(result)) {
          timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
        }
      } catch (err) {
        if (ignore) return;
        setError(toApiError(err));
        setLoaded(true);
      }
    };

    void poll();

    return () => {
      ignore = true;
      if (timer) clearTimeout(timer);
    };
  }, [api, selectedId, reloadToken]);

  const project = projects?.find((p) => p.id === selectedId) ?? null;
  const running = isRunning(audit);

  const start = async () => {
    if (!selectedId) return;
    setStarting(true);
    setError(null);
    try {
      const result = await api.startAudit(selectedId);
      setAudit(result);
      setLoaded(true);
      // Ответ приходит со статусом «в очереди» — опрос подхватит его сам.
      setReloadToken((token) => token + 1);
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setStarting(false);
    }
  };

  const verdict = audit?.verdict ? VERDICT[audit.verdict] : null;
  const critical = (audit?.issues ?? []).filter((i) => i.severity === "critical");
  const rest = (audit?.issues ?? []).filter((i) => i.severity !== "critical");

  return (
    <AppShell title="Аудит сайта" subtitle="Проверка готовности посадочной страницы к рекламе">
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
            title="Не удалось загрузить данные"
            description={error.message}
            requestId={error.requestId}
            onRetry={() => setReloadToken((token) => token + 1)}
          />
        </Card>
      ) : (
        <>
          <section className="flex flex-wrap items-end justify-between gap-4">
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

            <div className="flex items-center gap-3">
              {audit && <ModuleStatusBadge status={audit.status} size="md" />}
              <Button
                onClick={start}
                loading={starting}
                disabled={running || !project?.website_url}
              >
                {audit ? "Проверить заново" : "Проверить сайт"}
              </Button>
            </div>
          </section>

          {project && !project.website_url && (
            <Card>
              <EmptyState
                title="У проекта не указан адрес сайта"
                description="Добавьте адрес в настройках проекта — без него проверять нечего."
              />
            </Card>
          )}

          {!loaded && project?.website_url && (
            <Card>
              <Skeleton shape="card" />
            </Card>
          )}

          {loaded && !audit && project?.website_url && (
            <Card>
              <EmptyState
                icon={<IconGlobe size={24} />}
                title="Сайт ещё не проверяли"
                description="Проверка занимает до минуты: система откроет страницу, оценит предложение, форму заявки, доверие и наличие счётчика Метрики."
              />
            </Card>
          )}

          {running && (
            <Card>
              <div className="flex flex-col gap-2">
                <p className="text-body text-text-primary">Проверяем сайт</p>
                <p className="text-body-sm text-text-secondary">
                  {audit?.url} — обычно это занимает меньше минуты. Страница обновится сама.
                </p>
              </div>
            </Card>
          )}

          {audit?.status === "failed" && (
            <Card className="border-critical-border bg-critical-bg">
              <div className="flex flex-col gap-1">
                <p className="text-body text-text-primary font-medium">Проверить сайт не удалось</p>
                {/* Показывается причина, понятная человеку, а не текст исключения. */}
                <p className="text-body-sm text-text-secondary">{audit.error_reason}</p>
              </div>
            </Card>
          )}

          {audit?.status === "completed" && (
            <>
              <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                <Card>
                  <CardHeader title="Готовность к рекламе" />
                  <div className="flex flex-col gap-3">
                    <KpiCard label="Общая оценка" value={`${audit.score ?? 0} из 100`} />
                    {verdict && (
                      <StatusBadge tone={verdict.tone} size="md" dot>
                        {verdict.label}
                      </StatusBadge>
                    )}
                    {!audit.can_launch && (
                      // Автозапуск заблокирован критическими находками (v0.3 §15).
                      // Формулировка прямая: иначе блокировку принимают за совет.
                      <p className="text-body-sm text-text-secondary">
                        Пока критические замечания не устранены, запуск кампаний недоступен.
                      </p>
                    )}
                  </div>
                </Card>

                <Card className="lg:col-span-2">
                  <CardHeader
                    title="По разделам"
                    description="Каждый раздел оценивается отдельно — видно, что именно тянет вниз"
                  />
                  <div className="flex flex-col gap-3">
                    {audit.categories.map((category) => (
                      <CategoryRow key={category.category} category={category} />
                    ))}
                  </div>
                </Card>
              </section>

              <Card>
                <CardHeader
                  title="Что делать"
                  description={
                    audit.issues.length === 0
                      ? "Замечаний нет"
                      : "Сначала критические — они мешают запуску"
                  }
                />
                <div className="flex flex-col">
                  {[...critical, ...rest].map((issue, index) => (
                    <IssueRow key={`${issue.category}-${index}`} issue={issue} />
                  ))}
                  {audit.issues.length === 0 && (
                    <p className="text-body-sm text-text-secondary">
                      Сайт готов к рекламе, доработки не требуются.
                    </p>
                  )}
                </div>
              </Card>

              <Card>
                <CardHeader title="Проверенная страница" />
                <dl className="text-body-sm grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <Row label="Адрес" value={audit.final_url ?? audit.url} />
                  <Row label="Счётчик Метрики" value={audit.metrica_counter ?? "не найден"} />
                  <Row
                    label="Проверено"
                    value={
                      audit.finished_at ? new Date(audit.finished_at).toLocaleString("ru-RU") : "—"
                    }
                  />
                </dl>
              </Card>
            </>
          )}
        </>
      )}
    </AppShell>
  );
}

/**
 * Строка категории со шкалой.
 *
 * Шкала подписана числом: полоса без числа читается как «примерно нормально» и
 * не даёт понять, сколько именно не хватает.
 */
function CategoryRow({ category }: { category: CategoryRead }) {
  const tone =
    category.score >= 80 ? "bg-success" : category.score >= 50 ? "bg-warning" : "bg-critical";
  const findings = category.findings ?? [];

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-body-sm text-text-primary">
          {CATEGORY_LABELS[category.category] ?? category.category}
        </span>
        <span className="text-caption text-text-secondary tabular-nums">
          {category.score} / 100
        </span>
      </div>
      <div className="bg-surface-hover h-1.5 w-full overflow-hidden rounded-full">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${category.score}%` }} />
      </div>
      {findings.length > 0 && (
        <p className="text-caption text-text-secondary">{findings.join(" · ")}</p>
      )}
    </div>
  );
}

function IssueRow({ issue }: { issue: AuditIssueRead }) {
  return (
    <div className="border-border flex flex-col gap-1 border-b py-3 last:border-b-0">
      <AlertCard
        level={issue.severity as "critical" | "warning" | "recommendation" | "info"}
        message={issue.title}
      />
      {/* Находка без действия бесполезна: рядом всегда стоит, что сделать. */}
      <p className="text-body-sm text-text-secondary pl-7">{issue.action}</p>
    </div>
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
