"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { AdDraftRead, ApiError, ProjectRead } from "@ads-os/schemas";
import {
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  ProjectSwitcher,
  Skeleton,
  StatusBadge,
} from "@ads-os/ui";
import { IconMegaphone } from "@ads-os/ui/icons";
import { AppShell } from "@/components/AppShell";
import { createApiClient } from "@/lib/api";
import { toApiError } from "@/lib/errors";

/** Лимиты Директа. Здесь только для подсказки под полем — считает их backend. */
const LIMITS = { title: 56, title2: 30, text: 81 };

export default function AdsPage() {
  return (
    <Suspense
      fallback={
        <AppShell title="Объявления">
          <Skeleton shape="card" />
        </AppShell>
      }
    >
      <AdsScreen />
    </Suspense>
  );
}

function AdsScreen() {
  const api = useMemo(() => createApiClient(), []);
  const requestedProject = useSearchParams().get("project");

  const [projects, setProjects] = useState<ProjectRead[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<AdDraftRead[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [ready, setReady] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let ignore = false;
    void (async () => {
      try {
        const list = await api.listProjects();
        if (ignore) return;
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
        const list = await api.listAdDrafts(selectedId);
        if (ignore) return;
        setError(null);
        setDrafts(list.items);
        setNote(list.source_note ?? null);
        setReady(list.ready);
      } catch (err) {
        if (!ignore) setError(toApiError(err));
      }
    })();
    return () => {
      ignore = true;
    };
  }, [api, selectedId]);

  return (
    <AppShell
      title="Объявления"
      subtitle="Черновики по группам фраз — собраны из текста вашей посадочной страницы"
    >
      {error ? (
        <Card>
          <ErrorState title="Не удалось собрать черновики" description={error.message} />
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

          {note && (
            <Card className="border-warning-border bg-warning-bg">
              <p className="text-body-sm text-text-primary">{note}</p>
            </Card>
          )}

          {drafts === null ? (
            <Card>
              <Skeleton shape="card" />
            </Card>
          ) : drafts.length === 0 ? (
            <Card>
              <EmptyState
                icon={<IconMegaphone size={24} />}
                title="Групп фраз пока нет"
                description="Загрузите список фраз на экране «Семантика» — система разложит его по группам и соберёт по черновику на каждую."
              />
            </Card>
          ) : (
            <>
              <Card>
                <p className="text-body-sm text-text-secondary">
                  Черновиков: {drafts.length}, без замечаний: {ready}. Текст собран из фрагментов
                  вашей страницы — итоговый пишете вы, система проверяет лимиты и слова, из-за
                  которых приходит отказ.
                </p>
              </Card>

              {drafts.map((draft) => (
                <DraftCard key={draft.cluster} draft={draft} />
              ))}
            </>
          )}
        </>
      )}
    </AppShell>
  );
}

function DraftCard({ draft }: { draft: AdDraftRead }) {
  return (
    <Card className={draft.is_ready ? "" : "border-warning-border"}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <CardHeader title={draft.cluster} description={`Фраз в группе: ${draft.keywords.length}`} />
        <StatusBadge tone={draft.is_ready ? "success" : "warning"}>
          {draft.is_ready ? "Пройдёт модерацию" : "Есть замечания"}
        </StatusBadge>
      </div>

      {/* Объявление показано так, как его увидит человек в выдаче: иначе лимиты
          остаются абстракцией, а длина заголовка — просто числом. */}
      <div className="border-border bg-bg-secondary rounded-control mb-3 border p-3">
        <p className="text-body text-text-primary">
          {draft.title}
          {draft.title_2 && <span className="text-text-secondary"> — {draft.title_2}</span>}
        </p>
        {draft.display_path && (
          <p className="text-caption text-success">сайт.ру/{draft.display_path}</p>
        )}
        <p className="text-body-sm text-text-secondary mt-1">{draft.text || "текст не собран"}</p>
        {draft.callouts.length > 0 && (
          <p className="text-caption text-text-secondary mt-1">{draft.callouts.join(" · ")}</p>
        )}
      </div>

      <dl className="text-caption text-text-secondary mb-2 flex flex-wrap gap-x-4 gap-y-1">
        <Counter label="Заголовок" length={draft.title.length} limit={LIMITS.title} />
        <Counter
          label="Второй заголовок"
          length={draft.title_2?.length ?? 0}
          limit={LIMITS.title2}
        />
        <Counter label="Текст" length={draft.text.length} limit={LIMITS.text} />
      </dl>

      {draft.violations.length > 0 && (
        <ul className="flex flex-col gap-1">
          {draft.violations.map((violation, index) => (
            <li key={`${violation.problem}-${index}`} className="text-body-sm text-text-secondary">
              <span className="text-text-primary">{violation.field_name}:</span> {violation.message}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Counter({ label, length, limit }: { label: string; length: number; limit: number }) {
  return (
    <span className="flex items-baseline gap-1">
      <dt>{label}</dt>
      <dd className={length > limit ? "text-critical tabular-nums" : "tabular-nums"}>
        {length}/{limit}
      </dd>
    </span>
  );
}
