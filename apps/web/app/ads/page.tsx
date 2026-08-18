"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import type {
  AdDraftRead,
  ApiError,
  CampaignCheckRead,
  CampaignGroupRead,
  CampaignPreviewRead,
  ProjectRead,
  UtmNotesRead,
} from "@ads-os/schemas";
import {
  Card,
  CardHeader,
  Details,
  EmptyState,
  ErrorState,
  Hint,
  ProjectSwitcher,
  Skeleton,
  StatusBadge,
  plural,
} from "@ads-os/ui";
import type { Tone } from "@ads-os/tokens";
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
  const [utm, setUtm] = useState<UtmNotesRead | null>(null);
  const [ready, setReady] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);
  const [preview, setPreview] = useState<CampaignPreviewRead | null>(null);

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
        const [list, campaign] = await Promise.all([
          api.listAdDrafts(selectedId),
          api.previewCampaign(selectedId),
        ]);
        if (ignore) return;
        setPreview(campaign);
        setError(null);
        setDrafts(list.items);
        setNote(list.source_note ?? null);
        setUtm(list.utm);
        setReady(list.ready);
      } catch (err) {
        if (!ignore) setError(toApiError(err));
      }
    })();
    return () => {
      ignore = true;
    };
  }, [api, selectedId]);

  // Варианты приходят плоским списком, по несколько на группу. Собираем их
  // обратно: порядок сохраняется, поэтому группы идут так же, как пришли.
  const groups: { name: string; drafts: AdDraftRead[] }[] = [];
  for (const draft of drafts ?? []) {
    const last = groups[groups.length - 1];
    if (last && last.name === draft.cluster) {
      last.drafts.push(draft);
    } else {
      groups.push({ name: draft.cluster, drafts: [draft] });
    }
  }

  return (
    <AppShell
      title="Объявления"
      subtitle="Черновики по группам фраз — собраны из текста вашей посадочной страницы"
      actions={
        selectedId && drafts && drafts.length > 0 ? (
          // Обычная ссылка, а не запрос из скрипта: файл скачивает браузер, и
          // тянуть весь CSV в память вкладки ради того же результата незачем.
          <a
            href={api.campaignExportUrl(selectedId)}
            className="rounded-control bg-cta text-cta-text text-caption focus-visible:outline-focus inline-flex h-8 items-center px-3 font-medium focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            Выгрузить кампанию
          </a>
        ) : undefined
      }
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
                <p className="text-body-sm text-text-primary">
                  {groups.length} {plural(groups.length, "группа", "группы", "групп")}, в каждой по
                  несколько вариантов объявления. Без замечаний: {ready} из {drafts.length}.
                </p>
                <p className="text-caption text-text-secondary mt-1.5">
                  Варианты нужны для сравнения: с одним объявлением тестировать нечего. Текст собран
                  из фрагментов вашей страницы — итоговый пишете вы, система лишь проверяет лимиты и
                  слова, из-за которых приходит отказ. Кнопка сверху отдаёт всё это файлом для
                  Коммандера.
                </p>
              </Card>

              {preview && <BeforeCommanderCard preview={preview} />}

              {utm && <UtmCard utm={utm} />}

              {groups.map((group) => (
                <GroupCard key={group.name} name={group.name} drafts={group.drafts} />
              ))}
            </>
          )}
        </>
      )}
    </AppShell>
  );
}

/**
 * Разметка ссылок: пример и объяснение.
 *
 * Стоит рядом с черновиками, потому что именно эти ссылки уедут в кампанию.
 * Строка с фигурными скобками выглядит как ошибка вёрстки, и первый вопрос
 * человека — что это такое; показать рядом готовый пример дешевле, чем потом
 * объяснять, почему в отчёте оказалось «%7Bkeyword%7D».
 */
