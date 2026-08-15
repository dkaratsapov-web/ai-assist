"use client";

import { useState } from "react";
import {
  AiAvatar,
  AlertCard,
  Button,
  Card,
  CardHeader,
  ChatComposer,
  ConfirmationDialog,
  Drawer,
  IntegrationCard,
  KpiCard,
  LineChart,
  WorkflowStepper,
  RecommendationCard,
  formatCurrency,
  formatNumber,
} from "@ads-os/ui";
import { IconArrowRight, IconChart, IconPlug, IconTarget, IconUsers } from "@ads-os/ui/icons";
import { AppShell } from "@/components/AppShell";
import {
  chartLabels,
  chartSeriesData,
  chatSuggestions,
  demoNow,
  integrations,
  kpis,
  notifications,
  recommendations,
  workflowSteps,
  type RecommendationData,
} from "@/lib/mock-data";

const integrationIcons: Record<string, React.ReactNode> = {
  direct: <IconTarget size={22} />,
  metrica: <IconChart size={22} />,
  crm: <IconUsers size={22} />,
  telegram: <IconPlug size={22} />,
  max: <IconPlug size={22} />,
};

/**
 * Главный дашборд (v0.3 §125).
 *
 * Отвечает на три вопроса: что происходит, что требует внимания, что делать
 * дальше — и умещается в полтора экрана десктопа.
 *
 * Данные пока приходят из mock-модуля, но поток «рекомендация → подробности →
 * согласование» собран целиком: именно он, а не таблицы, является сутью
 * продукта, и проверять его на макете бессмысленно.
 */
