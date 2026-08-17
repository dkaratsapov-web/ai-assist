"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import type {
  ApiError,
  ComparisonRead,
  CompetitorRead,
  FeatureRowRead,
  OfferRowRead,
  ProjectRead,
} from "@ads-os/schemas";
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Input,
  Modal,
  ModuleStatusBadge,
  ProjectSwitcher,
  Skeleton,
  StatusBadge,
} from "@ads-os/ui";
import { IconUsers } from "@ads-os/ui/icons";
import { AppShell } from "@/components/AppShell";
import { createApiClient } from "@/lib/api";
import { toApiError } from "@/lib/errors";

/** Как часто перечитывать, пока хоть один конкурент разбирается. */
const POLL_INTERVAL_MS = 3000;

export default function CompetitorsPage() {
  return (
    <Suspense
      fallback={
        <AppShell title="Конкуренты">
          <Skeleton shape="card" />
        </AppShell>
      }
    >
      <CompetitorsScreen />
    </Suspense>
  );
}

function CompetitorsScreen() {
  const api = useMemo(() => createApiClient(), []);
  const requestedProject = useSearchParams().get("project");

  const [projects, setProjects] = useState<ProjectRead[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [competitors, setCompetitors] = useState<CompetitorRead[] | null>(null);
  const [comparison, setComparison] = useState<ComparisonRead | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState({ url: "", title: "" });

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

  const projectRef = useRef<string | null>(null);
  useEffect(() => {
    if (!selectedId) return;
    let ignore = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    if (projectRef.current !== selectedId) {
      projectRef.current = selectedId;
      setCompetitors(null);
      setComparison(null);
    }

    const poll = async () => {
      try {
        // Список и сравнение читаются вместе: сравнение без списка непонятно,
        // а список без сравнения — просто набор ссылок.
        const [list, result] = await Promise.all([
          api.listCompetitors(selectedId),
          api.getComparison(selectedId),
        ]);
        if (ignore) return;
        setError(null);
        setCompetitors(list.items);
        setComparison(result);

        const pending = list.items.some((c) => c.status === "queued" || c.status === "running");
        if (pending) timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
      } catch (err) {
        if (ignore) return;
        setError(toApiError(err));
      }
    };

    void poll();

    return () => {
      ignore = true;
      if (timer) clearTimeout(timer);
    };
  }, [api, selectedId, reloadToken]);

  const reload = useCallback(() => setReloadToken((token) => token + 1), []);

  const add = async () => {
    if (!selectedId) return;
    setSaving(true);
    try {
      await api.addCompetitor(selectedId, {
        url: draft.url.trim(),
        title: draft.title.trim() || null,
      });
      setAdding(false);
      setDraft({ url: "", title: "" });
      reload();
    } catch (err) {
      setError(toApiError(err));
      setAdding(false);
    } finally {
      setSaving(false);
    }
  };

  const remove = async (competitorId: string) => {
    if (!selectedId) return;
    try {
      await api.deleteCompetitor(selectedId, competitorId);
      reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

  const recheck = async (competitorId: string) => {
    if (!selectedId) return;
    try {
      await api.recheckCompetitor(selectedId, competitorId);
      reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

  const gaps = (comparison?.rows ?? []).filter((row) => row.is_gap);

  return (
    <AppShell
      title="Конкуренты"
      subtitle="Чего нет у вас из того, что есть у них"
      actions={
        selectedId ? (
          <Button size="sm" onClick={() => setAdding(true)}>
            Добавить
          </Button>
        ) : undefined
      }
    >
      {error ? (
        <Card>
          <ErrorState
            title="Не удалось загрузить данные"
            description={error.message}
            requestId={error.requestId}
            onRetry={reload}
          />
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

          {competitors === null ? (
            <Card>
              <Skeleton shape="card" />
            </Card>
          ) : competitors.length === 0 ? (
            <Card>
              <EmptyState
                icon={<IconUsers size={24} />}
                title="Конкуренты не добавлены"
                description="Добавьте два-три сайта, с которыми вы реально конкурируете за клиента. Система разберёт их страницы и покажет, чего не хватает у вас."
                actionLabel="Добавить конкурента"
                onAction={() => setAdding(true)}
              />
            </Card>
          ) : (
            <>
              {comparison?.summary && (
                <Card className={gaps.length > 0 ? "border-warning-border bg-warning-bg" : ""}>
                  <p className="text-body text-text-primary">{comparison.summary}</p>
                </Card>
              )}

              {comparison && !comparison.own_site_checked && (
                // Без проверки своего сайта колонка «у вас» была бы сплошным
                // «нет» — и читалась бы как приговор, хотя мы просто не смотрели.
                <Card>
                  <p className="text-body-sm text-text-secondary">
                    Ваш сайт ещё не проверяли, поэтому колонка «у вас» пустая. Запустите проверку на
                    экране «Аудит сайта» — тогда сравнение станет полным.
                  </p>
                </Card>
              )}

              {/* Предметное сравнение идёт первым. К конкуренту приходят
                  смотреть, чем он берёт — цену, срок, гарантию, — а не
                  выяснять, есть ли у него телефон. Таблица признаков ниже
                  остаётся: она отвечает на другой вопрос, о технической
                  готовности страницы. */}
              {comparison?.offer_has_data && (
                <Card>
                  <CardHeader
                    title="Чем берут конкуренты"
                    description="Условия дословно с их страниц — можно открыть и проверить"
                  />
                  <div className="flex flex-col">
                    {comparison.offer_rows
                      .filter((row) => row.mine || row.rivals.some((rival) => rival.value))
                      .map((row) => (
                        <OfferRow key={row.key} row={row} />
                      ))}
                  </div>
                </Card>
              )}

              <Card>
                <CardHeader
                  title="Готовность страниц"
                  description={`Проверено конкурентов: ${comparison?.rivals_checked ?? 0}`}
                />
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[520px] border-collapse">
                    <thead>
                      <tr className="border-border border-b">
                        <th className="text-caption text-text-secondary py-2 text-left font-medium">
                          Что смотрим
                        </th>
                        <th className="text-caption text-text-secondary w-24 py-2 text-center font-medium">
                          У вас
                        </th>
                        <th className="text-caption text-text-secondary w-32 py-2 text-center font-medium">
                          У конкурентов
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {(comparison?.rows ?? []).map((row) => (
                        <ComparisonRow key={row.key} row={row} />
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            </>
          )}

          {competitors !== null && competitors.length > 0 && (
            <Card>
              <CardHeader title="Список" />
              <div className="flex flex-col">
                {competitors.map((competitor) => (
                  <CompetitorRow
                    key={competitor.id}
                    competitor={competitor}
                    onRemove={() => void remove(competitor.id)}
                    onRecheck={() => void recheck(competitor.id)}
                  />
                ))}
              </div>
            </Card>
          )}
        </>
      )}

      <Modal
        open={adding}
        onClose={() => setAdding(false)}
        title="Добавить конкурента"
        description="Адрес той страницы, куда конкурент ведёт рекламу, а не главной вообще."
        footer={
          <>
            <Button variant="secondary" onClick={() => setAdding(false)}>
              Отмена
            </Button>
            <Button onClick={add} loading={saving} disabled={draft.url.trim() === ""}>
              Добавить
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Input
            label="Адрес сайта"
            value={draft.url}
            onChange={(e) => setDraft((d) => ({ ...d, url: e.target.value }))}
            placeholder="https://rival.ru/remont"
          />
          <Input
            label="Название"
            value={draft.title}
            onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))}
            hint="Не обязательно: если не заполнить, возьмётся заголовок страницы"
          />
        </div>
      </Modal>
    </AppShell>
  );
}

/**
 * Одно условие предложения: наше, их и вывод.
 *
 * Цитаты показываются дословно и с адресом конкурента. В этом весь смысл:
 * пересказ чужого предложения своими словами превращает факт в мнение, а так
 * специалист открывает сайт и находит ту же строку глазами за десять секунд.
 */
function OfferRow({ row }: { row: OfferRowRead }) {
  return (
    <div className="border-border border-b py-3 last:border-b-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-body-sm text-text-primary font-medium">{row.label}</span>
        {row.is_gap && <StatusBadge tone="warning">Смотреть в первую очередь</StatusBadge>}
      </div>

      <div className="mt-1.5 flex flex-col gap-1">
        <div className="flex flex-wrap gap-x-2">
          <span className="text-caption text-text-secondary w-28 shrink-0">У вас</span>
          <span className="text-body-sm text-text-primary min-w-0 flex-1">
            {row.mine || <span className="text-text-secondary">не указано</span>}
          </span>
        </div>

        {row.rivals
          .filter((rival) => rival.value)
          .map((rival) => (
            <div key={rival.url} className="flex flex-wrap gap-x-2">
              <a
                href={rival.url}
                target="_blank"
                rel="noreferrer noopener"
                className="text-caption text-info focus-visible:outline-focus w-28 shrink-0 truncate focus-visible:outline-2"
                title={rival.url}
              >
                {rival.title}
              </a>
              <span className="text-body-sm text-text-secondary min-w-0 flex-1">{rival.value}</span>
            </div>
          ))}
      </div>

      {row.verdict && <p className="text-body-sm text-text-primary mt-2">{row.verdict}</p>}
    </div>
  );
}

function ComparisonRow({ row }: { row: FeatureRowRead }) {
  return (
    <tr className="border-border border-b last:border-b-0">
      <td className="py-2.5 pr-3">
        <span className="text-body-sm text-text-primary block">{row.label}</span>
        <span className="text-caption text-text-secondary block">{row.why}</span>
      </td>
      <td className="py-2.5 text-center">
        {/* Кружок сопровождается словом: только цвет не читается при слабом
            цветовосприятии (v0.3 §139). */}
        <Mark present={row.mine} />
      </td>
      <td className="py-2.5 text-center">
        <span className="text-body-sm text-text-primary tabular-nums">
          {row.rivals_with} из {row.rivals_total}
        </span>
        {row.is_gap && (
          <StatusBadge tone="warning" className="mx-auto mt-1 block w-fit">
            Пробел
          </StatusBadge>
        )}
        {row.is_advantage && (
          <StatusBadge tone="success" className="mx-auto mt-1 block w-fit">
            Ваш плюс
          </StatusBadge>
        )}
      </td>
    </tr>
  );
}

function Mark({ present }: { present: boolean }) {
  return (
    <span className={present ? "text-body-sm text-success" : "text-body-sm text-text-secondary"}>
      {present ? "есть" : "нет"}
    </span>
  );
}

function CompetitorRow({
  competitor,
  onRemove,
  onRecheck,
}: {
  competitor: CompetitorRead;
  onRemove: () => void;
  onRecheck: () => void;
}) {
  return (
    <div className="border-border flex flex-wrap items-center justify-between gap-3 border-b py-3 last:border-b-0">
      <div className="flex min-w-0 flex-col">
        <span className="text-body-sm text-text-primary">{competitor.title ?? competitor.url}</span>
        <span className="text-caption text-text-secondary break-all">{competitor.url}</span>
        {competitor.error_reason && (
          <span className="text-caption text-critical">{competitor.error_reason}</span>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <ModuleStatusBadge status={competitor.status} />
        <Button size="sm" variant="ghost" onClick={onRecheck}>
          Перепроверить
        </Button>
        <Button size="sm" variant="ghost" onClick={onRemove}>
          Удалить
        </Button>
      </div>
    </div>
  );
}
