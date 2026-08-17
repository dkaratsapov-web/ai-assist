"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import type {
  ApiError,
  ClusterRead,
  CrossMinusResultRead,
  ImportSummary,
  Intent,
  KeywordRead,
  MinusWordList,
  MinusWordSetRead,
  ProjectRead,
} from "@ads-os/schemas";
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  FilterBar,
  Input,
  Modal,
  ProjectSwitcher,
  Skeleton,
  StatusBadge,
} from "@ads-os/ui";
import type { Tone } from "@ads-os/tokens";
import { IconSearch } from "@ads-os/ui/icons";
import { AppShell } from "@/components/AppShell";
import { createApiClient } from "@/lib/api";
import { toApiError } from "@/lib/errors";

const INTENT_TONE: Record<string, Tone> = {
  commercial: "success",
  informational: "info",
  irrelevant: "critical",
};

export default function SemanticsPage() {
  return (
    <Suspense
      fallback={
        <AppShell title="Семантика">
          <Skeleton shape="card" />
        </AppShell>
      }
    >
      <SemanticsScreen />
    </Suspense>
  );
}

function SemanticsScreen() {
  const api = useMemo(() => createApiClient(), []);
  const requestedProject = useSearchParams().get("project");

  const [projects, setProjects] = useState<ProjectRead[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [keywords, setKeywords] = useState<KeywordRead[] | null>(null);
  const [clusters, setClusters] = useState<ClusterRead[]>([]);
  const [minus, setMinus] = useState<MinusWordList | null>(null);
  const [cross, setCross] = useState<CrossMinusResultRead | null>(null);
  const [sets, setSets] = useState<MinusWordSetRead[]>([]);
  const [savingSet, setSavingSet] = useState(false);
  const [setName, setSetName] = useState("");
  const [filter, setFilter] = useState<string>("all");
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const [importing, setImporting] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [summary, setSummary] = useState<ImportSummary | null>(null);

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
        const [list, groups, minusWords, savedSets, crossing] = await Promise.all([
          api.listKeywords(selectedId),
          api.listClusters(selectedId),
          api.listMinusWords(selectedId),
          api.listMinusWordSets(),
          api.getCrossMinus(selectedId),
        ]);
        if (ignore) return;
        setError(null);
        setKeywords(list.items);
        setClusters(groups.items);
        setMinus(minusWords);
        setSets(savedSets.items);
        setCross(crossing);
      } catch (err) {
        if (!ignore) setError(toApiError(err));
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, selectedId, reloadToken]);

  const reload = useCallback(() => setReloadToken((token) => token + 1), []);

  const runImport = async () => {
    if (!selectedId) return;
    setSaving(true);
    try {
      setSummary(await api.importKeywords(selectedId, draft));
      setImporting(false);
      setDraft("");
      reload();
    } catch (err) {
      setError(toApiError(err));
      setImporting(false);
    } finally {
      setSaving(false);
    }
  };

  const move = async (keywordId: string, intent: Intent) => {
    if (!selectedId) return;
    try {
      await api.updateKeyword(selectedId, keywordId, intent);
      reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

  const saveSet = async () => {
    if (!selectedId) return;
    try {
      await api.saveMinusWordSet(setName.trim(), selectedId);
      setSavingSet(false);
      setSetName("");
      reload();
    } catch (err) {
      setError(toApiError(err));
      setSavingSet(false);
    }
  };

  const applySet = async (setId: string) => {
    if (!selectedId) return;
    try {
      await api.applyMinusWordSet(selectedId, setId);
      reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

  const addMinus = async (word: string) => {
    if (!selectedId) return;
    try {
      await api.addMinusWord(selectedId, word);
      reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

  const removeMinus = async (id: string) => {
    if (!selectedId) return;
    try {
      await api.deleteMinusWord(selectedId, id);
      reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

  const counts = {
    all: keywords?.length ?? 0,
    commercial: (keywords ?? []).filter((k) => k.intent === "commercial").length,
    informational: (keywords ?? []).filter((k) => k.intent === "informational").length,
    irrelevant: (keywords ?? []).filter((k) => k.intent === "irrelevant").length,
  };

  const shown = (keywords ?? []).filter((k) => filter === "all" || k.intent === filter);

  return (
    <AppShell
      title="Семантика"
      subtitle="Разбор списка фраз, отсев нецелевых и группировка под объявления"
      actions={
        selectedId ? (
          <Button size="sm" onClick={() => setImporting(true)}>
            Загрузить список
          </Button>
        ) : undefined
      }
    >
      {error ? (
        <Card>
          <ErrorState title="Не удалось загрузить" description={error.message} onRetry={reload} />
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

          {summary && (
            <Card>
              <p className="text-body-sm text-text-primary">
                Разобрано: добавлено {summary.added}, обновлено {summary.updated}
                {summary.skipped > 0 && `, пропущено строк ${summary.skipped}`}. Целевых{" "}
                {summary.commercial}, информационных {summary.informational}, нецелевых{" "}
                {summary.irrelevant}. Групп: {summary.clusters}.
              </p>
            </Card>
          )}

          {keywords === null ? (
            <Card>
              <Skeleton shape="card" />
            </Card>
          ) : keywords.length === 0 ? (
            <Card>
              <EmptyState
                icon={<IconSearch size={24} />}
                title="Список фраз не загружен"
                description="Вставьте выгрузку из Вордстата или Key Collector — система отсеет нецелевые, соберёт минус-слова и разложит остальное по группам под объявления."
                actionLabel="Загрузить список"
                onAction={() => setImporting(true)}
              />
            </Card>
          ) : (
            <>
              {clusters.length > 0 && (
                <Card>
                  <CardHeader
                    title="Группы под объявления"
                    description="Фразы одной группы ведут на одну страницу и требуют одного объявления"
                  />
                  <div className="flex flex-col">
                    {clusters.map((group) => (
                      <div
                        key={group.name}
                        className="border-border flex flex-wrap items-baseline justify-between gap-2 border-b py-2.5 last:border-b-0"
                      >
                        <div className="flex min-w-0 flex-col">
                          <span className="text-body-sm text-text-primary">{group.name}</span>
                          {/* Ядро — это объяснение группировки. Без него человек
                              не может ни проверить её, ни поправить. */}
                          {group.core.length > 0 && (
                            <span className="text-caption text-text-secondary">
                              объединены по: {group.core.join(", ")}
                            </span>
                          )}
                        </div>
                        <span className="text-caption text-text-secondary shrink-0 tabular-nums">
                          фраз: {group.phrases} · частотность: {group.total_frequency}
                        </span>
                      </div>
                    ))}
                  </div>
                </Card>
              )}

              {cross && (cross.items.length > 0 || cross.duplicates.length > 0) && (
                <Card>
                  <CardHeader
                    title="Фразы конкурируют между собой"
                    description="Общая фраза перехватывает запросы уточнённой — в отчёте это выглядит нормально"
                  />

                  {cross.duplicates.length > 0 && (
                    <div className="mb-3 flex flex-col gap-1.5">
                      <p className="text-caption text-text-secondary">
                        Одинаковые для Директа — порядок слов он не различает
                      </p>
                      {cross.duplicates.map((group) => (
                        <p key={group.phrases[0]} className="text-body-sm text-text-primary">
                          {group.phrases.join(" = ")}
                        </p>
                      ))}
                    </div>
                  )}

                  {cross.items.length > 0 && (
                    <div className="flex flex-col">
                      {cross.items.slice(0, 20).map((item) => (
                        <div
                          key={item.phrase}
                          className="border-border flex flex-col gap-1 border-b py-2.5 last:border-b-0"
                        >
                          <span className="text-body-sm text-text-primary font-medium">
                            {item.phrase}
                          </span>
                          <span className="text-caption text-text-secondary">
                            Отминусовать: {item.minus_words.map((word) => `−${word}`).join(", ")}
                          </span>
                          {/* Показываем, чьи запросы перехватываются: без этого
                              совет нельзя проверить и непонятно, что сломается,
                              если ему последовать. */}
                          <span className="text-caption text-text-secondary">
                            Иначе заберёт запросы: {item.shadows.slice(0, 3).join(", ")}
                            {item.shadows.length > 3 && ` и ещё ${item.shadows.length - 3}`}
                          </span>
                        </div>
                      ))}
                      {cross.items.length > 20 && (
                        <p className="text-caption text-text-secondary pt-2">
                          Показаны первые 20 из {cross.items.length}. Остальные попадут в выгрузку —
                          там они проставлены к каждой фразе.
                        </p>
                      )}
                    </div>
                  )}
                </Card>
              )}

              {minus &&
                (minus.items.length > 0 ||
                  minus.suggestions.length > 0 ||
                  minus.learned.length > 0 ||
                  minus.from_niche.length > 0) && (
                  <Card>
                    <CardHeader
                      title="Минус-слова"
                      description="Готовый список для кампании: остаётся проверить и перенести"
                    />
                    {minus.items.length > 0 && (
                      <div className="mb-3 flex flex-wrap gap-2">
                        {minus.items.map((word) => (
                          <button
                            key={word.id}
                            type="button"
                            onClick={() => void removeMinus(word.id)}
                            className="rounded-pill bg-bg-secondary text-caption text-text-secondary hover:bg-surface-active focus-visible:outline-focus px-3 py-1.5 focus-visible:outline-2"
                            title="Убрать из списка"
                          >
                            −{word.word} ✕
                          </button>
                        ))}
                      </div>
                    )}
                    {(sets.length > 0 || minus.items.length > 0) && (
                      <div className="border-border mb-3 flex flex-wrap items-center gap-2 border-t pt-3">
                        {/* Набор — заготовка на будущие проекты. Применение
                          добавляет слова, а не заменяет: своё в проекте важнее. */}
                        <span className="text-caption text-text-secondary">Готовые наборы:</span>
                        {sets.map((item) => (
                          <Button
                            key={item.id}
                            size="sm"
                            variant="ghost"
                            onClick={() => void applySet(item.id)}
                          >
                            {item.name} ({item.words.length})
                          </Button>
                        ))}
                        {minus.items.length > 0 && (
                          <Button size="sm" variant="ghost" onClick={() => setSavingSet(true)}>
                            Сохранить свой
                          </Button>
                        )}
                      </div>
                    )}
                    {minus.from_niche.length > 0 && (
                      <div className="border-border mb-3 border-t pt-3">
                        <p className="text-caption text-text-secondary mb-1.5">
                          Стартовый набор — минусуют почти всегда
                        </p>
                        <div className="flex flex-wrap gap-2">
                          {minus.from_niche.map((word) => (
                            <Button
                              key={word}
                              size="sm"
                              variant="ghost"
                              onClick={() => void addMinus(word)}
                            >
                              + {word}
                            </Button>
                          ))}
                        </div>
                      </div>
                    )}
                    {minus.learned.length > 0 && (
                      <div className="border-border mb-3 border-t pt-3">
                        {/* Подсказка, а не автоматика: слово не добавляется само.
                          Тихо отсечённый трафик — это то, о чём человек не
                          просил и о чём не узнает. */}
                        <p className="text-caption text-text-secondary mb-1.5">
                          Вы относили это к нецелевым в других проектах
                        </p>
                        <div className="flex flex-wrap gap-2">
                          {minus.learned.map((word) => (
                            <Button
                              key={word}
                              size="sm"
                              variant="ghost"
                              onClick={() => void addMinus(word)}
                            >
                              + {word}
                            </Button>
                          ))}
                        </div>
                      </div>
                    )}
                    {minus.suggestions.length > 0 && (
                      <>
                        <p className="text-caption text-text-secondary mb-1">Предлагаются</p>
                        <div className="flex flex-col">
                          {minus.suggestions.map((item) => (
                            <div
                              key={item.word}
                              className="border-border flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-b-0"
                            >
                              <div className="flex min-w-0 flex-col">
                                <span className="text-body-sm text-text-primary">{item.word}</span>
                                {/* Пример нужен, чтобы видеть, не выбросит ли
                                  минус-слово что-то нужное. */}
                                <span className="text-caption text-text-secondary">
                                  уводит фраз: {item.phrases} · например: {item.examples[0]}
                                </span>
                              </div>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => void addMinus(item.word)}
                              >
                                Добавить
                              </Button>
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                  </Card>
                )}

              <FilterBar
                label="Фильтр фраз"
                value={filter}
                onChange={setFilter}
                options={[
                  { value: "all", label: "Все", count: counts.all },
                  { value: "commercial", label: "Целевые", count: counts.commercial },
                  {
                    value: "informational",
                    label: "Информационные",
                    count: counts.informational,
                  },
                  { value: "irrelevant", label: "Нецелевые", count: counts.irrelevant },
                ]}
              />

              <Card>
                <div className="flex flex-col">
                  {shown.map((keyword) => (
                    <KeywordRow key={keyword.id} keyword={keyword} onMove={move} />
                  ))}
                </div>
              </Card>
            </>
          )}
        </>
      )}

      <Modal
        open={savingSet}
        onClose={() => setSavingSet(false)}
        title="Сохранить набор минус-слов"
        description="Набор общий для всех проектов. В следующем проекте той же ниши его останется применить одним нажатием."
        footer={
          <>
            <Button variant="secondary" onClick={() => setSavingSet(false)}>
              Отмена
            </Button>
            <Button onClick={saveSet} disabled={setName.trim().length < 2}>
              Сохранить
            </Button>
          </>
        }
      >
        <Input
          label="Название набора"
          value={setName}
          onChange={(e) => setSetName(e.target.value)}
          placeholder="Окна и остекление"
        />
      </Modal>

      <Modal
        open={importing}
        onClose={() => setImporting(false)}
        title="Загрузить список фраз"
        description="Вставьте как есть — из Вордстата, Key Collector или своего файла. Разделитель определится сам, частотность подхватится, если она есть."
        footer={
          <>
            <Button variant="secondary" onClick={() => setImporting(false)}>
              Отмена
            </Button>
            <Button onClick={runImport} loading={saving} disabled={draft.trim() === ""}>
              Разобрать
            </Button>
          </>
        }
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={12}
          spellCheck={false}
          placeholder={"пластиковые окна тверь\t5400\nкупить окна пвх\t3100"}
          className="border-border-input bg-bg text-body-sm text-text-primary rounded-control focus-visible:outline-focus w-full resize-y border p-3 font-mono focus-visible:outline-2"
        />
      </Modal>
    </AppShell>
  );
}

function KeywordRow({
  keyword,
  onMove,
}: {
  keyword: KeywordRead;
  onMove: (id: string, intent: Intent) => void;
}) {
  return (
    <div className="border-border flex flex-wrap items-center justify-between gap-3 border-b py-2.5 last:border-b-0">
      <div className="flex min-w-0 flex-col">
        <span className="text-body-sm text-text-primary">{keyword.phrase}</span>
        <span className="text-caption text-text-secondary">
          {keyword.frequency !== null ? `${keyword.frequency} в месяц` : "частотность неизвестна"}
          {/* Слово-причина показывается всегда: без него непонятно, что
              править, чтобы решение изменилось. */}
          {keyword.trigger && ` · из-за слова «${keyword.trigger}»`}
          {keyword.is_manual && " · решение ваше"}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <StatusBadge tone={INTENT_TONE[keyword.intent] ?? "neutral"}>
          {keyword.intent_label}
        </StatusBadge>
        {keyword.intent !== "irrelevant" ? (
          <Button size="sm" variant="ghost" onClick={() => onMove(keyword.id, "irrelevant")}>
            В нецелевые
          </Button>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => onMove(keyword.id, "commercial")}>
            Вернуть
          </Button>
        )}
      </div>
    </div>
  );
}
