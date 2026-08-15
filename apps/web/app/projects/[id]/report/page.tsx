"use client";

import { use, useEffect, useMemo, useState } from "react";
import type {
  ApiError,
  AuditRead,
  ComparisonRead,
  EconomicsResponse,
  LaunchPlanRead,
  ProgressRead,
  ProjectRead,
} from "@ads-os/schemas";
import { Button, ErrorState, Skeleton } from "@ads-os/ui";
import { createApiClient } from "@/lib/api";
import { toApiError } from "@/lib/errors";

/** Человеческие названия категорий аудита. Ключи приходят с backend. */
const CATEGORY_LABELS: Record<string, string> = {
  technical: "Техническое состояние",
  offer: "Предложение",
  conversion: "Конверсия",
  trust: "Доверие",
  tracking: "Аналитика",
};

const VERDICT_TEXT: Record<string, string> = {
  ready: "Можно запускать рекламу",
  ready_with_warnings: "Запускать можно, есть замечания",
  not_ready: "Запускать рано",
};

const SEVERITY_TEXT: Record<string, string> = {
  critical: "Критично",
  warning: "Важно",
  recommendation: "Стоит сделать",
  info: "К сведению",
};

const STEP_STATE_TEXT: Record<string, string> = {
  completed: "сделано",
  active: "в работе",
  waiting: "ждёт",
  blocked: "заблокировано",
  error: "ошибка",
};

interface Report {
  project: ProjectRead;
  progress: ProgressRead | null;
  audit: AuditRead | null;
  comparison: ComparisonRead | null;
  economics: EconomicsResponse | null;
  plan: LaunchPlanRead | null;
}

/**
 * Отчёт по проекту одной страницей.
 *
 * Отдельный экран без бокового меню и шапки: его открывают, чтобы распечатать
 * или сохранить в PDF и отдать клиенту. Всё, что не относится к содержанию
 * отчёта, при печати мешает.
 *
 * Данные собираются из тех же эндпоинтов, что и обычные экраны. Отдельного
 * «отчётного» API нет намеренно: он неизбежно разошёлся бы с тем, что человек
 * видит в интерфейсе, и отчёт перестал бы совпадать с сервисом.
 */