function UtmCard({ utm }: { utm: UtmNotesRead }) {
  return (
    <Card>
      <CardHeader
        title="Разметка ссылок"
        description="Проставляется сама — по ней в Метрике видно, какая группа и фраза принесли заявку"
      />
      <code className="text-caption text-text-secondary mb-2 block break-all">{utm.example}</code>
      <ul className="flex flex-col gap-1">
        {utm.notes.map((text, index) => (
          <li key={index} className="text-caption text-text-secondary">
            {text}
          </li>
        ))}
      </ul>
    </Card>
  );
}

/**
 * Все варианты одной группы под одним заголовком.
 *
 * Раньше каждый вариант был отдельной карточкой со своим заголовком группы и
 * числом фраз. При трёх вариантах на группу экран превращался в ленту, где
 * подряд идут три карточки «купить айфон · фраз в группе: 81» — и выглядело
 * это как три одинаковые группы, а не как три объявления одной. Первое, что
 * спрашивали, увидев экран: «почему всё повторяется».
 */
function GroupCard({ name, drafts }: { name: string; drafts: AdDraftRead[] }) {
  const phrases = drafts[0]?.keywords.length ?? 0;
  const clean = drafts.filter((d) => d.is_ready).length;

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <CardHeader
          title={name}
          description={`${phrases} ${plural(phrases, "фраза", "фразы", "фраз")} · ${drafts.length} ${plural(drafts.length, "вариант", "варианта", "вариантов")}`}
        />
        <StatusBadge tone={clean > 0 ? "success" : "warning"}>
          {clean > 0
            ? `${clean} ${plural(clean, "вариант готов", "варианта готовы", "вариантов готовы")}`
            : "все с замечаниями"}
        </StatusBadge>
      </div>

      <div className="flex flex-col gap-3">
        {drafts.map((draft, index) => (
          <DraftBlock key={index} draft={draft} number={index + 1} />
        ))}
      </div>
    </Card>
  );
}

