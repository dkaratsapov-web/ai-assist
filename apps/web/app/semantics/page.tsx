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
  CrossMinusRead,
  GroupList,
  GroupRead,
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
  const [groups, setGroups] = useState<GroupList | null>(null);
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
          minusWords,
          savedSets,
          crossing,
          briefData,
          onboardingData,
          collectionData,
          groupsData,
        ] = await Promise.all([
          api.listKeywords(selectedId),
          api.listMinusWords(selectedId),
          api.listMinusWordSets(),
          api.getCrossMinus(selectedId),
          api.getBrief(selectedId),
          api.getOnboarding(selectedId),
          api.getCollection(selectedId),
          api.listGroups(selectedId),
        ]);
        if (ignore) return;
        setError(null);
        setKeywords(list.items);
        setMinus(minusWords);
        setSets(savedSets.items);
        setCross(crossing);
        setBrief(briefData);
        setOnboarding(onboardingData);
        setCollection(collectionData);
        setGroups(groupsData);
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

  const moveToGroup = async (ids: string[], group: string | null) => {
    if (!selectedId || ids.length === 0) return;
    try {
      await api.moveToGroup(selectedId, { keyword_ids: ids, group });
      reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

  const renameGroup = async (name: string, next: string) => {
    if (!selectedId) return;
    try {
      await api.renameGroup(selectedId, name, { name: next });
      reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

  const dissolveGroup = async (name: string) => {
    if (!selectedId) return;
    try {
      await api.dissolveGroup(selectedId, name);
      reload();
    } catch (err) {
      setError(toApiError(err));
    }
  };

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
              {groups && (groups.items.length > 0 || (groups.ungrouped ?? []).length > 0) && (
                <GroupsCard
                  groups={groups}
                  onRename={renameGroup}
                  onDissolve={dissolveGroup}
                  onMove={moveToGroup}
                />
              )}

              {cross && (cross.items.length > 0 || cross.duplicates.length > 0) && (
                <CrossMinusCard cross={cross} />
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

              <PhraseTable
                keywords={shown}
                groups={(groups?.items ?? []).map((g) => g.name)}
                onMove={move}
                onGroup={moveToGroup}
              />
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

/**
 * Кросс-минусовка.
 *
 * Раньше этот блок вываливал на экран все минус-слова каждой фразы подряд —
 * сотни слов в строку. Страница переставала листаться, а нужного в этой стене
 * всё равно было не разглядеть.
 *
 * Теперь наружу вынесено то, ради чего блок существует: сколько фраз
 * перехватывают чужие запросы и что с этим делать. Сами слова — под строкой
 * раскрытия и с кнопкой «скопировать»: их не читают, их переносят в Директ.
 */
function CrossMinusCard({ cross }: { cross: CrossMinusResultRead }) {
  return (
    <Card>
      <CardHeader
        title="Фразы конкурируют между собой"
        description="Общая фраза перехватывает запросы уточнённой — в отчёте это выглядит нормально"
        action={
          <span className="text-caption text-text-secondary tabular-nums">
            {cross.items.length} {plural(cross.items.length, "фраза", "фразы", "фраз")}
          </span>
        }
      />

      <div className="flex flex-col gap-3">
        {cross.duplicates.length > 0 && (
          <div className="flex flex-col gap-1">
            <span className="text-body-sm text-text-primary">
              Одинаковые для Директа — порядок слов он не различает
            </span>
            {cross.duplicates.map((group) => (
              <span key={group.phrases[0]} className="text-caption text-text-secondary">
                {group.phrases.join(" = ")}
              </span>
            ))}
          </div>
        )}

        {cross.items.length > 0 && (
          <Details summary={`Показать минус-слова по каждой фразе (${cross.items.length})`}>
            <div className="flex flex-col">
              {cross.items.map((item) => (
                <CrossMinusRow key={item.phrase} item={item} />
              ))}
            </div>
          </Details>
        )}

        <Hint>
          Переносить руками не нужно: эти минус-слова уже проставлены к каждой фразе в выгрузке для
          Коммандера.
        </Hint>
      </div>
    </Card>
  );
}

function CrossMinusRow({ item }: { item: CrossMinusRead }) {
  const words = item.minus_words.map((word) => `-${word}`).join(" ");

  return (
    <div className="border-border-subtle flex flex-wrap items-start justify-between gap-2 border-b py-2 last:border-b-0">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-body-sm text-text-primary">{item.phrase}</span>
        {/* Список обрезан по высоте: у популярной фразы минус-слов бывает под
            триста, и в полный рост они занимают экран целиком. */}
        <span className="text-caption text-text-secondary clamp-2 break-all">{words}</span>
        <span className="text-caption text-text-secondary">
          Иначе заберёт запросы: {item.shadows.slice(0, 3).join(", ")}
          {item.shadows.length > 3 && ` и ещё ${item.shadows.length - 3}`}
        </span>
      </div>
      <CopyButton value={words} />
    </div>
  );
}

/** Сколько строк показываем сразу. Дальше — по кнопке. */
const PAGE_SIZE = 200;

/**
 * Таблица фраз.
 *
 * Заменяет список из карточек, в котором каждая фраза занимала три строки и
 * шестьдесят пикселей высоты. На ядре в тысячу фраз — а это обычный размер —
 * такой список превращался в шесть тысяч пикселей прокрутки, и найти в нём
 * что-либо можно было только поиском по странице браузера.
 *
 * Что изменилось по существу:
 *
 * **Строка стала строкой.** Одна фраза — одна линия, всё в колонках. Числа
 * выровнены и моноширинные: ради сравнения частотностей список и читают.
 *
 * **Шапка не уезжает.** Без неё после сотни строк непонятно, что в какой
 * колонке.
 *
 * **Выделение и действия пачкой.** Разметить двести фраз по одной — это два
 * часа работы; выделить и нажать один раз — минута.
 *
 * **Показывается не всё сразу.** Две сотни строк рисуются мгновенно, две
 * тысячи — с заметной задержкой на каждом нажатии.
 */
function PhraseTable({
  keywords,
  groups,
  onMove,
  onGroup,
}: {
  keywords: KeywordRead[];
  groups: string[];
  onMove: (id: string, intent: Intent) => void;
  onGroup: (ids: string[], group: string | null) => void;
}) {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"frequency" | "phrase">("frequency");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [grouping, setGrouping] = useState(false);
  const [groupDraft, setGroupDraft] = useState("");

  const needle = search.trim().toLowerCase();
  const rows = useMemo(() => {
    const found = needle
      ? keywords.filter((k) => k.phrase.toLowerCase().includes(needle))
      : keywords;
    return [...found].sort((a, b) =>
      sort === "frequency"
        ? (b.frequency ?? 0) - (a.frequency ?? 0) || a.phrase.localeCompare(b.phrase)
        : a.phrase.localeCompare(b.phrase),
    );
  }, [keywords, needle, sort]);

  const shown = rows.slice(0, limit);
  const allShownSelected = shown.length > 0 && shown.every((row) => selected.has(row.id));

  const toggle = (id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    setSelected((current) => {
      if (allShownSelected) {
        const next = new Set(current);
        shown.forEach((row) => next.delete(row.id));
        return next;
      }
      return new Set([...current, ...shown.map((row) => row.id)]);
    });
  };

  const chosen = [...selected];

  const applyGroup = (name: string | null) => {
    onGroup(chosen, name);
    setSelected(new Set());
    setGrouping(false);
    setGroupDraft("");
  };

  return (
    <Card padding="none">
      <div className="border-border-subtle flex flex-wrap items-center gap-2 border-b p-3">
        <div className="min-w-48 flex-1">
          <Input
            placeholder="Поиск по фразам"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => setSort(sort === "frequency" ? "phrase" : "frequency")}
        >
          {sort === "frequency" ? "По частотности" : "По алфавиту"}
        </Button>
        <span className="text-caption text-text-secondary tabular-nums">
          {rows.length} {plural(rows.length, "фраза", "фразы", "фраз")}
        </span>
      </div>

      {/* Панель действий появляется только при выделении: постоянная строка с
          неактивными кнопками занимает место и ничего не сообщает. */}
      {chosen.length > 0 && (
        <div className="border-border-subtle bg-bg-secondary flex flex-wrap items-center gap-2 border-b px-3 py-2">
          <span className="text-caption text-text-primary tabular-nums">
            Выделено: {chosen.length}
          </span>
          <Button size="sm" variant="secondary" onClick={() => setGrouping(true)}>
            В группу
          </Button>
          <Button size="sm" variant="ghost" onClick={() => applyGroup(null)}>
            Убрать из групп
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              chosen.forEach((id) => onMove(id, "irrelevant"));
              setSelected(new Set());
            }}
          >
            В нецелевые
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            Снять выделение
          </Button>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead className="bg-surface sticky top-(--layout-topbar-height) z-10">
            <tr className="border-border-subtle text-micro text-text-secondary border-b text-left">
              <th className="w-8 py-2 pl-3">
                <input
                  type="checkbox"
                  checked={allShownSelected}
                  onChange={toggleAll}
                  aria-label="Выделить все показанные"
                  className="accent-text-primary size-3.5 align-middle"
                />
              </th>
              <th className="py-2 font-medium">Фраза</th>
              <th className="w-24 py-2 text-right font-medium">В месяц</th>
              <th className="w-32 py-2 pl-3 font-medium">Тип</th>
              <th className="w-44 py-2 pl-3 font-medium">Группа</th>
              <th className="w-24 py-2 pr-3" />
            </tr>
          </thead>
          <tbody>
            {shown.map((keyword) => (
              <PhraseRow
                key={keyword.id}
                keyword={keyword}
                checked={selected.has(keyword.id)}
                onToggle={() => toggle(keyword.id)}
                onMove={onMove}
              />
            ))}
          </tbody>
        </table>
      </div>

      {rows.length > shown.length && (
        <div className="border-border-subtle border-t p-3">
          <Button size="sm" variant="secondary" onClick={() => setLimit(limit + PAGE_SIZE)}>
            Показать ещё {Math.min(PAGE_SIZE, rows.length - shown.length)}
          </Button>
        </div>
      )}

      {shown.length === 0 && (
        <p className="text-body-sm text-text-secondary p-4">
          {needle ? "По этому запросу фраз нет." : "Фраз нет."}
        </p>
      )}

      <Modal
        open={grouping}
        onClose={() => setGrouping(false)}
        title={`Перенести фраз: ${chosen.length}`}
        footer={
          <>
            <Button variant="secondary" onClick={() => setGrouping(false)}>
              Отмена
            </Button>
            <Button onClick={() => applyGroup(groupDraft.trim())} disabled={!groupDraft.trim()}>
              Перенести
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Input
            label="Название группы"
            placeholder="Пластиковые окна"
            value={groupDraft}
            onChange={(e) => setGroupDraft(e.target.value)}
          />
          {groups.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <span className="text-caption text-text-secondary">Или выберите готовую</span>
              <div className="flex flex-wrap gap-1.5">
                {groups.map((name) => (
                  <button
                    key={name}
                    type="button"
                    onClick={() => setGroupDraft(name)}
                    className="border-border bg-bg-secondary text-caption text-text-primary rounded-pill hover:bg-surface-hover focus-visible:outline-focus border px-2.5 py-1 focus-visible:outline-2"
                  >
                    {name}
                  </button>
                ))}
              </div>
            </div>
          )}
          <Hint>
            Перенесённые фразы становятся вашим решением: пересчёт групп их больше не трогает.
          </Hint>
        </div>
      </Modal>
    </Card>
  );
}

function PhraseRow({
  keyword,
  checked,
  onToggle,
  onMove,
}: {
  keyword: KeywordRead;
  checked: boolean;
  onToggle: () => void;
  onMove: (id: string, intent: Intent) => void;
}) {
  return (
    <tr className="border-border-subtle hover:bg-surface-hover border-b last:border-b-0">
      <td className="py-1.5 pl-3 align-middle">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          aria-label={`Выделить «${keyword.phrase}»`}
          className="accent-text-primary size-3.5 align-middle"
        />
      </td>
      <td className="text-caption text-text-primary py-1.5 pr-3 align-middle">
        {keyword.phrase}
        {/* Причина — рядом с фразой и мелким: она нужна, только когда решение
            вызывает вопрос, а вопрос возникает у одной строки из двадцати. */}
        {keyword.reason_label && (
          <span className="text-text-secondary"> · {keyword.reason_label}</span>
        )}
      </td>
      <td className="text-caption text-text-secondary py-1.5 text-right align-middle tabular-nums">
        {keyword.frequency !== null ? keyword.frequency : "—"}
      </td>
      <td className="py-1.5 pl-3 align-middle">
        <StatusBadge tone={INTENT_TONE[keyword.intent] ?? "neutral"} size="sm">
          {keyword.intent_label}
        </StatusBadge>
      </td>
      <td className="text-caption text-text-secondary truncate py-1.5 pl-3 align-middle">
        {keyword.cluster_name ?? "—"}
      </td>
      <td className="py-1.5 pr-3 text-right align-middle">
        <button
          type="button"
          onClick={() =>
            onMove(keyword.id, keyword.intent === "irrelevant" ? "commercial" : "irrelevant")
          }
          className="text-caption text-text-secondary hover:text-text-primary focus-visible:outline-focus rounded-control px-1 focus-visible:outline-2"
        >
          {keyword.intent === "irrelevant" ? "Вернуть" : "Убрать"}
        </button>
      </td>
    </tr>
  );
}

/**
 * Группы под объявления.
 *
 * Раньше здесь был список из названий и чисел — посмотреть, что внутри группы,
 * было нельзя, а поправить тем более. Между тем структура кампании решается
 * именно здесь: одна группа — одно объявление и одна посадочная, и ошибка в
 * составе стоит дороже всего остального в этом экране.
 *
 * Отсюда три вещи. Фразы раскрываются внутри группы, а не в отдельном окне.
 * Название правится на месте. И видно, какие группы собрал человек: пересчёт
 * их не трогает, и не показать этого значило бы оставить необъяснимое
 * поведение.
 */
function GroupsCard({
  groups,
  onRename,
  onDissolve,
  onMove,
}: {
  groups: GroupList;
  onRename: (name: string, next: string) => void;
  onDissolve: (name: string) => void;
  onMove: (ids: string[], group: string | null) => void;
}) {
  const names = groups.items.map((group) => group.name);
  // Список необязателен в контракте: сервер шлёт его всегда, но
  // сгенерированный тип этого не знает.
  const ungrouped = groups.ungrouped ?? [];

  return (
    <Card>
      <CardHeader
        title="Группы под объявления"
        description="Одна группа — одно объявление и одна посадочная страница"
        action={
          <span className="text-caption text-text-secondary tabular-nums">
            {groups.total} {plural(groups.total, "группа", "группы", "групп")}
          </span>
        }
      />

      <div className="flex flex-col">
        {groups.items.map((group) => (
          <GroupRow
            key={group.name}
            group={group}
            others={names.filter((name) => name !== group.name)}
            onRename={onRename}
            onDissolve={onDissolve}
            onMove={onMove}
          />
        ))}
      </div>

      {ungrouped.length > 0 && (
        <div className="border-border-subtle mt-3 border-t pt-3">
          <Details
            summary={`Без группы: ${ungrouped.length} ${plural(ungrouped.length, "фраза", "фразы", "фраз")}`}
          >
            <p>
              Эти фразы в кампанию не пойдут: объявление собирается по группе. Перенесите их в
              таблице фраз или распустите ненужную группу, чтобы расчёт разложил всё заново.
            </p>
            <div className="flex flex-col">
              {ungrouped.slice(0, 30).map((phrase) => (
                <div
                  key={phrase.id}
                  className="border-border-subtle flex items-center justify-between gap-3 border-b py-1.5 last:border-b-0"
                >
                  <span className="text-caption text-text-primary">{phrase.phrase}</span>
                  <span className="text-caption text-text-secondary tabular-nums">
                    {phrase.frequency ?? "—"}
                  </span>
                </div>
              ))}
            </div>
          </Details>
        </div>
      )}
    </Card>
  );
}

function GroupRow({
  group,
  others,
  onRename,
  onDissolve,
  onMove,
}: {
  group: GroupRead;
  others: string[];
  onRename: (name: string, next: string) => void;
  onDissolve: (name: string) => void;
  onMove: (ids: string[], group: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(group.name);

  const save = () => {
    const next = draft.trim();
    if (next && next !== group.name) onRename(group.name, next);
    setEditing(false);
  };

  return (
    <div className="border-border-subtle border-b py-2 last:border-b-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {editing ? (
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <div className="min-w-48 flex-1">
              <Input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") save();
                  if (e.key === "Escape") setEditing(false);
                }}
                autoFocus
              />
            </div>
            <Button size="sm" onClick={save}>
              Сохранить
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Отмена
            </Button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="focus-visible:outline-focus rounded-control flex min-w-0 flex-1 items-center gap-2 text-left focus-visible:outline-2"
          >
            <span aria-hidden="true" className="text-text-secondary text-caption">
              {open ? "▾" : "▸"}
            </span>
            <span className="text-body-sm text-text-primary truncate font-medium">
              {group.name}
            </span>
            {/* Пометка обязательна: без неё непонятно, почему пересчёт одни
                группы трогает, а другие нет. */}
            {group.manual && (
              <StatusBadge tone="neutral" size="sm">
                ваша
              </StatusBadge>
            )}
          </button>
        )}

        <div className="flex shrink-0 items-center gap-3">
          <span className="text-caption text-text-secondary tabular-nums">
            {group.phrases.length} · {group.total_frequency}
          </span>
          {!editing && (
            <>
              <button
                type="button"
                onClick={() => {
                  setDraft(group.name);
                  setEditing(true);
                }}
                className="text-caption text-text-secondary hover:text-text-primary focus-visible:outline-focus rounded-control px-1 focus-visible:outline-2"
              >
                Переименовать
              </button>
              <button
                type="button"
                onClick={() => onDissolve(group.name)}
                className="text-caption text-text-secondary hover:text-text-primary focus-visible:outline-focus rounded-control px-1 focus-visible:outline-2"
              >
                Распустить
              </button>
            </>
          )}
        </div>
      </div>

      {open && (
        <div className="mt-1.5 ml-5 flex flex-col">
          {group.phrases.map((phrase) => (
            <div
              key={phrase.id}
              className="border-border-subtle flex flex-wrap items-center justify-between gap-2 border-b py-1 last:border-b-0"
            >
              <span className="text-caption text-text-primary min-w-0 flex-1 truncate">
                {phrase.phrase}
              </span>
              <span className="text-caption text-text-secondary shrink-0 tabular-nums">
                {phrase.frequency ?? "—"}
              </span>
              {/* Перенос прямо отсюда: искать эту же фразу в общей таблице,
                  чтобы переложить её в соседнюю группу, — лишняя работа. */}
              <select
                aria-label={`Перенести «${phrase.phrase}»`}
                value=""
                onChange={(e) => {
                  const target = e.target.value;
                  if (target) onMove([phrase.id], target === "__none__" ? null : target);
                }}
                className="border-border rounded-control text-caption text-text-secondary bg-surface shrink-0 border px-1.5 py-0.5"
              >
                <option value="">перенести…</option>
                {others.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
                <option value="__none__">убрать из групп</option>
              </select>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
