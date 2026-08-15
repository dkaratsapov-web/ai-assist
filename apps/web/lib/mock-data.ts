import type { SeverityKey, WorkflowStepStateKey } from "@ads-os/tokens";
import { lifecycleSteps } from "@ads-os/tokens";
import type { ProjectStatusKey, IntegrationStatusKey } from "@ads-os/tokens";

/**
 * Демонстрационные данные.
 *
 * Соответствуют demo-проекту из v0.3 §76: ремонт техники Apple, регион Тверь.
 * Все значения синтетические — реальные рекламные кабинеты не подключены и до
 * прохождения Security Acceptance Criteria подключены не будут (v0.4 §2.1).
 *
 * Файл существует ровно до появления настоящего API: страницы уже сейчас
 * написаны так, будто данные приходят снаружи, поэтому замена источника не
 * потребует переписывания разметки.
 */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

/** Фиксированная «сейчас», чтобы демо выглядело одинаково при каждой сборке. */
export const demoNow = new Date("2026-05-07T12:00:00Z");

/* ── KPI ───────────────────────────────────────────────────────────────────── */

export interface KpiData {
  key: string;
  label: string;
  value: string;
  delta: number;
  polarity: "up-is-good" | "up-is-bad" | "neutral";
  trend: number[];
  seriesColor: string;
}

export const kpis: KpiData[] = [
  {
    key: "spend",
    label: "Расходы",
    value: "142 750 ₽",
    delta: 12,
    // Рост расходов сам по себе не хорош и не плох — он оценивается только
    // вместе с отдачей, поэтому окраска нейтральная.
    polarity: "neutral",
    trend: [88, 96, 91, 104, 99, 118, 131, 142],
    seriesColor: "var(--color-chart-1)",
  },
  {
    key: "leads",
    label: "Лиды",
    value: "267",
    delta: 18,
    polarity: "up-is-good",
    trend: [180, 195, 188, 214, 221, 238, 251, 267],
    seriesColor: "var(--color-chart-2)",
  },
  {
    key: "cpl",
    label: "CPL",
    value: "535 ₽",
    delta: -7,
    polarity: "up-is-bad",
    trend: [612, 598, 604, 578, 566, 551, 542, 535],
    seriesColor: "var(--color-chart-4)",
  },
  {
    key: "sales",
    label: "Продажи",
    value: "58",
    delta: 11,
    polarity: "up-is-good",
    trend: [38, 41, 44, 46, 49, 52, 55, 58],
    seriesColor: "var(--color-chart-3)",
  },
  {
    key: "revenue",
    label: "Выручка",
    value: "695 200 ₽",
    delta: 15,
    polarity: "up-is-good",
    trend: [452, 478, 501, 534, 578, 612, 655, 695],
    seriesColor: "var(--color-chart-1)",
  },
];

/* ── График динамики ───────────────────────────────────────────────────────── */

export const chartLabels = ["01.05", "02.05", "03.05", "04.05", "05.05", "06.05", "07.05"];

/**
 * Серии графика.
 *
 * Референс дашборда показывает Расходы, Лиды и Продажи на одной оси. Буквально
 * так построить нельзя: 267 лидов на шкале до 200 000 ₽ превращаются в прямую
 * линию у нижнего края. Поэтому денежная метрика привязана к левой оси, а
 * количественные — к правой.
 */
export const chartSeriesData = [
  {
    key: "spend",
    label: "Расходы, ₽",
    color: "var(--color-chart-1)",
    axis: "left" as const,
    values: [88_400, 96_100, 91_300, 104_800, 99_200, 118_600, 142_750],
  },
  {
    key: "leads",
    label: "Лиды, шт",
    color: "var(--color-chart-2)",
    axis: "right" as const,
    values: [180, 195, 188, 214, 221, 238, 267],
  },
  {
    key: "sales",
    label: "Продажи, шт",
    color: "var(--color-chart-3)",
    axis: "right" as const,
    values: [38, 41, 44, 46, 49, 52, 58],
  },
];

/* ── AI-рекомендации ───────────────────────────────────────────────────────── */

export interface RecommendationData {
  id: string;
  level: SeverityKey;
  title: string;
  reason: string;
  reasons?: string[];
  createdAt: Date;
  requiresApproval: boolean;
}

