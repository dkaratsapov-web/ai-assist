"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  type ApiError,
  type AuditChangesRead,
  type AuditPageRead,
  type AuditHistoryItem,
  type AuditIssueRead,
  type AuditRead,
  type CategoryRead,
  type ProjectRead,
  type ReviewNoteRead,
  type ReviewRead,
} from "@ads-os/schemas";
import {
  AlertCard,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Input,
  KpiCard,
  Modal,
  ModuleStatusBadge,
  ProjectSwitcher,
  Skeleton,
  StatusBadge,
} from "@ads-os/ui";
import type { Tone } from "@ads-os/tokens";
import { IconGlobe } from "@ads-os/ui/icons";
import { AppShell } from "@/components/AppShell";
import { createApiClient } from "@/lib/api";
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

  const [projects, setProjects] = useState<ProjectRead[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pages, setPages] = useState<AuditPageRead[]>([]);
  // null означает «главная страница проекта»: её адрес знает backend, и
  // дублировать это знание на фронте незачем.
  const [page, setPage] = useState<string | null>(null);
  const [addingPage, setAddingPage] = useState(false);
  const [pageDraft, setPageDraft] = useState("");
  const [audit, setAudit] = useState<AuditRead | null>(null);
  const [history, setHistory] = useState<AuditHistoryItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [starting, setStarting] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

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
  }, [api, reloadToken, requestedProject]);

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
      setHistory([]);
      setLoaded(false);
    }

    const poll = async () => {
      try {
        // История читается вместе с последним результатом: они всегда
        // показываются рядом, и второй запрос отдельным эффектом дал бы
        // мигание — сначала новый результат, потом устаревшая история.
        const [result, past, pageList] = await Promise.all([
          api.getAudit(selectedId, page),
          api.getAuditHistory(selectedId),
          api.listAuditPages(selectedId),
        ]);
        if (ignore) return;
        setError(null);
        setAudit(result);
        setHistory(past.items);
        setPages(pageList.items);
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
  }, [api, selectedId, page, reloadToken]);

  const project = projects?.find((p) => p.id === selectedId) ?? null;
  const running = isRunning(audit);

  const addPage = async () => {
    if (!selectedId) return;
    const url = pageDraft.trim();
    setStarting(true);
    setError(null);
    try {
      await api.startAudit(selectedId, url);
      setAddingPage(false);
      setPageDraft("");
      // Переключаемся на добавленную страницу: человек только что попросил её
      // проверить и ждёт результат именно по ней.
      setPage(url);
      setReloadToken((token) => token + 1);
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setStarting(false);
    }
  };

  const start = async () => {
    if (!selectedId) return;
    setStarting(true);
    setError(null);
    try {
      const result = await api.startAudit(selectedId, page);
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
  const active = (audit?.issues ?? []).filter((i) => !i.dismissed);
  const critical = active.filter((i) => i.severity === "critical");
  const rest = active.filter((i) => i.severity !== "critical");
  // Скрытые не исчезают, а уезжают вниз отдельным списком: проверка их
  // по-прежнему находит, просто человек решил, что для этого проекта они не
  // важны — и это решение должно оставаться видимым и обратимым.
  const dismissed = (audit?.issues ?? []).filter((i) => i.dismissed);

  const dismiss = async (issueKey: string, reason: string) => {
    if (!selectedId) return;
    try {
      await api.dismissIssue(selectedId, { issue_key: issueKey, reason: reason || null });
      setReloadToken((token) => token + 1);
    } catch (err) {
      setError(toApiError(err));
    }
  };

  const restore = async (issueKey: string) => {
    if (!selectedId) return;
    try {
      await api.restoreIssue(selectedId, issueKey);
      setReloadToken((token) => token + 1);
    } catch (err) {
      setError(toApiError(err));
    }
  };

  return (
    <AppShell title="Аудит сайта" subtitle="Проверка готовности посадочной страницы к рекламе">
      {error ? (
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

          {pages.length > 0 && project?.website_url && (
            <PagePicker
              pages={pages}
              selected={page ?? project.website_url}
              onSelect={(url) => setPage(url === project.website_url ? null : url)}
              onAdd={() => setAddingPage(true)}
            />
          )}

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

          {audit?.status === "completed" && audit.changes?.compared && (
            <ChangesCard changes={audit.changes} />
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
                    active.length === 0
                      ? "Замечаний нет"
                      : "Сначала критические — они мешают запуску"
                  }
                />
                <div className="flex flex-col">
                  {[...critical, ...rest].map((issue, index) => (
                    <IssueRow
                      key={issue.key ?? `${issue.category}-${index}`}
                      issue={issue}
                      onDismiss={
                        // Критическое замечание скрыть нельзя: блокировка,
                        // которую можно спрятать, не является блокировкой.
                        issue.key && issue.severity !== "critical"
                          ? (reason) => void dismiss(issue.key as string, reason)
                          : undefined
                      }
                    />
                  ))}
                  {active.length === 0 && (
                    <p className="text-body-sm text-text-secondary">
                      {audit.issues.length === 0
                        ? "Сайт готов к рекламе, доработки не требуются."
                        : "Все замечания отмечены неактуальными."}
                    </p>
                  )}
                </div>
              </Card>

              <ReviewCard review={audit.review} />

              {dismissed.length > 0 && (
                <Card>
                  <CardHeader
                    title="Отмечено как неактуальное"
                    description="Проверка их по-прежнему находит, и на балл они влияют — скрыт только рабочий список"
                  />
                  <div className="flex flex-col">
                    {dismissed.map((issue, index) => (
                      <DismissedRow
                        key={issue.key ?? `${issue.category}-${index}`}
                        issue={issue}
                        onRestore={() => void restore(issue.key as string)}
                      />
                    ))}
                  </div>
                </Card>
              )}

              {/* История показывается только когда есть с чем сравнивать:
                  одна строка «единственная проверка» пользы не несёт. */}
              {history.length > 1 && (
                <Card>
                  <CardHeader title="История проверок" description="Помогли ли доработки сайта" />
                  <div className="flex flex-col">
                    {history.map((item) => (
                      <HistoryRow key={item.id} item={item} />
                    ))}
                  </div>
                </Card>
              )}

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
      <Modal
        open={addingPage}
        onClose={() => setAddingPage(false)}
        title="Проверить ещё одну страницу"
        description="Адрес другой посадочной того же сайта. В кампании их обычно несколько, и оценивать все по главной — значит не проверять их вовсе."
        footer={
          <>
            <Button variant="secondary" onClick={() => setAddingPage(false)}>
              Отмена
            </Button>
            <Button onClick={addPage} loading={starting} disabled={pageDraft.trim() === ""}>
              Проверить
            </Button>
          </>
        }
      >
        <Input
          label="Адрес страницы"
          value={pageDraft}
          onChange={(e) => setPageDraft(e.target.value)}
          placeholder={
            project?.website_url ? `${project.website_url}okna-pvh` : "https://сайт.ру/страница"
          }
          hint="Только страницы вашего сайта — чужие адреса проверять нельзя"
        />
      </Modal>
    </AppShell>
  );
}

/**
 * Переключатель проверенных страниц.
 *
 * Главная всегда первая и помечена, остальные — от худшей оценки к лучшей:
 * работать начинают с той страницы, которая тянет вниз.
 */
function PagePicker({
  pages,
  selected,
  onSelect,
  onAdd,
}: {
  pages: AuditPageRead[];
  selected: string;
  onSelect: (url: string) => void;
  onAdd: () => void;
}) {
  return (
    <Card>
      <CardHeader
        title="Посадочные страницы"
        description="Страница попадает сюда, когда её проверили"
      />
      <div className="flex flex-wrap items-center gap-2">
        {pages.map((item) => {
          const active = item.url === selected;
          return (
            <button
              key={item.url}
              type="button"
              aria-pressed={active}
              onClick={() => onSelect(item.url)}
              className={
                "rounded-pill text-caption focus-visible:outline-focus inline-flex items-center gap-1.5 px-3 py-1.5 font-medium focus-visible:outline-2 " +
                (active
                  ? "bg-cta text-cta-text"
                  : "bg-bg-secondary text-text-secondary hover:bg-surface-active")
              }
            >
              <span className="max-w-64 truncate">
                {item.is_primary ? "Главная" : shortPath(item.url)}
              </span>
              {item.score !== null && (
                <span className={active ? "opacity-70" : "text-text-secondary"}>{item.score}</span>
              )}
            </button>
          );
        })}
        <Button size="sm" variant="ghost" onClick={onAdd}>
          + Ещё страница
        </Button>
      </div>
    </Card>
  );
}

/** Путь без домена: домен у всех страниц один, и повторять его негде. */
function shortPath(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.pathname === "/" ? parsed.hostname : parsed.pathname;
  } catch {
    return url;
  }
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

function IssueRow({
  issue,
  onDismiss,
}: {
  issue: AuditIssueRead;
  onDismiss?: (reason: string) => void;
}) {
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");

  return (
    <div className="border-border flex flex-col gap-1 border-b py-3 last:border-b-0">
      <AlertCard
        level={issue.severity as "critical" | "warning" | "recommendation" | "info"}
        message={issue.title}
      />
      {/* Находка без действия бесполезна: рядом всегда стоит, что сделать. */}
      <p className="text-body-sm text-text-secondary pl-7">{issue.action}</p>

      {onDismiss && !asking && (
        <div className="pl-7">
          <Button size="sm" variant="ghost" onClick={() => setAsking(true)}>
            Неактуально для нас
          </Button>
        </div>
      )}

      {onDismiss && asking && (
        <div className="flex flex-wrap items-end gap-2 pl-7">
          <div className="min-w-48 flex-1">
            <Input
              label="Почему"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              hint="Не обязательно, но это прочитает тот, кто вернётся к проекту через полгода"
              placeholder="Цены считаем индивидуально"
            />
          </div>
          <Button
            size="sm"
            onClick={() => {
              onDismiss(reason);
              setAsking(false);
              setReason("");
            }}
          >
            Скрыть
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setAsking(false)}>
            Отмена
          </Button>
        </div>
      )}
    </div>
  );
}

function DismissedRow({ issue, onRestore }: { issue: AuditIssueRead; onRestore: () => void }) {
  return (
    <div className="border-border flex flex-wrap items-center justify-between gap-2 border-b py-2.5 last:border-b-0">
      <div className="flex min-w-0 flex-col">
        <span className="text-body-sm text-text-secondary">{issue.title}</span>
        <span className="text-caption text-text-secondary">
          {issue.dismissed_reason ? `${issue.dismissed_reason} · ` : ""}
          скрыл(а) {issue.dismissed_by}
        </span>
      </div>
      <Button size="sm" variant="ghost" onClick={onRestore}>
        Вернуть
      </Button>
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

/**
 * Строка истории.
 *
 * Балл сам по себе ничего не говорит: «74» — это лучше или хуже, чем было?
 * Поэтому рядом всегда стоит изменение, и именно оно набрано заметнее.
 */
function HistoryRow({ item }: { item: AuditHistoryItem }) {
  const when = new Date(item.finished_at ?? item.created_at).toLocaleString("ru-RU", {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="border-border flex flex-wrap items-center justify-between gap-3 border-b py-2.5 last:border-b-0">
      <span className="text-body-sm text-text-secondary">
        {when}
        {/* Счётчики рядом с датой, а не только изменение балла: «+3» не
            отличает исправленную мелочь от исправленной блокировки. */}
        {(item.fixed_count > 0 || item.appeared_count > 0) && (
          <span className="text-caption text-text-secondary block">
            {[
              item.fixed_count > 0 ? `исправлено: ${item.fixed_count}` : null,
              item.appeared_count > 0 ? `появилось: ${item.appeared_count}` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
        )}
      </span>

      <div className="flex items-center gap-3">
        {item.status === "completed" ? (
          <>
            <span className="text-body-sm text-text-primary tabular-nums">{item.score} из 100</span>
            {item.score_delta !== null && item.score_delta !== undefined && (
              <StatusBadge
                tone={
                  item.score_delta > 0 ? "success" : item.score_delta < 0 ? "critical" : "neutral"
                }
              >
                {item.score_delta > 0 ? `+${item.score_delta}` : String(item.score_delta)}
              </StatusBadge>
            )}
            {!item.can_launch && <StatusBadge tone="warning">Запуск закрыт</StatusBadge>}
          </>
        ) : (
          <span className="text-body-sm text-text-secondary">
            {item.error_reason ?? "Проверка не завершена"}
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * Что изменилось с прошлой проверки.
 *
 * Показывается выше оценки: человек, нажавший «Проверить заново», пришёл
 * именно за этим ответом, а не за баллом. Балл мог вырасти на три пункта, пока
 * критическая проблема осталась на месте.
 */
/** О чём говорит замечание модели. Ключи приходят с backend. */
const TOPIC_LABELS: Record<string, string> = {
  offer: "Предложение",
  objections: "Возражения",
  language: "Язык",
  match: "Совпадение с рекламой",
  structure: "Порядок изложения",
};

const GRADE: Record<string, { label: string; tone: Tone }> = {
  good: { label: "хорошо", tone: "success" },
  weak: { label: "слабо", tone: "warning" },
  missing: { label: "нет", tone: "critical" },
};

/**
 * Разбор страницы моделью.
 *
 * Стоит отдельно от списка замечаний и ниже него — и это не про вёрстку.
 * Замечания выше проверены кодом: их можно открыть и увидеть. Здесь мнение, и
 * оно бывает ошибочным. Поэтому карточка подписана как мнение, у каждого
 * пункта стоит цитата со страницы, а на балл готовности всё это не влияет
 * вовсе — балл посчитан по фактам ещё до того, как модель что-либо сказала.
 */
function ReviewCard({ review }: { review: ReviewRead }) {
  if (!review.available) {
    return (
      <Card>
        <CardHeader title="Разбор моделью" />
        <p className="text-body-sm text-text-secondary">{review.reason}</p>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title="Разбор моделью"
        description="Мнение, а не проверка: на оценку готовности не влияет"
      />
      <div className="flex flex-col gap-4">
        <p className="text-body-sm text-text-primary">{review.summary}</p>

        <dl className="text-body-sm grid grid-cols-1 gap-2 sm:grid-cols-2">
          <Row label="Сильнее всего" value={review.strongest} />
          <Row label="Мешает больше всего" value={review.weakest} />
        </dl>

        <div className="flex flex-col">
          {(review.notes ?? []).map((note, index) => (
            <ReviewNoteRow key={`${note.topic}-${index}`} note={note} />
          ))}
        </div>

        <p className="text-caption text-text-secondary">
          Модель: {review.model || "не указана"}. Уверенность:{" "}
          {Math.round((review.confidence ?? 0) * 100)}%. Спорить с этим разбором можно и нужно —
          последнее слово за специалистом.
        </p>
      </div>
    </Card>
  );
}

function ReviewNoteRow({ note }: { note: ReviewNoteRead }) {
  const grade = GRADE[note.grade] ?? { label: note.grade, tone: "warning" as Tone };

  return (
    <div className="border-border-subtle flex flex-col gap-1 border-b py-3 last:border-0">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone={grade.tone} size="sm" dot>
          {grade.label}
        </StatusBadge>
        <span className="text-body-sm text-text-primary font-medium">
          {TOPIC_LABELS[note.topic] ?? note.topic}
        </span>
      </div>
      <p className="text-body-sm text-text-primary">{note.what}</p>
      <p className="text-body-sm text-text-secondary">{note.fix}</p>
      {/* Цитата — единственное, чем мнение можно проверить, не открывая
          страницу заново. Без неё спорить с замечанием приходится вслепую. */}
      {note.quote && (
        <p className="text-caption text-text-secondary border-border-subtle border-l-2 pl-3 italic">
          «{note.quote}»
        </p>
      )}
    </div>
  );
}

function ChangesCard({ changes }: { changes: AuditChangesRead }) {
  const nothing = changes.fixed.length === 0 && changes.appeared.length === 0;

  if (nothing) {
    return (
      <Card>
        <p className="text-body-sm text-text-secondary">
          С прошлой проверки список замечаний не изменился.
        </p>
      </Card>
    );
  }

  return (
    <Card
      className={
        // Появившееся замечание важнее исправленного: обычно это значит, что
        // на сайте что-то сломали. Поэтому предупреждающий фон включает именно
        // оно, а не отсутствие исправлений.
        changes.appeared.length > 0 ? "border-warning-border bg-warning-bg" : ""
      }
    >
      <CardHeader title="Что изменилось с прошлой проверки" />
      <div className="flex flex-col gap-3">
        {changes.appeared.length > 0 && (
          <ChangeGroup title="Появилось" issues={changes.appeared} tone="warning" />
        )}
        {changes.fixed.length > 0 && (
          <ChangeGroup title="Исправлено" issues={changes.fixed} tone="success" />
        )}
        {changes.remaining.length > 0 && (
          <p className="text-caption text-text-secondary">
            Осталось без изменений: {changes.remaining.length}
          </p>
        )}
      </div>
    </Card>
  );
}

function ChangeGroup({
  title,
  issues,
  tone,
}: {
  title: string;
  issues: AuditIssueRead[];
  tone: Tone;
}) {
  return (
    <div className="flex flex-col gap-1">
      <StatusBadge tone={tone} className="w-fit">
        {title}: {issues.length}
      </StatusBadge>
      <ul className="flex flex-col gap-0.5">
        {issues.map((issue) => (
          <li key={issue.key ?? issue.title} className="text-body-sm text-text-primary">
            {issue.title}
          </li>
        ))}
      </ul>
    </div>
  );
}
