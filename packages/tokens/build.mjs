#!/usr/bin/env node
/**
 * Генерирует из design-tokens.json:
 *   dist/tokens.css — CSS-переменные в @theme-блоке Tailwind v4
 *   dist/tokens.ts  — типизированные константы для Web и сообщений ботов
 *
 * Пайплайн зафиксирован в v0.4 §19:
 *   design-tokens.json → CSS variables → Tailwind theme → компоненты → bot constants
 *
 * Правка сгенерированных файлов бессмысленна — они перезаписываются.
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const src = join(root, "design-tokens.json");
const outDir = join(root, "dist");

const tokens = JSON.parse(readFileSync(src, "utf8"));

const BANNER = `/**
 * СГЕНЕРИРОВАННЫЙ ФАЙЛ — не редактировать.
 * Источник: packages/tokens/design-tokens.json
 * Пересборка: pnpm tokens
 */`;

/** Плоские группы «ключ → значение», попадающие в @theme как есть. */
const THEME_GROUPS = [
  ["color", "--color-"],
  ["font", "--font-"],
  ["fontWeight", "--font-weight-"],
  ["container", "--container-"],
  ["radius", "--radius-"],
  ["shadow", "--shadow-"],
  ["ease", "--ease-"],
  ["breakpoint", "--breakpoint-"],
];

/**
 * Группы, которые в тему Tailwind не попадают — просто CSS-переменные.
 *
 * Шкала отступов намеренно живёт здесь, а не в @theme. Её имена (sm, md, lg…)
 * совпадают с размерной шкалой Tailwind, и `--spacing-md: 16px` молча
 * превращал `max-w-md` в 16 пикселей — модальное окно схлопывалось в узкую
 * полосу. Сетка 4/8/12/16/24/32/48 из v0.3 §121 и так совпадает с числовой
 * шкалой Tailwind (p-1, p-2, p-3, p-4, p-6, p-8, p-12), поэтому в разметке
 * используется она, а эти переменные остаются для документации и для
 * потребителей вне Tailwind — например, для конструктора сообщений ботов.
 */
const ROOT_GROUPS = [
  ["spacing", "--space-"],
  ["duration", "--duration-"],
  ["z", "--z-"],
  ["layout", "--layout-"],
];

function emitFlat(group, prefix) {
  const entries = tokens[group];
  if (!entries) return [];
  return Object.entries(entries).map(([key, value]) => `  ${prefix}${key}: ${value};`);
}

function emitTypography() {
  const lines = [];
  for (const [key, spec] of Object.entries(tokens.text)) {
    lines.push(`  --text-${key}: ${spec.size};`);
    lines.push(`  --text-${key}--line-height: ${spec.lineHeight};`);
    lines.push(`  --text-${key}--font-weight: ${spec.weight};`);
    if (spec.tracking && spec.tracking !== "0") {
      lines.push(`  --text-${key}--letter-spacing: ${spec.tracking};`);
    }
  }
  return lines;
}

function buildCss() {
  const themeLines = [];
  for (const [group, prefix] of THEME_GROUPS) {
    const lines = emitFlat(group, prefix);
    if (lines.length) themeLines.push(`  /* ${group} */`, ...lines, "");
  }
  themeLines.push("  /* typography */", ...emitTypography());

  const rootLines = [];
  for (const [group, prefix] of ROOT_GROUPS) {
    const lines = emitFlat(group, prefix);
    if (lines.length) rootLines.push(`  /* ${group} */`, ...lines, "");
  }

  return [
    BANNER.replace(/^\/\*\*/, "/*").replace(/ \* /g, " * "),
    "",
    "@theme {",
    ...themeLines,
    "}",
    "",
    ":root {",
    ...rootLines.slice(0, -1),
    "}",
    "",
  ].join("\n");
}

function buildTs() {
  const json = JSON.stringify(tokens, null, 2);
  return `${BANNER}

export const tokens = ${json} as const;

/** Смысловая окраска элемента. Цвет никогда не единственный носитель смысла (v0.3 §139). */
export type Tone = "success" | "warning" | "critical" | "info" | "neutral";

export const color = tokens.color;
export const severity = tokens.vocabulary.severity;
export const workflowStepState = tokens.vocabulary.workflowStepState;
export const projectStatus = tokens.vocabulary.projectStatus;
export const moduleStatus = tokens.vocabulary.moduleStatus;
export const integrationStatus = tokens.vocabulary.integrationStatus;
export const metricAvailability = tokens.vocabulary.metricAvailability;
export const lifecycleSteps = tokens.vocabulary.lifecycle.steps;

export type SeverityKey = keyof typeof severity;
export type WorkflowStepStateKey = keyof typeof workflowStepState;
export type ProjectStatusKey = keyof typeof projectStatus;
export type ModuleStatusKey = keyof typeof moduleStatus;
export type IntegrationStatusKey = keyof typeof integrationStatus;
export type MetricAvailabilityKey = "available" | "proxy" | "unavailable";
export type LifecycleStepKey = (typeof lifecycleSteps)[number]["key"];

/** Порядок серий графиков. Одна метрика — один цвет во всём продукте (v0.4 §19). */
export const chartSeries = [
  tokens.color["chart-1"],
  tokens.color["chart-2"],
  tokens.color["chart-3"],
  tokens.color["chart-4"],
] as const;
`;
}

mkdirSync(outDir, { recursive: true });
writeFileSync(join(outDir, "tokens.css"), buildCss(), "utf8");
writeFileSync(join(outDir, "tokens.ts"), buildTs(), "utf8");

const count = THEME_GROUPS.concat(ROOT_GROUPS).reduce(
  (n, [g]) => n + Object.keys(tokens[g] ?? {}).length,
  Object.keys(tokens.text).length,
);
console.log(`tokens: сгенерировано ${count} токенов → dist/tokens.css, dist/tokens.ts`);
