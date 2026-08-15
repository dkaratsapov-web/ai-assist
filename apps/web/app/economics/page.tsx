"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  type ApiError,
  type EconomicsResponse,
  type EconomicsUpdate,
  type MetricRead,
  type ProjectRead,
} from "@ads-os/schemas";
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Input,
  KpiCard,
  ProjectSwitcher,
  Skeleton,
  StatusBadge,
  formatCurrency,
  formatNumber,
} from "@ads-os/ui";
import { IconIdea } from "@ads-os/ui/icons";
import { AppShell } from "@/components/AppShell";
import { createApiClient } from "@/lib/api";
import { toApiError } from "@/lib/errors";

/** Поля ввода экономики. Порядок повторяет деление на обязательное и желательное. */
const REQUIRED_FIELDS = [
  { key: "monthly_budget", label: "Месячный бюджет, ₽", hint: "Сколько готовы тратить в месяц" },
  { key: "average_order_value", label: "Средний чек, ₽", hint: "Или ожидаемая ценность клиента" },
] as const;

const RECOMMENDED_FIELDS = [
  { key: "margin_percent", label: "Маржинальность, %", hint: "Валовая маржа со сделки" },
  { key: "lead_to_sale_rate", label: "Конверсия из лида в продажу", hint: "Доля от 0 до 1" },
  { key: "target_cac", label: "Целевой CAC, ₽", hint: "Если не задан — считается по марже" },
  { key: "target_cpl", label: "Целевой CPL, ₽", hint: "Если не задан — считается по CAC" },
] as const;

/**
 * Поля прогноза.
 *
 * Без них известна только ёмкость бюджета — «на сколько заявок хватит денег,
 * если цена окажется целевой». С ними считается то, что на самом деле нужно:
 * сколько заявок будет при известной цене клика и конверсии страницы.
 */
const FORECAST_FIELDS = [
  {
    key: "expected_cpc",
    label: "Ожидаемая цена клика, ₽",
    hint: "Из прошлых кампаний или прогноза Директа",
  },
  {
    key: "site_conversion_rate",
    label: "Конверсия посадочной",
    hint: "Доля от 0 до 1: 0.03 — это 3 %",
  },
] as const;

type FieldKey =
  | (typeof REQUIRED_FIELDS)[number]["key"]
  | (typeof RECOMMENDED_FIELDS)[number]["key"]
  | (typeof FORECAST_FIELDS)[number]["key"];

export default function EconomicsPage() {
  // useSearchParams требует границы Suspense при пререндере страницы.
  return (
    <Suspense
      fallback={
        <AppShell title="Экономика проекта">
          <Skeleton shape="card" />
        </AppShell>
      }
    >
      <EconomicsScreen />
    </Suspense>
  );
}