export const recommendations: RecommendationData[] = [
  {
    id: "rec-1",
    level: "critical",
    title: "Рост CPL в кампании «Ремонт iPhone»",
    reason: "CPL вырос на 32% за 3 дня.",
    reasons: ["нерелевантные поисковые запросы", "снижение конверсии посадочной страницы"],
    createdAt: new Date(demoNow.getTime() - 10 * MINUTE),
    // Изменение ставок и отключение ключей затрагивает деньги — только через
    // согласование (v0.4 §10: всё, кроме чтения, по умолчанию требует approval).
    requiresApproval: true,
  },
  {
    id: "rec-2",
    level: "warning",
    title: "Добавить минус-фразы",
    reason: "Найдено 124 нерелевантных запроса, которые расходуют бюджет впустую.",
    createdAt: new Date(demoNow.getTime() - HOUR),
    requiresApproval: true,
  },
  {
    id: "rec-3",
    level: "recommendation",
    title: "Протестировать новый креатив",
    reason: "CTR может вырасти примерно на 18% по текущим данным.",
    createdAt: new Date(demoNow.getTime() - 3 * HOUR),
    requiresApproval: false,
  },
];

/* ── Цепочка этапов проекта ────────────────────────────────────────────────── */

/** Состояния демо-проекта по канону из v0.4 §3. */
const stepStates: WorkflowStepStateKey[] = [
  "completed",
  "completed",
  "completed",
  "completed",
  "active",
  "waiting",
  "waiting",
  "waiting",
  "waiting",
  "waiting",
];

export const workflowSteps = lifecycleSteps.map((step, index) => ({
  key: step.key,
  label: step.label,
  description: step.description,
  state: stepStates[index] ?? "waiting",
}));

/* ── Интеграции ────────────────────────────────────────────────────────────── */

export interface IntegrationData {
  key: string;
  name: string;
  status: IntegrationStatusKey;
}

export const integrations: IntegrationData[] = [
  { key: "direct", name: "Яндекс Директ", status: "connected" },
  { key: "metrica", name: "Яндекс Метрика", status: "connected" },
  { key: "crm", name: "AmoCRM", status: "connected" },
  { key: "telegram", name: "Telegram", status: "connected" },
  { key: "max", name: "MAX", status: "disconnected" },
];

/* ── Уведомления ───────────────────────────────────────────────────────────── */

export interface NotificationData {
  id: string;
  level: SeverityKey;
  message: string;
  createdAt: Date;
}

export const notifications: NotificationData[] = [
  {
    id: "n-1",
    level: "critical",
    message: "Рост CPL в кампании «Ремонт iPhone»",
    createdAt: new Date(demoNow.getTime() - 10 * MINUTE),
  },
  {
    id: "n-2",
    level: "warning",
    message: "Добавить минус-фразы",
    createdAt: new Date(demoNow.getTime() - HOUR),
  },
  {
    id: "n-3",
    level: "recommendation",
    message: "Протестировать новый креатив",
    createdAt: new Date(demoNow.getTime() - 3 * HOUR),
  },
];

/* ── Проекты ───────────────────────────────────────────────────────────────── */

export interface ProjectData {
  id: string;
  name: string;
  status: ProjectStatusKey;
  spend: number;
  leads: number;
  cpl: number;
  trend: number[];
}

export const projects: ProjectData[] = [
  {
    id: "apple-service-tver",
    name: "Apple Service Тверь",
    status: "active",
    spend: 142_750,
    leads: 267,
    cpl: 535,
    trend: [88, 96, 91, 104, 99, 118, 131, 142],
  },
  {
    id: "iphone-repair-msk",
    name: "Ремонт iPhone Москва",
    status: "active",
    spend: 98_320,
    leads: 163,
    cpl: 602,
    trend: [62, 71, 68, 78, 84, 88, 93, 98],
  },
  {
    id: "iphone-parts-spb",
    name: "Запчасти iPhone СПб",
    status: "paused",
    spend: 56_410,
    leads: 74,
    cpl: 762,
    trend: [48, 52, 55, 54, 56, 56, 56, 56],
  },
  {
    id: "trade-in-iphone",
    name: "Trade-in iPhone",
    status: "draft",
    spend: 0,
    leads: 0,
    cpl: 0,
    trend: [0, 0, 0, 0, 0, 0, 0, 0],
  },
];

/** Подсказки для пустого состояния AI-чата (v0.3 §135). */
export const chatSuggestions = [
  "Почему вырос CPL?",
  "Что сегодня требует внимания?",
  "Покажи нецелевые запросы",
  "Какие гипотезы стоит протестировать?",
];