export default function DashboardPage() {
  const [detailsFor, setDetailsFor] = useState<RecommendationData | null>(null);
  const [confirmFor, setConfirmFor] = useState<RecommendationData | null>(null);
  const [applying, setApplying] = useState(false);

  const handleApply = (recommendation: RecommendationData) => {
    // Рискованное действие никогда не выполняется по одному нажатию: сначала
    // показывается точный состав изменения (v0.3 §88, §113).
    if (recommendation.requiresApproval) {
      setConfirmFor(recommendation);
      return;
    }
    setApplying(true);
    window.setTimeout(() => setApplying(false), 900);
  };

  return (
    <AppShell
      title="Добро пожаловать, Иван"
      subtitle="AI-помощник по контекстной рекламе"
      notifications={3}
    >
      {/* ── Уровень 1: KPI ─────────────────────────────────────────────── */}
      <section aria-labelledby="kpi-heading">
        <h2 id="kpi-heading" className="sr-only">
          Ключевые показатели по всем проектам
        </h2>
        {/* Пять колонок только на действительно широких экранах: на 1440 пять
            карточек ломают значение на две строки, а KPI должен читаться
            одним взглядом. */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-6 2xl:grid-cols-5">
          {kpis.map((kpi, index) => (
            <KpiCard
              key={kpi.key}
              className={
                index < 3 ? "lg:col-span-2 2xl:col-span-1" : "lg:col-span-3 2xl:col-span-1"
              }
              label={kpi.label}
              value={kpi.value}
              delta={kpi.delta}
              polarity={kpi.polarity}
              period="за 7 дней"
              trend={kpi.trend}
              seriesColor={kpi.seriesColor}
            />
          ))}
        </div>
      </section>

      {/* ── Уровень 2: динамика и рекомендации ─────────────────────────── */}
      <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader
            title="Динамика за 7 дней"
            action={
              <Button variant="ghost" size="sm" iconRight={<IconArrowRight size={16} />}>
                Подробнее
              </Button>
            }
          />
          <LineChart
            series={chartSeriesData.map((series) => ({
              ...series,
              format: (value: number) =>
                series.axis === "left" ? formatCurrency(value) : formatNumber(value),
            }))}
            labels={chartLabels}
            caption="Расходы в рублях (левая ось), лиды и продажи в штуках (правая ось) по дням за последние 7 дней"
          />
        </Card>

        <Card>
          <CardHeader
            title="AI-рекомендации"
            action={
              <Button variant="ghost" size="sm" iconRight={<IconArrowRight size={16} />}>
                Все 12
              </Button>
            }
          />
          <div className="flex flex-col gap-2">
            {recommendations.map((recommendation) => (
              <RecommendationCard
                key={recommendation.id}
                level={recommendation.level}
                title={recommendation.title}
                reason={recommendation.reason}
                reasons={recommendation.reasons}
                createdAt={recommendation.createdAt}
                now={demoNow}
                requiresApproval={recommendation.requiresApproval}
                applying={applying}
                onApply={() => handleApply(recommendation)}
                onDetails={() => setDetailsFor(recommendation)}
              />
            ))}
          </div>
        </Card>
      </section>

      {/* ── Уровень 3: цепочка этапов проекта ──────────────────────────── */}
      <section>
        <Card>
          <CardHeader
            title="Логическая цепочка работы с проектом"
            description="Apple Service Тверь"
          />
          <WorkflowStepper steps={workflowSteps} className="scrollbar-slim" />
        </Card>
      </section>

      {/* ── Нижний уровень ─────────────────────────────────────────────── */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader
            title="Интеграции"
            action={
              <span className="text-caption text-text-secondary">
                {integrations.filter((item) => item.status === "connected").length} из{" "}
                {integrations.length}
              </span>
            }
          />
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-3">
            {integrations.map((integration) => (
              <IntegrationCard
                key={integration.key}
                name={integration.name}
                status={integration.status}
                icon={integrationIcons[integration.key]}
              />
            ))}
          </div>
        </Card>

        <Card>
          <CardHeader title="AI-помощник" />
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <AiAvatar size={52} />
              <p className="text-caption text-text-secondary">
                Задайте вопрос по проектам — отвечу по данным, а не догадками.
              </p>
            </div>
            <ChatComposer
              onSubmit={() => undefined}
              projectContext="Apple Service Тверь"
              suggestions={chatSuggestions.slice(0, 2)}
            />
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Уведомления"
            action={
              <Button variant="ghost" size="sm" iconRight={<IconArrowRight size={16} />}>
                Все 3
              </Button>
            }
          />
          <div className="divide-border flex flex-col divide-y">
            {notifications.map((notification) => (
              <AlertCard
                key={notification.id}
                level={notification.level}
                message={notification.message}
                createdAt={notification.createdAt}
                now={demoNow}
                onClick={() => undefined}
              />
            ))}
          </div>
        </Card>
      </section>

      {/* ── Подробности рекомендации ───────────────────────────────────── */}
      <Drawer
        open={detailsFor !== null}
        onClose={() => setDetailsFor(null)}
        title={detailsFor?.title ?? ""}
        description="Основание, метрики и ожидаемый эффект"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDetailsFor(null)}>
              Закрыть
            </Button>
            {detailsFor && (
              <Button
                onClick={() => {
                  const target = detailsFor;
                  setDetailsFor(null);
                  handleApply(target);
                }}
              >
                {detailsFor.requiresApproval ? "На согласование" : "Применить"}
              </Button>
            )}
          </>
        }
      >
        {detailsFor && (
          <div className="flex flex-col gap-6">
            <section>
              <h3 className="text-h3 mb-2">Что обнаружено</h3>
              <p className="text-body-sm text-text-secondary">{detailsFor.reason}</p>
            </section>

            <section>
              <h3 className="text-h3 mb-2">Основание</h3>
              <ul className="text-body-sm text-text-secondary flex list-none flex-col gap-1.5">
                {(detailsFor.reasons ?? ["Данные кампании за последние 3 дня"]).map((item) => (
                  <li key={item} className="flex gap-2">
                    <span aria-hidden="true">•</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
              {/* Вывод AI всегда отделён от данных и от действия (v0.3 §140). */}
              <p className="text-caption text-text-secondary mt-3">
                Источник: отчёт по поисковым запросам, данные Метрики. Уверенность модели: средняя —
                рекомендуем проверить перед применением.
              </p>
            </section>
          </div>
        )}
      </Drawer>

      {/* ── Согласование действия ──────────────────────────────────────── */}
      <ConfirmationDialog
        open={confirmFor !== null}
        onClose={() => setConfirmFor(null)}
        onConfirm={() => setConfirmFor(null)}
        title="Отправить изменение на согласование"
        description="Действие затрагивает рекламный бюджет, поэтому выполняется только после подтверждения."
        changes={[
          { label: "Дневной бюджет кампании", before: "4 500 ₽", after: "3 800 ₽" },
          { label: "Активных ключевых фраз", before: "1 284", after: "1 160" },
        ]}
        affectedCount={124}
        affectedNoun={["ключевая фраза", "ключевые фразы", "ключевых фраз"]}
        confirmLabel="Отправить"
        ttlMs={5 * 60_000}
      >
        <p className="text-caption text-text-secondary">
          После подтверждения изменение попадёт в журнал и будет применено, когда согласование
          пройдёт проверку политик.
        </p>
      </ConfirmationDialog>
    </AppShell>
  );
}