function EconomicsScreen() {
  const api = useMemo(() => createApiClient(), []);
  // Проект может прийти ссылкой из карточки проекта: переход должен открывать
  // экономику именно того проекта, из которого пришли.
  const requestedProject = useSearchParams().get("project");

  const [projects, setProjects] = useState<ProjectRead[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [economics, setEconomics] = useState<EconomicsResponse | null>(null);
  const [draft, setDraft] = useState<Partial<Record<FieldKey, string>>>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);
  // Счётчик повторов: увеличение перезапускает загрузку, не дублируя её код.
  const [reloadToken, setReloadToken] = useState(0);

  // Загрузка вынесена внутрь асинхронного замыкания, а не вызывается прямо в
  // теле эффекта: синхронный setState в эффекте вызывает каскадные
  // перерисовки. Флаг отмены закрывает гонку — при быстром переключении
  // проектов ответ по предыдущему не должен затирать текущий.
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

  useEffect(() => {
    if (!selectedId) return;
    let ignore = false;

    void (async () => {
      try {
        const response = await api.getEconomics(selectedId);
        if (ignore) return;
        setError(null);
        setEconomics(response);
        setDraft(toDraft(response));
      } catch (err) {
        if (ignore) return;
        setError(toApiError(err));
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, selectedId, reloadToken]);

  // Пока загруженная экономика относится к другому проекту, показываются
  // скелетоны: это честнее, чем показать чужие цифры на долю секунды.
  const selected = economics?.project_id === selectedId ? economics : null;
  const summary = selected?.summary;

  const save = async () => {
    if (!selectedId) return;
    setSaving(true);
    setError(null);
    try {
      const payload: EconomicsUpdate = {
        ...toPayload(draft),
        // Версия, на которой пользователь редактировал: защищает от записи
        // поверх чужого изменения (v0.4 §100).
        expected_version: selected?.input?.version ?? null,
      };
      const response = await api.updateEconomics(selectedId, payload);
      setEconomics(response);
      setDraft(toDraft(response));
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <AppShell title="Экономика проекта" subtitle="Третий шаг цепочки работы с проектом">
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
                  projects={projects.map((p) => ({
                    id: p.id,
                    name: p.name,
                    status: p.status,
                  }))}
                  selectedId={selectedId ?? ""}
                  onSelect={setSelectedId}
                />
              )}
            </div>

            {summary && (
              <StatusBadge
                tone={
                  summary.mode === "complete"
                    ? "success"
                    : summary.mode === "limited"
                      ? "warning"
                      : "neutral"
                }
                size="md"
              >
                {summary.mode === "complete"
                  ? "Экономика заполнена"
                  : summary.mode === "limited"
                    ? "Экономика заполнена частично"
                    : "Экономика не заполнена"}
              </StatusBadge>
            )}
          </section>

          {/* Подсказка о том, что заполнить, — часть требования v0.4 §5. */}
          {summary?.cta && (
            <Card className="border-warning-border bg-warning-bg">
              <div className="flex items-start gap-3">
                <span className="text-warning mt-0.5">
                  <IconIdea size={18} />
                </span>
                <div>
                  <p className="text-body-sm text-text-primary font-medium">{summary.cta}</p>
                  {summary.missing_recommended.length > 0 && (
                    <p className="text-caption text-text-secondary mt-1">
                      Не заполнено: {summary.missing_recommended.join(", ")}
                    </p>
                  )}
                </div>
              </div>
            </Card>
          )}

          <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-1">
              <CardHeader
                title="Данные бизнеса"
                description="Эти величины вводятся вручную: с сайта их получить нельзя"
              />

              <div className="flex flex-col gap-4">
                <p className="text-micro text-text-secondary tracking-wide uppercase">
                  Обязательно
                </p>
                {REQUIRED_FIELDS.map((field) => (
                  <Input
                    key={field.key}
                    label={field.label}
                    hint={field.hint}
                    inputMode="decimal"
                    value={draft[field.key] ?? ""}
                    onChange={(e) => setDraft((d) => ({ ...d, [field.key]: e.target.value }))}
                  />
                ))}

                <p className="text-micro text-text-secondary mt-2 tracking-wide uppercase">
                  Желательно
                </p>
                {RECOMMENDED_FIELDS.map((field) => (
                  <Input
                    key={field.key}
                    label={field.label}
                    hint={field.hint}
                    inputMode="decimal"
                    value={draft[field.key] ?? ""}
                    onChange={(e) => setDraft((d) => ({ ...d, [field.key]: e.target.value }))}
                  />
                ))}

                <p className="text-micro text-text-secondary mt-2 tracking-wide uppercase">
                  Для прогноза заявок
                </p>
                {FORECAST_FIELDS.map((field) => (
                  <Input
                    key={field.key}
                    label={field.label}
                    hint={field.hint}
                    inputMode="decimal"
                    value={draft[field.key] ?? ""}
                    onChange={(e) => setDraft((d) => ({ ...d, [field.key]: e.target.value }))}
                  />
                ))}

                <Button onClick={save} loading={saving} fullWidth className="mt-2">
                  Сохранить
                </Button>
              </div>
            </Card>

            <div className="flex flex-col gap-4 xl:col-span-2">
              <Card>
                <CardHeader
                  title="Пороговые значения"
                  description="Выше этих величин привлечение перестаёт окупаться"
                />
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <MetricCard
                    label="Валовая прибыль со сделки"
                    metric={summary?.gross_profit_per_sale}
                    money
                  />
                  <MetricCard label="Безубыточный CAC" metric={summary?.break_even_cac} money />
                  <MetricCard label="Безубыточный CPL" metric={summary?.break_even_cpl} money />
                </div>
              </Card>

              <Card>
                <CardHeader
                  title="Цели"
                  description="К каким значениям стремимся при текущих вводных"
                />
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <MetricCard label="Целевой CAC" metric={summary?.target_cac} money />
                  <MetricCard label="Целевой CPL" metric={summary?.target_cpl} money />
                  <MetricCard label="Целевой ROAS" metric={summary?.target_roas} />
                </div>
              </Card>

              <Card>
                <CardHeader
                  title="Ожидаемый поток"
                  description="Сколько заявок будет при вашей цене клика и конверсии страницы"
                />
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <MetricCard label="Кликов в месяц" metric={summary?.expected_monthly_clicks} />
                  <MetricCard label="Заявок в месяц" metric={summary?.expected_monthly_leads} />
                </div>
              </Card>

              <Card>
                <CardHeader
                  title="Ёмкость бюджета"
                  /* Формулировка правится намеренно. «Лидов в месяц» читалось
                     как прогноз, хотя это верхняя граница: столько получится,
                     только если цена заявки окажется целевой. На старте она
                     почти всегда выше, и разница определяет, окупится кампания
                     или нет. */
                  description="Верхняя граница: столько получится, если цена окажется целевой"
                />
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <MetricCard
                    label="Заявок при целевой цене"
                    metric={summary?.monthly_leads_capacity}
                  />
                  <MetricCard label="Продаж в месяц" metric={summary?.monthly_sales_capacity} />
                  <MetricCard label="Прогноз выручки" metric={summary?.projected_revenue} money />
                </div>
              </Card>
            </div>
          </section>
        </>
      )}
    </AppShell>
  );
}

