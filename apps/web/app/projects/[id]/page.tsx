"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  type ApiError,
  type NicheRead,
  type ProgressRead,
  type ProjectAccessRead,
  type ProjectRead,
  type StepRead,
} from "@ads-os/schemas";
import {
  Button,
  Card,
  CardHeader,
  ConfirmationDialog,
  ErrorState,
  Input,
  Modal,
  ProjectStatusBadge,
  Skeleton,
  StatusBadge,
  WorkflowStepper,
} from "@ads-os/ui";
import { IconChart, IconGlobe, IconTarget, IconUsers } from "@ads-os/ui/icons";
import { AppShell } from "@/components/AppShell";
import { createApiClient } from "@/lib/api";
import { toApiError } from "@/lib/errors";

/** Куда ведёт шаг. Шаги без готового экрана здесь не перечислены — и не
 *  притворяются ссылками. */
const STEP_LINKS = {
  research: (id: string) => `/site-audit?project=${id}`,
  competitors: (id: string) => `/competitors?project=${id}`,
  economics: (id: string) => `/economics?project=${id}`,
  strategy: (id: string) => `/strategy?project=${id}`,
} as const;

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const api = useMemo(() => createApiClient(), []);

  const [project, setProject] = useState<ProjectRead | null>(null);
  const [progress, setProgress] = useState<ProgressRead | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const [niches, setNiches] = useState<NicheRead[]>([]);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState({ name: "", website: "", region: "", niche: "" });
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const router = useRouter();

  // Ниша могла быть удалена из справочника с тех пор, как её выбрали. Тогда
  // карточки просто нет — это лучше, чем пустой блок с заголовком.
  const activeNiche = niches.find((n) => n.key === project?.niche) ?? null;

  useEffect(() => {
    let ignore = false;

    void (async () => {
      try {
        // Оба запроса идут вместе: прогресс без проекта показывать нечему, а
        // проект без прогресса — половина экрана.
        const [loadedProject, loadedProgress, loadedNiches] = await Promise.all([
          api.getProject(id),
          api.getProgress(id),
          api.listNiches(),
        ]);
        if (ignore) return;
        setError(null);
        setProject(loadedProject);
        setProgress(loadedProgress);
        setNiches(loadedNiches.items);
      } catch (err) {
        if (ignore) return;
        setError(toApiError(err));
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, id, reloadToken]);

  const openEditor = () => {
    if (!project) return;
    setDraft({
      name: project.name,
      website: project.website_url ?? "",
      region: project.primary_region ?? "",
      niche: project.niche ?? "",
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
        niche: draft.niche || null,
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

  const remove = async () => {
    if (!project) return;
    setDeleting(true);
    try {
      await api.deleteProject(project.id);
      // Возврат к списку: оставаться на странице удалённого проекта незачем,
      // а следующий же запрос вернул бы 404 и экран ошибки.
      router.push("/projects");
    } catch (err) {
      setError(toApiError(err));
      setConfirmDelete(false);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <AppShell
      title={project?.name ?? "Проект"}
      subtitle={project?.website_url ?? undefined}
      actions={
        project ? (
          <span className="flex items-center gap-2">
            {/* Отчёт открывается в новой вкладке: это отдельная страница под
                печать, и возвращаться из неё «назад» к проекту неудобно. */}
            <Button
              size="sm"
              variant="secondary"
              onClick={() => window.open(`/projects/${project.id}/report`, "_blank")}
            >
              Отчёт
            </Button>
            <Button size="sm" variant="secondary" onClick={openEditor}>
              Изменить
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(true)}>
              Удалить
            </Button>
          </span>
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

          {activeNiche ? <NicheCard niche={activeNiche} /> : null}

          <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
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
            <StepLink
              href={STEP_LINKS.strategy(project.id)}
              icon={<IconTarget size={18} />}
              title="Стратегия запуска"
              description="С какой стратегии ставок начинать и сколько ждать первых выводов"
            />
          </section>

          <AccessCard projectId={project.id} />

          <p className="text-caption text-text-secondary">
            Пока открыты исследование, экономика и план запуска. Остальные шаги видны в цепочке,
            чтобы был понятен весь путь, и станут доступны по мере готовности.
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
          <label className="flex flex-col gap-1.5">
            <span className="text-caption text-text-secondary">Ниша</span>
            <select
              value={draft.niche}
              onChange={(e) => setDraft((d) => ({ ...d, niche: e.target.value }))}
              className="border-border-input rounded-control text-body-sm text-text-primary bg-bg focus-visible:outline-focus h-10 border px-3 focus-visible:outline-2"
            >
              <option value="">Не выбрана</option>
              {niches.map((niche) => (
                <option key={niche.key} value={niche.key}>
                  {niche.label}
                </option>
              ))}
            </select>
            <span className="text-caption text-text-secondary">
              Добавляет стартовые минус-слова и проверку требований Директа к этой нише
            </span>
          </label>
        </div>
      </Modal>
      <ConfirmationDialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => void remove()}
        title="Удалить проект"
        description="Проект и его результаты перестанут отображаться. Данные не стираются сразу — восстановить проект можно обращением в поддержку."
        confirmLabel={deleting ? "Удаляем…" : "Удалить"}
        destructive
      />
    </AppShell>
  );
}

/**
 * Кому открыт этот проект.
 *
 * Одно поле — почта. Учётную запись заводить не надо: она создаётся сама, а
 * личность подтвердит Яндекс при первом входе. Отдельного экрана «участники»
 * для этого не заводится намеренно: доступ выдают, глядя на проект, а не на
 * список людей, и решение «пусть Иван посмотрит вот это» принимается здесь.
 *
 * Карточка молчит, когда доступов нет и добавить их некому: специалисту она
 * покажет пустой список, который он не может изменить, — а это и есть тот
 * самый интерфейс с кнопками, которые ничего не делают.
 */
function AccessCard({ projectId }: { projectId: string }) {
  const api = useMemo(() => createApiClient(), []);
  const [people, setPeople] = useState<ProjectAccessRead[] | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"viewer" | "specialist">("viewer");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);

  const [reloadToken, setReloadToken] = useState(0);
  const reload = () => setReloadToken((token) => token + 1);

  useEffect(() => {
    let ignore = false;

    void (async () => {
      try {
        const list = await api.listProjectAccess(projectId);
        if (!ignore) setPeople(list.items);
      } catch {
        // Список доступов — не главное на этой странице. Не загрузился —
        // карточки просто нет, и проект остаётся рабочим.
        if (!ignore) setPeople([]);
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, projectId, reloadToken]);

  const grant = async () => {
    const value = email.trim();
    if (!value) return;
    setBusy(true);
    setFailure(null);
    try {
      await api.grantProjectAccess(projectId, { email: value, role });
      setEmail("");
      reload();
    } catch (err) {
      const failed = toApiError(err);
      // Отказ по роли — это не ошибка ввода: специалисту просто нечего здесь
      // делать, и правильнее убрать форму, чем оставить её с красной надписью.
      if (failed.status === 403) setForbidden(true);
      else setFailure(failed.message);
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (userId: string) => {
    try {
      await api.revokeProjectAccess(projectId, userId);
      reload();
    } catch (err) {
      setFailure(toApiError(err).message);
    }
  };

  if (people === null) return null;
  if (forbidden && people.length === 0) return null;

  return (
    <Card>
      <CardHeader
        title="Доступ к проекту"
        description="Впишите почту — человек увидит этот проект и ни один другой"
      />

      <div className="flex flex-col gap-4">
        {people.length > 0 && (
          <div className="flex flex-col">
            {people.map((person) => (
              <div
                key={person.user_id}
                className="border-border flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-b-0"
              >
                <div className="flex min-w-0 flex-col">
                  <span className="text-body-sm text-text-primary">{person.email}</span>
                  <span className="text-caption text-text-secondary">
                    {person.role === "viewer" ? "Только просмотр" : "Может менять"}
                    {" · "}
                    {/* Отметка входа отвечает на вопрос «дошло ли приглашение».
                        Без неё владелец не знает, ждать ему или писать человеку. */}
                    {person.last_login_at
                      ? `заходил ${new Date(person.last_login_at).toLocaleDateString("ru-RU")}`
                      : "ещё не заходил"}
                  </span>
                </div>
                {!forbidden && (
                  <Button size="sm" variant="ghost" onClick={() => void revoke(person.user_id)}>
                    Закрыть доступ
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}

        {!forbidden && (
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-56 flex-1">
              <Input
                label="Почта"
                placeholder="ivan@yandex.ru"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void grant();
                }}
              />
            </div>
            <Button
              variant="secondary"
              onClick={() => setRole(role === "viewer" ? "specialist" : "viewer")}
            >
              {role === "viewer" ? "Только просмотр" : "Может менять"}
            </Button>
            <Button onClick={() => void grant()} loading={busy} disabled={email.trim() === ""}>
              Открыть доступ
            </Button>
          </div>
        )}

        {failure && <p className="text-body-sm text-critical">{failure}</p>}

        <p className="text-caption text-text-secondary">
          Пароль не нужен: человек войдёт своим аккаунтом Яндекса. Подойдёт любое написание адреса —
          ya.ru и yandex.ru, с точкой или дефисом в логине: это один и тот же ящик.
        </p>
      </div>
    </Card>
  );
}

function describe(progress: ProgressRead, key: string): string {
  const step: StepRead | undefined = progress.steps.find((s) => s.key === key);
  if (!step) return "";
  if (step.state === "completed") return "Готово";
  return step.hint ?? "";
}

/**
 * Что известно про нишу проекта.
 *
 * Требования площадки идут первыми и отдельно от заметок: без них объявления
 * не выходят на показы вообще, а заметка — это повод подумать. Мешать одно с
 * другим значит уравнивать «сайт не пройдёт модерацию» и «уточните у клиента».
 */
function NicheCard({ niche }: { niche: NicheRead }) {
  return (
    <Card>
      <CardHeader
        title={`Ниша: ${niche.label}`}
        description="Что в этой нише проверяется дополнительно"
      />
      <div className="flex flex-col gap-4">
        {niche.requirements.length > 0 ? (
          <div className="flex flex-col gap-2">
            <span className="text-caption text-text-secondary">Требования Яндекс Директа</span>
            {niche.requirements.map((requirement) => (
              <div key={requirement.key} className="flex items-start gap-2">
                <StatusBadge tone={requirement.blocking ? "critical" : "warning"} size="sm">
                  {requirement.blocking ? "Обязательно" : "Желательно"}
                </StatusBadge>
                <span className="text-body-sm text-text-primary">{requirement.title}</span>
              </div>
            ))}
            <span className="text-caption text-text-secondary">
              Проверяются при аудите сайта вместе с остальными.
            </span>
          </div>
        ) : null}

        {niche.notes.length > 0 ? (
          <ul className="flex flex-col gap-1.5">
            {niche.notes.map((note) => (
              <li key={note} className="text-body-sm text-text-secondary">
                {note}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Card>
  );
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
