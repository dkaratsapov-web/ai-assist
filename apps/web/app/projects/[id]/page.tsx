"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { type ApiError, type ProgressRead, type ProjectRead, type StepRead } from "@ads-os/schemas";
import {
  Button,
  Card,
  CardHeader,
  ErrorState,
  Input,
  Modal,
  ProjectStatusBadge,
  Skeleton,
  StatusBadge,
  WorkflowStepper,
} from "@ads-os/ui";
import { IconChart, IconGlobe, IconUsers } from "@ads-os/ui/icons";
import { AppShell } from "@/components/AppShell";
import { createApiClient, isApiConfigured } from "@/lib/api";
import { toApiError } from "@/lib/errors";

/** Куда ведёт шаг. Шаги без готового экрана здесь не перечислены — и не
 *  притворяются ссылками. */
const STEP_LINKS = {
  research: (id: string) => `/site-audit?project=${id}`,
  competitors: (id: string) => `/competitors?project=${id}`,
  economics: (id: string) => `/economics?project=${id}`,
} as const;

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const api = useMemo(() => createApiClient(), []);
  const configured = isApiConfigured();

  const [project, setProject] = useState<ProjectRead | null>(null);
  const [progress, setProgress] = useState<ProgressRead | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState({ name: "", website: "", region: "" });

  useEffect(() => {
    if (!configured) return;
    let ignore = false;

    void (async () => {
      try {
        // Оба запроса идут вместе: прогресс без проекта показывать нечему, а
        // проект без прогресса — половина экрана.
        const [loadedProject, loadedProgress] = await Promise.all([
          api.getProject(id),
          api.getProgress(id),
        ]);
        if (ignore) return;
        setError(null);
        setProject(loadedProject);
        setProgress(loadedProgress);
      } catch (err) {
        if (ignore) return;
        setError(toApiError(err));
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, configured, id, reloadToken]);

  const openEditor = () => {
    if (!project) return;
    setDraft({
      name: project.name,
      website: project.website_url ?? "",
      region: project.primary_region ?? "",
    });
    setEditing(true);
  };

  const save = async () => {
    if (!project) return;
    setSaving(true);
    try {
      await api.updateProject(project.id, {
        name: draft.name.trim(),
        website_url: draft.website.trim() || null,
        primary_region: draft.region.trim() || null,
        // Версия, на которой правили: защищает от записи поверх чужого
        // изменения (v0.4 §100).
        expected_version: project.version,
      });
      setEditing(false);
      setReloadToken((token) => token + 1);
    } catch (err) {
      setError(toApiError(err));
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppShell
      title={project?.name ?? "Проект"}
      subtitle={project?.website_url ?? undefined}
      actions={
        project ? (
          <Button size="sm" variant="secondary" onClick={openEditor}>
            Изменить
          </Button>
        ) : undefined
      }
    >
      {error ? (
        <Card>
          <ErrorState
            title="Не удалось загрузить проект"
            description={error.message}
            requestId={error.requestId}
            onRetry={() => setReloadToken((token) => token + 1)}
          />
        </Card>
      ) : !project || !progress ? (
        <div className="flex flex-col gap-3">
          <Skeleton shape="card" />
          <Skeleton shape="card" />
        </div>
      ) : (
        <>
          <Card>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="flex flex-col gap-1">
                <p className="text-caption text-text-secondary">Сейчас нужно</p>
                {/* Одно предложение вместо списка задач: пока модулей мало,
                    список из десяти пунктов только прячет главное. */}
                <p className="text-body text-text-primary">
                  {progress.next_action ?? "Всё, что можно сделать сейчас, сделано"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <ProjectStatusBadge status={project.status} size="md" />
                <StatusBadge tone="neutral" size="md">
                  Шагов пройдено: {progress.completed_count} из {progress.total_count}
                </StatusBadge>
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Путь проекта"
              description="Десять шагов от заведения проекта до масштабирования"
            />
            <WorkflowStepper
              steps={progress.steps.map((step) => ({
                key: step.key,
                label: step.label,
                description: step.hint ?? undefined,
                state: step.state,
              }))}
            />
          </Card>

          <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StepLink
              href={STEP_LINKS.research(project.id)}
              icon={<IconGlobe size={18} />}
              title="Аудит сайта"
              description={describe(progress, "research")}
            />
            <StepLink
              href={STEP_LINKS.competitors(project.id)}
              icon={<IconUsers size={18} />}
              title="Конкуренты"
              description="Сравнение с сайтами, за клиента с которыми вы конкурируете"
            />
            <StepLink
              href={STEP_LINKS.economics(project.id)}
              icon={<IconChart size={18} />}
              title="Экономика"
              description={describe(progress, "economics")}
            />
          </section>

          <p className="text-caption text-text-secondary">
            Пока открыты исследование и экономика. Остальные шаги видны в цепочке, чтобы был понятен
            весь путь, и станут доступны по мере готовности.
          </p>
        </>
      )}

      <Modal
        open={editing}
        onClose={() => setEditing(false)}
        title="Изменить проект"
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditing(false)}>
              Отмена
            </Button>
            <Button onClick={save} loading={saving} disabled={draft.name.trim() === ""}>
              Сохранить
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Input
            label="Название"
            value={draft.name}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
          />
          <Input
            label="Адрес сайта"
            value={draft.website}
            onChange={(e) => setDraft((d) => ({ ...d, website: e.target.value }))}
            placeholder="https://example.ru"
            hint="Нужен для проверки готовности к рекламе"
          />
          <Input
            label="Основной регион"
            value={draft.region}
            onChange={(e) => setDraft((d) => ({ ...d, region: e.target.value }))}
          />
        </div>
      </Modal>
    </AppShell>
  );
}

function describe(progress: ProgressRead, key: string): string {
  const step: StepRead | undefined = progress.steps.find((s) => s.key === key);
  if (!step) return "";
  if (step.state === "completed") return "Готово";
  return step.hint ?? "";
}

function StepLink({
  href,
  icon,
  title,
  description,
}: {
  href: string;
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <Card>
      <Link
        href={href}
        className="focus-visible:outline-focus -m-1 flex items-start gap-3 rounded-lg p-1 focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        <span className="text-text-secondary mt-0.5">{icon}</span>
        <span className="flex flex-col gap-0.5">
          <span className="text-body text-text-primary font-medium">{title}</span>
          <span className="text-body-sm text-text-secondary">{description}</span>
        </span>
      </Link>
    </Card>
  );
}