/**
 * Карточка метрики.
 *
 * Достоверность приходит с backend и отображается теми же состояниями, что и на
 * дашборде: «оценка» для величин, посчитанных с допущением, и «нет данных» там,
 * где считать не из чего. Правдоподобное число вместо пробела здесь было бы
 * опаснее всего — на него будут опираться при решениях о деньгах.
 */
function MetricCard({
  label,
  metric,
  money = false,
}: {
  label: string;
  metric: MetricRead | undefined;
  money?: boolean;
}) {
  if (!metric) {
    return <KpiCard label={label} value="" loading />;
  }

  const numeric = metric.value === null ? null : Number(metric.value);

  return (
    <KpiCard
      label={label}
      value={
        numeric === null
          ? "—"
          : money
            ? formatCurrency(numeric)
            : formatNumber(Math.round(numeric * 100) / 100)
      }
      availability={metric.availability}
      availabilityHint={metric.reason ?? undefined}
    />
  );
}

function toDraft(response: EconomicsResponse): Partial<Record<FieldKey, string>> {
  const input = response.input;
  if (!input) return {};
  const entries: [FieldKey, string][] = [];
  for (const key of [
    "monthly_budget",
    "average_order_value",
    "margin_percent",
    "lead_to_sale_rate",
    "target_cac",
    "target_cpl",
  ] as FieldKey[]) {
    const value = (input as Record<string, unknown>)[key];
    if (value !== null && value !== undefined) entries.push([key, String(value)]);
  }
  return Object.fromEntries(entries) as Partial<Record<FieldKey, string>>;
}

function toPayload(draft: Partial<Record<FieldKey, string>>): EconomicsUpdate {
  const payload: Record<string, string | null> = {};
  for (const [key, value] of Object.entries(draft)) {
    // Пустое поле означает «не задано», а не ноль: разница принципиальная,
    // нулевая маржа и незаполненная маржа — разные состояния.
    payload[key] = value && value.trim() !== "" ? value.trim() : null;
  }
  payload.main_conversion = "lead";
  return payload as EconomicsUpdate;
}