function DraftBlock({ draft, number }: { draft: AdDraftRead; number: number }) {
  return (
    <div className="border-border rounded-control border p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-caption text-text-secondary">Вариант {number}</span>
        {!draft.is_ready && (
          <StatusBadge tone="warning" size="sm">
            не пройдёт
          </StatusBadge>
        )}
      </div>

      {/* Объявление показано так, как его увидит человек в выдаче: иначе лимиты
          остаются абстракцией, а длина заголовка — просто числом. */}
      <div className="border-border bg-bg-secondary rounded-control mb-3 border p-3">
        <p className="text-body text-text-primary">
          {draft.title}
          {draft.title_2 && <span className="text-text-secondary"> — {draft.title_2}</span>}
        </p>
        {/* Настоящий адрес посадочной показывается рядом с отображаемой
            ссылкой: разные группы теперь ведут на разные страницы, и это надо
            видеть до выгрузки, а не после запуска. */}
        <p className="text-caption text-success break-all">
          {draft.landing_url}
          {draft.display_path && (
            <span className="text-text-secondary"> · {draft.display_path}</span>
          )}
        </p>
        <p className="text-body-sm text-text-secondary mt-1">{draft.text || "текст не собран"}</p>
        {draft.callouts.length > 0 && (
          <p className="text-caption text-text-secondary mt-1">{draft.callouts.join(" · ")}</p>
        )}
        {draft.sitelinks.length > 0 && (
          <p className="text-caption text-info mt-1">
            {draft.sitelinks.map((link) => link.title).join(" · ")}
          </p>
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
    </div>
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

const CHECK_TONE: Record<string, Tone> = {
  blocking: "critical",
  warning: "warning",
  note: "neutral",
};

const CHECK_LABEL: Record<string, string> = {
  blocking: "мешает",
  warning: "стоит поправить",
  note: "к сведению",
};

/**
 * Что уедет в Коммандер.
 *
 * Последний экран перед тем, как работа покидает систему. До него человек
 * видел объявления, фразы и группы по отдельности, а собранную кампанию —
 * только в самом файле, то есть уже после выгрузки. Ошибку в структуре
 * замечали в Директе, где правка стоит дороже всего.
 *
 * Замечания стоят выше содержимого намеренно: они и есть причина, по которой
 * этот экран существует. Ни одно из них выгрузку не запрещает — специалист
 * может знать про свой случай больше, чем проверка, а запрет, который нельзя
 * обойти, приводит к тому, что работу доделывают мимо системы.
 */
function BeforeCommanderCard({ preview }: { preview: CampaignPreviewRead }) {
  const checks = preview.checks ?? [];
  const blocking = checks.filter((check) => check.severity === "blocking");

  return (
    <Card>
      <CardHeader
        title="Что уедет в Коммандер"
        description="Посмотрите здесь: в Директе правка обойдётся дороже"
        action={
          <span className="text-caption text-text-secondary tabular-nums">
            {preview.groups.length} групп · {preview.total_phrases} фраз · {preview.total_frequency}{" "}
            показов
          </span>
        }
      />

      <div className="flex flex-col gap-4">
        {checks.length > 0 ? (
          <div className="flex flex-col">
            {checks.map((check) => (
              <CheckRow key={check.key} check={check} />
            ))}
          </div>
        ) : (
          <p className="text-body-sm text-text-primary">
            Замечаний нет: структура собрана, фразы разложены, минус-слова на месте.
          </p>
        )}

        {blocking.length > 0 && (
          <Hint>
            Выгрузить можно и сейчас — кнопка сверху работает. Но то, что помечено как «мешает»,
            почти наверняка придётся править уже в Директе.
          </Hint>
        )}

        <Details summary={`Показать структуру целиком (${preview.groups.length})`}>
          <div className="flex flex-col">
            {preview.groups.map((group) => (
              <CampaignGroupRow key={group.name} group={group} />
            ))}
          </div>
        </Details>

        {(preview.ungrouped ?? []).length > 0 && (
          <Details summary={`Не уедет — фраз без группы: ${(preview.ungrouped ?? []).length}`}>
            <div className="flex flex-wrap gap-1.5">
              {(preview.ungrouped ?? []).slice(0, 50).map((phrase) => (
                <span
                  key={phrase}
                  className="border-border bg-bg-secondary text-caption text-text-secondary rounded-pill border px-2 py-0.5"
                >
                  {phrase}
                </span>
              ))}
            </div>
          </Details>
        )}
      </div>
    </Card>
  );
}

function CheckRow({ check }: { check: CampaignCheckRead }) {
  return (
    <div className="border-border-subtle flex flex-col gap-1 border-b py-2.5 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone={CHECK_TONE[check.severity] ?? "neutral"} size="sm" dot>
          {CHECK_LABEL[check.severity] ?? check.severity}
        </StatusBadge>
        <span className="text-body-sm text-text-primary font-medium">{check.title}</span>
      </div>
      <p className="text-caption text-text-secondary max-w-(--layout-measure)">{check.action}</p>
      {/* Примеры обязательны: без них человек не понимает, где искать, и
          замечание остаётся непрочитанным. */}
      {(check.examples ?? []).length > 0 && (
        <p className="text-caption text-text-secondary">
          Например: {(check.examples ?? []).join(" · ")}
          {check.count > (check.examples ?? []).length &&
            ` и ещё ${check.count - (check.examples ?? []).length}`}
        </p>
      )}
    </div>
  );
}

function CampaignGroupRow({ group }: { group: CampaignGroupRead }) {
  return (
    <div className="border-border-subtle flex flex-col gap-1 border-b py-2 last:border-b-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-body-sm text-text-primary font-medium">{group.name}</span>
        <span className="text-caption text-text-secondary tabular-nums">
          {group.phrases.length} фраз · {group.total_frequency}
        </span>
      </div>
      {/* Заголовок объявления рядом с фразами — единственный способ увидеть,
          совпадают ли они. Ради этого совпадения группы и собирают. */}
      {(group.titles ?? []).length > 0 && (
        <span className="text-caption text-text-secondary">
          Объявление: {(group.titles ?? [])[0]}
        </span>
      )}
      <span className="text-caption text-text-secondary clamp-2 break-all">
        {group.phrases.join(" · ")}
      </span>
    </div>
  );
}