export default function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const api = useMemo(() => createApiClient(), []);

  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let ignore = false;

    void (async () => {
      try {
        const project = await api.getProject(id);

        // Разделы отчёта независимы: если конкурентов не добавляли, а экономику
        // не заполняли, отчёт всё равно должен собраться — просто без этих
        // разделов. Поэтому каждый запрос гасит свою ошибку сам.
        const [progress, audit, comparison, economics, plan] = await Promise.all([
          api.getProgress(id).catch(() => null),
          api.getAudit(id).catch(() => null),
          api.getComparison(id).catch(() => null),
          api.getEconomics(id).catch(() => null),
          api.getStrategy(id).catch(() => null),
        ]);

        if (ignore) return;
        setReport({ project, progress, audit, comparison, economics, plan });
      } catch (err) {
        if (!ignore) setError(toApiError(err));
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api, id]);

  if (error) {
    return (
      <main className="bg-bg mx-auto max-w-3xl p-6">
        <ErrorState title="Не удалось собрать отчёт" description={error.message} />
      </main>
    );
  }

  if (!report) {
    return (
      <main className="bg-bg mx-auto flex max-w-3xl flex-col gap-4 p-6">
        <Skeleton shape="card" />
        <Skeleton shape="card" />
      </main>
    );
  }

  const { project, progress, audit, comparison, economics, plan } = report;
  const gaps = (comparison?.rows ?? []).filter((row) => row.is_gap);

  return (
    <main className="bg-bg text-text-primary mx-auto max-w-3xl p-6 print:max-w-none print:p-0">
      <header className="border-border mb-6 flex items-start justify-between gap-4 border-b pb-4">
        <div>
          <h1 className="text-h2">{project.name}</h1>
          <p className="text-body-sm text-text-secondary">
            Отчёт о готовности к запуску рекламы · {formatDate(new Date().toISOString())}
          </p>
          {project.website_url && (
            <p className="text-body-sm text-text-secondary break-all">{project.website_url}</p>
          )}
        </div>
        {/* Кнопка прячется при печати: в бумажном отчёте она бессмысленна. */}
        <Button size="sm" className="print:hidden" onClick={() => window.print()}>
          Печать или PDF
        </Button>
      </header>

      {progress && (
        <Section title="Готовность к запуску">
          <p className="text-body-sm text-text-secondary mb-2">
            Пройдено шагов: {progress.completed_count} из {progress.total_count}
            {progress.next_action && ` · дальше: ${progress.next_action}`}
          </p>
          <ul className="flex flex-col gap-1">
            {progress.steps.map((step) => (
              <li key={step.key} className="text-body-sm flex justify-between gap-3">
                <span>{step.label}</span>
                <span className="text-text-secondary shrink-0">
                  {STEP_STATE_TEXT[step.state] ?? step.state}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {audit && audit.status === "completed" && (
        <Section title="Сайт">
          <p className="text-body-sm mb-2">
            Оценка готовности: <strong>{audit.score ?? "—"} из 100</strong>
            {audit.verdict && ` · ${VERDICT_TEXT[audit.verdict] ?? audit.verdict}`}
          </p>
          <p className="text-body-sm text-text-secondary mb-3">
            Проверено {formatDate(audit.finished_at ?? audit.created_at)}
            {audit.metrica_counter
              ? ` · счётчик Метрики ${audit.metrica_counter}`
              : " · счётчик Метрики не найден"}
          </p>

          {audit.categories.length > 0 && (
            <ul className="mb-3 flex flex-col gap-1">
              {audit.categories.map((category) => (
                <li key={category.category} className="text-body-sm flex justify-between gap-3">
                  <span>{CATEGORY_LABELS[category.category] ?? category.category}</span>
                  <span className="text-text-secondary shrink-0 tabular-nums">
                    {category.score}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {reportIssues(audit).length > 0 && (
            <>
              <h3 className="text-body-sm mb-1 font-medium">Что исправить</h3>
              <ul className="flex flex-col gap-2">
                {reportIssues(audit).map((issue, index) => (
                  <li key={`${issue.title}-${index}`} className="text-body-sm">
                    <span className="text-text-secondary">
                      {SEVERITY_TEXT[issue.severity] ?? issue.severity}:{" "}
                    </span>
                    {issue.title}
                    <span className="text-text-secondary block">{issue.action}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Section>
      )}

      {comparison && comparison.rivals_checked > 0 && (
        <Section title="Конкуренты">
          <p className="text-body-sm text-text-secondary mb-2">
            Проверено конкурентов: {comparison.rivals_checked}
            {!comparison.own_site_checked && " · свой сайт не проверялся, сравнение неполное"}
          </p>
          {comparison.summary && <p className="text-body-sm mb-3">{comparison.summary}</p>}
          {gaps.length > 0 && (
            <>
              <h3 className="text-body-sm mb-1 font-medium">Чего нет у вас, а у них есть</h3>
              <ul className="flex flex-col gap-1">
                {gaps.map((row) => (
                  <li key={row.key} className="text-body-sm">
                    {row.label}
                    <span className="text-text-secondary">
                      {" "}
                      — есть у {row.rivals_with} из {row.rivals_total}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Section>
      )}

      {economics && (
        <Section title="Экономика">
          {economics.summary.missing_required.length > 0 && (
            <p className="text-body-sm text-text-secondary mb-2">
              Расчёт неполный: не хватает данных ({economics.summary.missing_required.join(", ")}).
            </p>
          )}
          <ul className="flex flex-col gap-1">
            <MetricLine
              label="Прибыль с продажи"
              metric={economics.summary.gross_profit_per_sale}
            />
            <MetricLine label="Предельная цена лида" metric={economics.summary.break_even_cpl} />
            <MetricLine label="Предельная цена клиента" metric={economics.summary.break_even_cac} />
            <MetricLine
              label="Точка окупаемости, ROAS"
              metric={economics.summary.break_even_roas}
            />
            <MetricLine label="Лидов в месяц" metric={economics.summary.monthly_leads_capacity} />
            <MetricLine label="Продаж в месяц" metric={economics.summary.monthly_sales_capacity} />
            <MetricLine
              label="Ожидаемая прибыль"
              metric={economics.summary.projected_gross_profit}
            />
          </ul>
        </Section>
      )}

      {plan && (
        <Section title="План запуска">
          {plan.blockers.length > 0 ? (
            <ul className="flex flex-col gap-1">
              {plan.blockers.map((blocker) => (
                <li key={blocker} className="text-body-sm">
                  {blocker}
                </li>
              ))}
            </ul>
          ) : (
            <>
              {plan.strategy_label && (
                <p className="text-body-sm mb-1">
                  Стратегия на старте: <strong>{plan.strategy_label}</strong>
                </p>
              )}
              <p className="text-body-sm text-text-secondary mb-2">{plan.strategy_reason}</p>
              <ul className="flex flex-col gap-1">
                {plan.weekly_conversions !== null && (
                  <li className="text-body-sm flex justify-between gap-3">
                    <span>Заявок в неделю</span>
                    <span className="text-text-secondary shrink-0 tabular-nums">
                      {plan.weekly_conversions}
                    </span>
                  </li>
                )}
                <li className="text-body-sm flex justify-between gap-3">
                  <span>До первых выводов</span>
                  <span className="text-text-secondary shrink-0 tabular-nums">
                    {plan.test_weeks !== null
                      ? `${plan.test_weeks} нед.`
                      : "объёма мало, ждать пришлось бы слишком долго"}
                  </span>
                </li>
                {plan.test_budget !== null && (
                  <li className="text-body-sm flex justify-between gap-3">
                    <span>Бюджет теста</span>
                    <span className="text-text-secondary shrink-0 tabular-nums">
                      {plan.test_budget} ₽
                    </span>
                  </li>
                )}
              </ul>
            </>
          )}
        </Section>
      )}

      <footer className="text-caption text-text-secondary border-border mt-6 border-t pt-4">
        Отчёт составлен автоматически по данным сервиса на {formatDate(new Date().toISOString())}.
        Значения, помеченные как приблизительные, рассчитаны по неполным данным.
      </footer>
    </main>
  );
}

/**
 * Замечания для клиентского отчёта.
 *
 * Отмеченные неактуальными не попадают: для клиента это решение уже принято, и
 * строка «цен нет, но мы решили, что это неважно» в отчёте только вызывает
 * вопрос, на который отчёт не отвечает.
 */
function reportIssues(audit: AuditRead) {
  return audit.issues.filter((issue) => !issue.dismissed);
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    // break-inside-avoid не даёт разделу разорваться между страницами при печати.
    <section className="mb-6 print:break-inside-avoid">
      <h2 className="text-body mb-2 font-medium">{title}</h2>
      {children}
    </section>
  );
}

function MetricLine({
  label,
  metric,
}: {
  label: string;
  metric: { value: string | null; availability: string };
}) {
  return (
    <li className="text-body-sm flex justify-between gap-3">
      <span>{label}</span>
      <span className="text-text-secondary shrink-0 tabular-nums">
        {metric.value ?? "—"}
        {/* «Приблизительно» пишется словом рядом со значением, а не сноской:
            в распечатанном отчёте сноску никто не сопоставит с числом. */}
        {metric.availability === "proxy" && " (приблизительно)"}
      </span>
    </li>
  );
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}
