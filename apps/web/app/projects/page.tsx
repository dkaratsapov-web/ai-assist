"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ApiError, type ProjectRead } from "@ads-os/schemas";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  Modal,
  ProjectStatusBadge,
  Skeleton,
} from "@ads-os/ui";
import { IconFolder } from "@ads-os/ui/icons";
import { AppShell } from "@/components/AppShell";
import { createApiClient, isApiConfigured } from "@/lib/api";
import { toApiError } from "@/lib/errors";

export default function ProjectsPage() {
  const api = useMemo(() => createApiClient(), []);
  const configured = isApiConfigured();

  const [projects, setProjects] = useState<ProjectRead[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [region, setRegion] = useState("");

  useEffect(() => {
    if (!configured) return;
    let ignore = false;

    void (async () => {
      try {
        const list = await api.listProjects();
        if (ignore) return;
        setError(null);
        setProjects(list.items);
      } catch (err) {
        if (ignore) return;
        setError(toApiError(err));
        setProjects([]);
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, configured, reloadToken]);

  const create = async () => {
    setSaving(true);
    try {
      await api.createProject({
        name: name.trim(),
        // Пустая строка — это не «не указано». Пустые поля уходят как null,
        // иначе адрес сайта окажется пустой строкой и аудит попробует её открыть.
        website_url: website.trim() || null,
        primary_region: region.trim() || null,
      });
      setCreating(false);
      setName("");
      setWebsite("");
      setRegion("");
      setReloadToken((token) => token + 1);
    } catch (err) {
      setError(toApiError(err));
      setCreating(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppShell
      title="Проекты"
      subtitle="Каждый проект — отдельный рекламируемый бизнес"
      actions={
        configured ? (
          <Button size="sm" onClick={() => setCreating(true)}>
            Новый проект
          </Button>
        ) : undefined
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
            title="Не удалось загрузить проекты"
            description={error.message}
            requestId={error.requestId}
            onRetry={() => setReloadToken((token) => token + 1)}
          />
        </Card>
      ) : projects === null ? (
        <div className="flex flex-col gap-3">
          <Skeleton shape="card" />
          <Skeleton shape="card" />
        </div>
      ) : projects.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconFolder size={24} />}
            title="Проектов пока нет"
            description="Создайте первый проект: достаточно названия. Адрес сайта и регион можно добавить позже."
            actionLabel="Новый проект"
            onAction={() => setCreating(true)}
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {projects.map((project) => (
            <ProjectRow key={project.id} project={project} />
          ))}
        </div>
      )}

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="Новый проект"
        description="Обязательно только название. Остальное дозаполняется по ходу работы."
        footer={
          <>
            <Button variant="secondary" onClick={() => setCreating(false)}>
              Отмена
            </Button>
            <Button onClick={create} loading={saving} disabled={name.trim() === ""}>
              Создать
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Input
            label="Название"
            value={name}
            onChange={(e) => setName(e.target.value)}
            hint="Как вы называете этот бизнес между собой"
          />
          <Input
            label="Адрес сайта"
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
            placeholder="https://example.ru"
            hint="Нужен для проверки готовности к рекламе. Можно добавить позже"
          />
          <Input
            label="Основной регион"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            placeholder="Москва"
          />
        </div>
      </Modal>
    </AppShell>
  );
}

/**
 * Строка проекта в списке.
 *
 * Показывает только то, что система действительно знает. Расход, лиды и CPL
 * здесь намеренно не выводятся: рекламный кабинет ещё не подключён, и нули
 * читались бы как «реклама идёт, результата нет» (v0.3 §140).
 */
function ProjectRow({ project }: { project: ProjectRead }) {
  return (
    <Card>
      <Link
        href={`/projects/${project.id}`}
        className="focus-visible:outline-focus -m-1 flex flex-col gap-2 rounded-lg p-1 focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        <div className="flex items-start justify-between gap-3">
          <span className="text-body text-text-primary font-medium">{project.name}</span>
          <ProjectStatusBadge status={project.status} />
        </div>
        <p className="text-body-sm text-text-secondary break-all">
          {project.website_url ?? "Адрес сайта не указан"}
        </p>
        {project.primary_region && (
          <p className="text-caption text-text-secondary">{project.primary_region}</p>
        )}
      </Link>
    </Card>
  );
}
