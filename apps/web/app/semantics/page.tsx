"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import type {
  ApiError,
  BriefRead,
  CleanupGroupRead,
  CollectionMaskRead,
  CollectionRead,
  CleanupResult,
  ClusterRead,
  CrossMinusResultRead,
  ImportSummary,
  Intent,
  OnboardingRead,
  QuestionRead,
  KeywordRead,
  MinusWordList,
  MinusWordSetRead,
  ProjectRead,
} from "@ads-os/schemas";
import {
  Button,
  Card,
  CardHeader,
  Details,
  EmptyState,
  Hint,
  ProgressBar,
  ErrorState,
  FilterBar,
  Input,
  Modal,
  ProjectSwitcher,
  Skeleton,
  StatusBadge,
  plural,
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
  const [cleaning, setCleaning] = useState(false);
  const [dropping, setDropping] = useState(false);
  const [cleanup, setCleanup] = useState<CleanupResult | null>(null);
  const [brief, setBrief] = useState<BriefRead | null>(null);
  const [collection, setCollection] = useState<CollectionRead | null>(null);
  const [collecting, setCollecting] = useState(false);
  const [onboarding, setOnboarding] = useState<OnboardingRead | null>(null);
  const [applying, setApplying] = useState(false);
  const [questionsOpen, setQuestionsOpen] = useState(false);
  const [briefOpen, setBriefOpen] = useState(false);
  const [briefDraft, setBriefDraft] = useState({
    sells: "",
    synonyms: "",
    excludes: "",
    cities: "",
  });

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
        const [
          list,
          groups,
          minusWords,
          savedSets,
          crossing,
          briefData,
          onboardingData,
          collectionData,
        ] = await Promise.all([
          api.listKeywords(selectedId),
          api.listClusters(selectedId),
          api.listMinusWords(selectedId),
          api.listMinusWordSets(),
          api.getCrossMinus(selectedId),
          api.getBrief(selectedId),
          api.getOnboarding(selectedId),
          api.getCollection(selectedId),
        ]);
        if (ignore) return;
        setError(null);
        setKeywords(list.items);
        setClusters(groups.items);
        setMinus(minusWords);
        setSets(savedSets.items);
        setCross(crossing);
        setBrief(briefData);
        setOnboarding(onboardingData);
        setCollection(collectionData);
        setBriefDraft({
          sells: briefData.sells ?? "",
          synonyms: briefData.synonyms ?? "",
          excludes: briefData.excludes ?? "",
          cities: briefData.cities ?? "",
        });
      } catch (err) {
        if (!ignore) setError(toApiError(err));
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, selectedId, reloadToken]);

  const reload = useCallback(() => setReloadToken((token) => token + 1), []);

  const startCollection = async () => {
    if (!selectedId) return;
    setCollecting(true);
    try {
      setCollection(await api.startCollection(selectedId));
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setCollecting(false);
    }
  };

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

  const saveAnswer = async (key: string, value: string) => {
    if (!selectedId) return;
    try {
      setOnboarding(await api.saveAnswers(selectedId, { [key]: value }));
      // Ответ «чего клиент не делает» попадает в бриф — его надо перечитать.
      if (key === "not_selling") reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

  const applyOnboarding = async (fields: {
    region?: boolean;
    niche?: boolean;
    brief?: boolean;
  }) => {
    if (!selectedId) return;
    setApplying(true);
    try {
      setOnboarding(await api.applyOnboarding(selectedId, fields));
      reload();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setApplying(false);
    }
  };

  const saveBrief = async () => {
    if (!selectedId) return;
    setSaving(true);
    try {
      setBrief(await api.saveBrief(selectedId, briefDraft));
      setBriefOpen(false);
    } catch (err) {
      setError(toApiError(err));
      setBriefOpen(false);
    } finally {
      setSaving(false);
    }
  };

  /**
   * Файл читается прямо во вкладке и уходит текстом в base64.
   *
   * Так у выгрузки и у вставленного вручную списка остаётся один путь разбора:
   * два разных рано или поздно разойдутся, и разойдутся на чужом файле.
   */
  const importFile = async (file: File) => {
    if (!selectedId) return;
    setSaving(true);
    try {
      const buffer = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (const byte of buffer) binary += String.fromCharCode(byte);
      setSummary(await api.importKeywordsFile(selectedId, file.name, btoa(binary)));
      setImporting(false);
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

  const addAllMinus = async (words: string[]) => {
    if (!selectedId) return;
    try {
      await api.addMinusWords(selectedId, words);
      reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

  const recheck = async () => {
    if (!selectedId) return;
    setCleaning(true);
    try {
      setCleanup(await api.recheckKeywords(selectedId));
      reload();
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setCleaning(false);
    }
  };

  const dropIrrelevant = async () => {
    if (!selectedId) return;
    setCleaning(true);
    try {
      setCleanup(await api.dropIrrelevantKeywords(selectedId));
      setDropping(false);
      reload();
    } catch (err) {
      setError(toApiError(err));
      setDropping(false);
    } finally {
      setCleaning(false);
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
              {summary.cleaned.length > 0 && <CleanupBreakdown groups={summary.cleaned} />}
            </Card>
          )}

          {cleanup && (
            <Card>
              <p className="text-body-sm text-text-primary">
                Готово: затронуто {cleanup.affected}{" "}
                {plural(cleanup.affected, "фраза", "фразы", "фраз")}. В ядре осталось{" "}
                {cleanup.remaining}: целевых {cleanup.commercial}, информационных{" "}
                {cleanup.informational}, нецелевых {cleanup.irrelevant}. Групп: {cleanup.clusters}.
              </p>
            </Card>
          )}

          {/* Бриф стоит выше списка фраз намеренно: сначала человек отвечает,
              что продаёт, потом идёт собирать. В обратном порядке он собирает
              наугад и приносит список, половину которого потом вычищает. */}
          {onboarding && (
            <OnboardingCard
              data={onboarding}
              onApply={applyOnboarding}
              busy={applying}
              questionsOpen={questionsOpen}
              onToggleQuestions={() => setQuestionsOpen((open) => !open)}
              onAnswer={saveAnswer}
            />
          )}

          {brief && <BriefCard brief={brief} onEdit={() => setBriefOpen(true)} />}

          {collection && (
            <CollectionCard
              collection={collection}
              busy={collecting}
              canStart={Boolean(brief?.sells?.trim())}
              onStart={startCollection}
            />
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
                        className="border-border-subtle flex flex-wrap items-baseline justify-between gap-2 border-b py-2.5 last:border-b-0"
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
                          className="border-border-subtle flex flex-col gap-1 border-b py-2.5 last:border-b-0"
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
                      <SuggestedWords
                        title="Стартовый набор — минусуют почти всегда"
                        words={minus.from_niche}
                        onAdd={addMinus}
                        onAddAll={addAllMinus}
                      />
                    )}
                    {minus.learned.length > 0 && (
                      // Подсказка, а не автоматика: слово не добавляется само.
                      // Тихо отсечённый трафик — это то, о чём человек не
                      // просил и о чём не узнает.
                      <SuggestedWords
                        title="Вы относили это к нецелевым в других проектах"
                        words={minus.learned}
                        onAdd={addMinus}
                        onAddAll={addAllMinus}
                      />
                    )}
                    {minus.suggestions.length > 0 && (
                      <>
                        <p className="text-caption text-text-secondary mb-1">Предлагаются</p>
                        <div className="flex flex-col">
                          {minus.suggestions.map((item) => (
                            <div
                              key={item.word}
                              className="border-border-subtle flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-b-0"
                            >
                              <div className="flex min-w-0 flex-col">
                                <span className="text-body-sm text-text-primary">
                                  {item.word}
                                  {item.reason_label && (
                                    <span className="text-text-secondary">
                                      {" "}
                                      — {item.reason_label}
                                    </span>
                                  )}
                                </span>
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

              <Card>
                <CardHeader
                  title="Чистка ядра"
                  description="Разметка — предложение, а не приговор: любую фразу можно вернуть одним нажатием"
                />
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="secondary" onClick={recheck} loading={cleaning}>
                    Перепроверить заново
                  </Button>
                  {counts.irrelevant > 0 && (
                    <Button size="sm" variant="ghost" onClick={() => setDropping(true)}>
                      Убрать нецелевые ({counts.irrelevant})
                    </Button>
                  )}
                </div>
                <Details summary="Когда нужна перепроверка" className="mt-3">
                  <p>
                    После того как поменялся регион проекта или минус-слова: фразы, загруженные
                    раньше, разбирались по старым условиям. Ваши решения перепроверка не трогает.
                  </p>
                </Details>
              </Card>

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
        open={briefOpen}
        onClose={() => setBriefOpen(false)}
        title="Бриф для сбора запросов"
        description="Четыре вопроса. Из ответов соберутся строки, которые останется вставить в Вордстат — придумывать их самому не придётся."
        footer={
          <>
            <Button variant="secondary" onClick={() => setBriefOpen(false)}>
              Отмена
            </Button>
            <Button onClick={saveBrief} loading={saving} disabled={briefDraft.sells.trim() === ""}>
              Сохранить
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Input
            label="Что продаём"
            value={briefDraft.sells}
            onChange={(e) => setBriefDraft({ ...briefDraft, sells: e.target.value })}
            placeholder="пластиковые окна, остекление балконов"
            hint="Через запятую. Это главное поле — из него строятся все строки."
          />
          <Input
            label="Как это называют иначе"
            value={briefDraft.synonyms}
            onChange={(e) => setBriefDraft({ ...briefDraft, synonyms: e.target.value })}
            placeholder="окна пвх, стеклопакеты"
            hint="Чужие слова важнее своих: человек ищет теми, к которым привык, а не теми, что в прайсе."
          />
          <Input
            label="Чего не делаем"
            value={briefDraft.excludes}
            onChange={(e) => setBriefDraft({ ...briefDraft, excludes: e.target.value })}
            placeholder="ремонт окон, москитные сетки"
            hint="Отсюда берутся минусы. Единственное, что нельзя угадать за клиента."
          />
          <Input
            label="Города, если они шире региона проекта"
            value={briefDraft.cities}
            onChange={(e) => setBriefDraft({ ...briefDraft, cities: e.target.value })}
            placeholder="тверь, конаково"
            hint="Можно оставить пустым — тогда берётся регион проекта."
          />
        </div>
      </Modal>

      <Modal
        open={dropping}
        onClose={() => setDropping(false)}
        title={`Убрать нецелевые фразы (${counts.irrelevant})`}
        description="Фразы удалятся из проекта. Те, тип которых поставили вы, останутся — кнопка убирает решения словаря, а не ваши. Загрузить список заново можно в любой момент."
        footer={
          <>
            <Button variant="secondary" onClick={() => setDropping(false)}>
              Отмена
            </Button>
            <Button onClick={dropIrrelevant} loading={cleaning}>
              Убрать
            </Button>
          </>
        }
      >
        <p className="text-body-sm text-text-secondary">
          Перед удалением стоит пролистать список нецелевых с фильтром — у каждой фразы написано,
          из-за чего она туда попала.
        </p>
      </Modal>

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
        {/* Файл идёт первым: из Вордстата выгрузка приходит файлом, и открывать
            его, чтобы скопировать содержимое, — лишний шаг ни за чем. */}
        <label className="border-border-input rounded-control hover:bg-bg-secondary mb-3 flex cursor-pointer flex-col items-center gap-1 border border-dashed p-4 text-center">
          <span className="text-body-sm text-text-primary">Выбрать файл выгрузки</span>
          <span className="text-caption text-text-secondary">
            xlsx из Вордстата, csv из Key Collector или обычный txt
          </span>
          <input
            type="file"
            accept=".xlsx,.csv,.txt,.tsv"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void importFile(file);
            }}
          />
        </label>

        <p className="text-caption text-text-secondary mb-1.5">или вставьте текст</p>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={10}
          spellCheck={false}
          placeholder={"пластиковые окна тверь\t5400\nкупить окна пвх\t3100"}
          className="border-border-input bg-bg text-body-sm text-text-primary rounded-control focus-visible:outline-focus w-full resize-y border p-3 font-mono focus-visible:outline-2"
        />
      </Modal>
    </AppShell>
  );
}

const APPLY_LABELS: Record<string, string> = {
  region: "регион проекта",
  niche: "нишу",
  brief: "услуги в бриф",
};

/**
 * Анкета клиента: что прочитано с сайта и что осталось спросить.
 *
 * Граница между половинами не косметическая. Слева то, что на сайте написано, —
 * это факты, их видно и можно проверить глазами. Справа то, чего на сайте не
 * бывает: средний чек, маржа, что клиент на самом деле не делает. Подставить
 * туда правдоподобные числа значило бы построить весь расчёт экономики на
 * выдумке — поэтому там вопросы, а не значения.
 */
function OnboardingCard({
  data,
  onApply,
  busy,
  questionsOpen,
  onToggleQuestions,
  onAnswer,
}: {
  data: OnboardingRead;
  onApply: (fields: { region?: boolean; niche?: boolean; brief?: boolean }) => void;
  busy: boolean;
  questionsOpen: boolean;
  onToggleQuestions: () => void;
  onAnswer: (key: string, value: string) => void;
}) {
  const p = data.profile;
  const questions = [...data.questions, ...data.niche_questions];
  const answered = questions.filter((question) => question.answer).length;

  const facts: [string, string][] = [
    ["Компания", p.company ?? ""],
    ["Город", p.city ?? ""],
    ["Ниша", p.niche_label ?? ""],
    ["Услуги", (p.services ?? []).join(", ")],
    ["Цены на сайте", (p.prices ?? []).join(", ")],
    ["Телефоны", (p.phones ?? []).join(", ")],
    ["Мессенджеры", (p.messengers ?? []).join(", ")],
    ["Почта", (p.emails ?? []).join(", ")],
    ["Адрес", p.address ?? ""],
    ["Реквизиты", p.company_details ?? ""],
    ["Режим работы", p.working_hours ?? ""],
  ];

  return (
    <Card>
      <CardHeader
        title="Что известно о клиенте"
        description={
          data.has_audit
            ? "Слева — прочитанное с сайта, справа — то, чего на сайте не бывает"
            : "Сайт ещё не проверяли — читать нечего"
        }
      />

      {!data.has_audit ? (
        <Hint className="mt-2">
          Запустите проверку сайта на экране «Аудит». Тем же заходом система прочитает название,
          город, услуги, цены и контакты — вписывать их руками не придётся.
        </Hint>
      ) : (
        <>
          {data.source_url && (
            // Источник виден намеренно: анкета, собранная с тестовой копии
            // сайта, выглядит точно так же, как настоящая.
            <p className="text-caption text-text-secondary mt-2 break-all">
              Прочитано со страницы {data.source_url}
            </p>
          )}

          <dl className="mt-3 flex flex-col">
            {facts
              .filter(([, value]) => value !== "")
              .map(([label, value]) => (
                <div
                  key={label}
                  className="border-border-subtle flex flex-wrap gap-x-3 border-b py-2 last:border-b-0"
                >
                  <dt className="text-caption text-text-secondary w-36 shrink-0">{label}</dt>
                  <dd className="text-body-sm text-text-primary min-w-0 flex-1">{value}</dd>
                </div>
              ))}
          </dl>

          {data.filled === 0 && (
            <Hint className="mt-2">
              На странице не нашлось ни города, ни услуг, ни контактов. Так бывает, если сайт
              собирается скриптами: наш разбор видит пустой каркас. Заполните бриф руками.
            </Hint>
          )}

          {data.can_apply.length > 0 && (
            <div className="border-border mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
              <span className="text-caption text-text-secondary">
                Перенести в проект: {data.can_apply.map((key) => APPLY_LABELS[key]).join(", ")}
              </span>
              <Button
                size="sm"
                loading={busy}
                onClick={() =>
                  onApply({
                    region: data.can_apply.includes("region"),
                    niche: data.can_apply.includes("niche"),
                    brief: data.can_apply.includes("brief"),
                  })
                }
              >
                Заполнить по сайту
              </Button>
              {/* Выборочно — потому что разбор ошибается, и взять город, но не
                  взять нишу, это обычное дело. */}
              {data.can_apply.includes("region") && data.can_apply.length > 1 && (
                <Button size="sm" variant="ghost" onClick={() => onApply({ region: true })}>
                  Только регион
                </Button>
              )}
            </div>
          )}
        </>
      )}

      <div className="border-border mt-3 border-t pt-3">
        <button
          type="button"
          onClick={onToggleQuestions}
          className="text-body-sm text-text-primary focus-visible:outline-focus text-left font-medium focus-visible:outline-2"
        >
          Спросить у клиента — отвечено {answered} из {questions.length} {questionsOpen ? "▲" : "▼"}
        </button>
        <p className="text-caption text-text-secondary mt-1">
          Этого нет ни на одном сайте, а без ответов расчёт окупаемости строить не на чем.
        </p>

        {questionsOpen && (
          <ol className="mt-2 flex flex-col">
            {questions.map((question: QuestionRead) => (
              <QuestionRow key={question.key} question={question} onAnswer={onAnswer} />
            ))}
          </ol>
        )}
      </div>
    </Card>
  );
}

/**
 * Бриф и то, что из него следует.
 *
 * Долгая часть сбора запросов — не нажатия в Вордстате, а придумывание, что
 * туда вводить. Ответы на четыре вопроса превращаются в готовые строки, а сам
 * сбор остаётся ручным — и здесь же написано, почему.
 */
function BriefCard({ brief, onEdit }: { brief: BriefRead; onEdit: () => void }) {
  const filled = (brief.sells ?? "").trim() !== "";

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <CardHeader
          title="С чего начать сбор"
          description={
            filled
              ? "Готовые строки для Вордстата — вставляйте по очереди"
              : "Ответьте на четыре вопроса, и система соберёт строки для Вордстата"
          }
        />
        <Button size="sm" variant={filled ? "ghost" : "primary"} onClick={onEdit}>
          {filled ? "Изменить бриф" : "Заполнить бриф"}
        </Button>
      </div>

      {!filled ? (
        <Details summary="Почему часть работы остаётся ручной">
          <p>{brief.why_manual}</p>
        </Details>
      ) : (
        <>
          <ol className="mb-3 flex flex-col gap-1.5">
            {brief.steps.map((step, index) => (
              <li key={index} className="text-body-sm text-text-secondary flex gap-2">
                <span className="text-text-primary tabular-nums">{index + 1}.</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>

          <div className="border-border flex flex-col border-t pt-3">
            {brief.masks.map((mask) => (
              <div
                key={mask.query}
                className="border-border-subtle flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-b-0"
              >
                <div className="flex min-w-0 flex-col">
                  <code className="text-body-sm text-text-primary break-all">{mask.query}</code>
                  <span className="text-caption text-text-secondary">{mask.purpose}</span>
                </div>
                <CopyButton value={mask.query} />
              </div>
            ))}
          </div>

          <Details summary="Почему часть работы остаётся ручной" className="mt-3">
            <p>{brief.why_manual}</p>
          </Details>
        </>
      )}
    </Card>
  );
}

/**
 * Вопрос вместе с полем для ответа.
 *
 * Раньше вопросы только читались, и человек уходил записывать ответы в
 * блокнот — то есть в систему они не попадали вовсе, а спрашивать их
 * приходилось каждый раз заново.
 *
 * Сохранение по уходу из поля, а не по кнопке. Кнопка «сохранить» на десять
 * полей означает, что одно забытое нажатие стирает всю работу — а работа здесь
 * это разговор с клиентом, который второй раз не состоится.
 */
function QuestionRow({
  question,
  onAnswer,
}: {
  question: QuestionRead;
  onAnswer: (key: string, value: string) => void;
}) {
  const [value, setValue] = useState(question.answer ?? "");
  const [saved, setSaved] = useState(false);

  return (
    <li className="border-border-subtle border-b py-2.5 last:border-b-0">
      <p className="text-body-sm text-text-primary">{question.text}</p>
      <p className="text-caption text-text-secondary">{question.why}</p>
      <div className="mt-1.5 flex items-start gap-2">
        <textarea
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setSaved(false);
          }}
          onBlur={() => {
            // Ничего не менялось — не дёргаем сервер и не мигаем «сохранено»:
            // подтверждение того, чего не было, обесценивает подтверждения.
            if ((question.answer ?? "") === value.trim()) return;
            onAnswer(question.key, value.trim());
            setSaved(true);
          }}
          rows={1}
          placeholder="Ответ клиента"
          className="border-border-input bg-bg text-body-sm text-text-primary rounded-control focus-visible:outline-focus w-full resize-y border px-2.5 py-1.5 focus-visible:outline-2"
        />
        {saved && <span className="text-caption text-success shrink-0 pt-2">сохранено</span>}
      </div>
    </li>
  );
}

/** Кнопка «скопировать» с подтверждением: без него непонятно, сработала ли. */
function CopyButton({ value }: { value: string }) {
  const [done, setDone] = useState(false);

  return (
    <Button
      size="sm"
      variant="ghost"
      onClick={() => {
        void navigator.clipboard.writeText(value).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 2000);
        });
      }}
    >
      {done ? "Скопировано" : "Копировать"}
    </Button>
  );
}

/**
 * Список слов-подсказок с кнопкой «добавить все».
 *
 * Стартовый набор ниши — это два десятка слов, и принимают их обычно целиком.
 * Двадцать нажатий с ожиданием перепроверки после каждого — та самая работа,
 * ради снятия которой всё и делается.
 */
function SuggestedWords({
  title,
  words,
  onAdd,
  onAddAll,
}: {
  title: string;
  words: string[];
  onAdd: (word: string) => void;
  onAddAll: (words: string[]) => void;
}) {
  return (
    <div className="border-border mb-3 border-t pt-3">
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <p className="text-caption text-text-secondary">{title}</p>
        {words.length > 1 && (
          <Button size="sm" variant="ghost" onClick={() => onAddAll(words)}>
            Добавить все ({words.length})
          </Button>
        )}
      </div>
      {/* Метки, а не кнопки-ссылки. Раньше два десятка слов шли подряд
          обычным текстом со знаком плюс — ряд читался как абзац, и было
          неочевидно, что по каждому слову можно нажать. */}
      <div className="flex flex-wrap gap-1.5">
        {words.map((word) => (
          <button
            key={word}
            type="button"
            onClick={() => onAdd(word)}
            className="border-border bg-bg-secondary text-caption text-text-primary rounded-pill hover:bg-surface-hover focus-visible:outline-focus border px-2.5 py-1 transition-colors duration-(--duration-fast) focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            + {word}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * Из чего складывается нецелевая часть списка.
 *
 * Отвечает на единственный вопрос, который человек задаёт после загрузки трёх
 * тысяч фраз: «а не выкинуло ли оно лишнего». Ответить на него можно только
 * назвав причину и показав примеры — число «нецелевых: 480» само по себе не
 * значит ничего.
 */
function CleanupBreakdown({ groups }: { groups: CleanupGroupRead[] }) {
  return (
    <div className="border-border mt-3 flex flex-col border-t pt-3">
      <p className="text-caption text-text-secondary mb-1.5">Что ушло в нецелевые и почему</p>
      {groups.map((group) => (
        <div key={group.reason} className="border-border-subtle border-b py-2 last:border-b-0">
          <p className="text-body-sm text-text-primary">
            {group.label} — {group.phrases} {plural(group.phrases, "фраза", "фразы", "фраз")}
          </p>
          <p className="text-caption text-text-secondary">{group.hint}</p>
          <p className="text-caption text-text-secondary mt-0.5">
            например: {group.examples.join(", ")}
          </p>
        </div>
      ))}
    </div>
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
    <div className="border-border-subtle flex flex-wrap items-center justify-between gap-3 border-b py-2.5 last:border-b-0">
      <div className="flex min-w-0 flex-col">
        <span className="text-body-sm text-text-primary">{keyword.phrase}</span>
        <span className="text-caption text-text-secondary">
          {keyword.frequency !== null ? `${keyword.frequency} в месяц` : "частотность неизвестна"}
          {/* Слово-причина показывается всегда: без него непонятно, что
              править, чтобы решение изменилось. Вид причины — рядом: «москва»
              сама по себе не объясняет ничего, «другой город» объясняет сразу. */}
          {keyword.trigger && ` · из-за «${keyword.trigger}»`}
          {keyword.reason_label && ` (${keyword.reason_label})`}
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

/** Названия состояний маски. Ключи приходят с backend. */
const MASK_STATE: Record<string, { label: string; tone: Tone }> = {
  pending: { label: "ждёт", tone: "neutral" },
  done: { label: "собрана", tone: "success" },
  failed: { label: "не вышло", tone: "warning" },
};

/**
 * Сбор частотностей.
 *
 * Всё, что здесь показано, продиктовано одним числом: сто запросов в час на
 * весь сервис. Из него следует, что сбор — не кнопка с ожиданием, а задание,
 * которое идёт фоном и может встать на середине.
 *
 * Поэтому на экране три вещи, которых обычно у кнопки не бывает: сколько масок
 * пройдено из скольких, сколько запросов осталось в этом часе и когда сбор
 * продолжится сам. Без последнего человек видит замерший прогресс и нажимает
 * «повторить», тратя запросы, которых и так нет.
 */
function CollectionCard({
  collection,
  busy,
  canStart,
  onStart,
}: {
  collection: CollectionRead;
  busy: boolean;
  canStart: boolean;
  onStart: () => void;
}) {
  if (collection.blocked_reason) {
    return (
      <Card tone="quiet">
        <div className="flex flex-col gap-1">
          <span className="text-body-sm text-text-primary font-medium">
            Сбор частотностей автоматически
          </span>
          <Hint>{collection.blocked_reason}</Hint>
        </div>
      </Card>
    );
  }

  const running = collection.status === "queued" || collection.status === "running";
  const done = collection.done_count ?? 0;
  const total = collection.total_count ?? 0;

  return (
    <Card>
      <CardHeader
        title="Сбор частотностей"
        description="Система пройдёт по маскам сама и сложит найденное в ядро"
        action={
          <Button size="sm" onClick={onStart} loading={busy} disabled={running || !canStart}>
            {collection.exists ? "Собрать заново" : "Собрать"}
          </Button>
        }
      />

      <div className="flex flex-col gap-3">
        {!canStart && <Hint>Сначала заполните бриф — из него строятся маски.</Hint>}

        {collection.exists && total > 0 && (
          <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-body-sm text-text-primary">
                Пройдено масок: {done} из {total}
              </span>
              <span className="text-caption text-text-secondary tabular-nums">
                добавлено {collection.added ?? 0} · обновлено {collection.updated ?? 0}
              </span>
            </div>
            <ProgressBar value={done} total={total} label={`Пройдено масок: ${done} из ${total}`} />
          </div>
        )}

        {/* Отдельной строкой, потому что это единственное объяснение замершего
            прогресса. Без него человек считает, что сбор сломался. */}
        {collection.resumes_at && running && (
          <p className="text-body-sm text-text-primary">
            Лимит запросов на этот час исчерпан. Сбор продолжится сам в{" "}
            {new Date(collection.resumes_at).toLocaleTimeString("ru-RU", {
              hour: "2-digit",
              minute: "2-digit",
            })}
            .
          </p>
        )}

        {collection.error_reason && (
          <p className="text-body-sm text-critical">{collection.error_reason}</p>
        )}

        {collection.exists && (collection.masks ?? []).length > 0 && (
          <Details summary="Что собрано по каждой маске">
            <div className="flex flex-col">
              {(collection.masks ?? []).map((mask) => (
                <MaskProgressRow key={mask.query} mask={mask} />
              ))}
            </div>
          </Details>
        )}

        <Hint>
          Площадка отдаёт сто запросов в час на весь сервис — это её ограничение, не наше. Поэтому
          сбор идёт фоном: можно закрыть страницу и вернуться позже. В этом часе осталось{" "}
          {collection.quota_left ?? 0}.
        </Hint>
      </div>
    </Card>
  );
}

function MaskProgressRow({ mask }: { mask: CollectionMaskRead }) {
  const state = MASK_STATE[mask.state ?? "pending"] ?? MASK_STATE.pending;

  return (
    <div className="border-border-subtle flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-b-0">
      <div className="flex min-w-0 flex-col">
        <code className="text-body-sm text-text-primary break-all">{mask.query}</code>
        {mask.reason && <span className="text-caption text-text-secondary">{mask.reason}</span>}
      </div>
      <div className="flex shrink-0 items-center gap-3">
        {mask.state === "done" && (
          <span className="text-caption text-text-secondary tabular-nums">
            фраз: {mask.found ?? 0} · объём темы: {mask.total ?? 0}
          </span>
        )}
        <StatusBadge tone={state?.tone ?? "neutral"} size="sm">
          {state?.label ?? mask.state}
        </StatusBadge>
      </div>
    </div>
  );
}
