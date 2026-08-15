#!/usr/bin/env node
/**
 * Проверка контраста палитры по WCAG 2.1 AA (v0.3 §139, §150).
 *
 * Запускается в CI. Любая правка design-tokens.json, роняющая контраст ниже
 * порога, ломает сборку — это дешевле, чем ловить проблему на ревью макетов.
 *
 * Пороги:
 *   4.5:1 — обычный текст
 *   3.0:1 — крупный текст (>=18.66px bold / >=24px) и графические объекты
 *   отключённые элементы порогу не подчиняются (WCAG 1.4.3, 1.4.11)
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const { color } = JSON.parse(readFileSync(join(root, "design-tokens.json"), "utf8"));

const channel = (c) => {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
};

const luminance = (hex) => {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
};

const contrast = (a, b) => {
  const [la, lb] = [luminance(a), luminance(b)];
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
};

/**
 * CIE L*a*b* — нужен для различимости серий графиков.
 *
 * Коэффициент контраста WCAG для этой задачи не годится: он сравнивает только
 * яркость, поэтому фиолетовый и оранжевый одинаковой светлоты дают около 1.1,
 * хотя различаются очевидно. Правильная метрика — перцептивная разница ΔE.
 */
const lab = (hex) => {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => channel(parseInt(h.slice(i, i + 2), 16)));
  const x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047;
  const y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883;
  const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const [fx, fy, fz] = [f(x), f(y), f(z)];
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
};

const deltaE = (a, b) => {
  const [la, lb] = [lab(a), lab(b)];
  return Math.hypot(la[0] - lb[0], la[1] - lb[1], la[2] - lb[2]);
};

const TEXT = 4.5;
const GRAPHIC = 3.0;

/** [токен, фон, порог, описание] */
const checks = [
  ["text-primary", "bg", TEXT, "основной текст на белом"],
  ["text-primary", "bg-secondary", TEXT, "основной текст на вторичном фоне"],
  ["text-secondary", "bg", TEXT, "вторичный текст на белом"],
  ["text-secondary", "bg-secondary", TEXT, "вторичный текст на вторичном фоне"],
  ["text-inverse", "cta", TEXT, "текст на чёрной CTA-кнопке"],
  ["text-inverse", "surface-inverse", TEXT, "текст на инверсной поверхности"],

  ["success", "success-bg", TEXT, "текст бейджа «успех»"],
  ["warning", "warning-bg", TEXT, "текст бейджа «предупреждение»"],
  ["critical", "critical-bg", TEXT, "текст бейджа «критично»"],
  ["info", "info-bg", TEXT, "текст бейджа «информация»"],
  ["neutral", "neutral-bg", TEXT, "текст нейтрального бейджа"],

  ["success", "bg", TEXT, "статусный текст на белом"],
  ["warning", "bg", TEXT, "статусный текст на белом"],
  ["critical", "bg", TEXT, "статусный текст на белом"],
  ["info", "bg", TEXT, "статусный текст на белом"],

  // Декоративные border и border-strong порогу 3:1 не подчиняются: карточка
  // опознаётся по фону и тени. Проверяется только border-input — граница поля
  // ввода является единственным признаком контрола (WCAG 1.4.11).
  ["border-input", "bg", GRAPHIC, "граница поля ввода"],
  ["border-input", "bg-secondary", GRAPHIC, "граница поля ввода на вторичном фоне"],

  // Кольцо фокуса всегда рисуется со смещением наружу, поэтому лежит на фоне
  // страницы, а не на самом контроле. Значимая пара — focus/bg, не focus/cta.
  ["focus", "bg", GRAPHIC, "кольцо фокуса на белом"],
  ["focus", "bg-secondary", GRAPHIC, "кольцо фокуса на вторичном фоне"],

  ["chart-1", "bg", GRAPHIC, "серия графика 1"],
  ["chart-2", "bg", GRAPHIC, "серия графика 2"],
  ["chart-3", "bg", GRAPHIC, "серия графика 3"],
  ["chart-4", "bg", GRAPHIC, "серия графика 4"],
  ["chart-axis", "bg", GRAPHIC, "ось графика"],
  ["chart-1", "bg-secondary", GRAPHIC, "серия 1 на вторичном фоне"],
  ["chart-2", "bg-secondary", GRAPHIC, "серия 2 на вторичном фоне"],
  ["chart-3", "bg-secondary", GRAPHIC, "серия 3 на вторичном фоне"],
  ["chart-4", "bg-secondary", GRAPHIC, "серия 4 на вторичном фоне"],
];

/**
 * Серии графиков должны различаться между собой. Метрика — ΔE, а не WCAG:
 * см. комментарий к lab(). Порог 25 соответствует «различимо без усилий».
 * Это не отменяет требования v0.3 §139: у графиков всегда есть текстовые
 * значения и подсказки, цвет не является единственным носителем смысла.
 */
const seriesPairs = [
  ["chart-1", "chart-2"],
  ["chart-1", "chart-3"],
  ["chart-1", "chart-4"],
  ["chart-2", "chart-3"],
  ["chart-2", "chart-4"],
  ["chart-3", "chart-4"],
];
const SERIES_MIN_DELTA_E = 25;

const failures = [];
const rows = [];

for (const [fg, bg, min, label] of checks) {
  const ratio = contrast(color[fg], color[bg]);
  const ok = ratio >= min;
  if (!ok) failures.push(`${fg} на ${bg}: ${ratio.toFixed(2)} < ${min} (${label})`);
  rows.push(`  ${ok ? "✓" : "✗"} ${(fg + " / " + bg).padEnd(34)} ${ratio.toFixed(2).padStart(6)}  ≥${min}  ${label}`);
}

for (const [a, b] of seriesPairs) {
  const diff = deltaE(color[a], color[b]);
  const ok = diff >= SERIES_MIN_DELTA_E;
  if (!ok) {
    failures.push(`серии ${a} и ${b} перцептивно близки: ΔE ${diff.toFixed(1)} < ${SERIES_MIN_DELTA_E}`);
  }
  rows.push(
    `  ${ok ? "✓" : "✗"} ${(a + " / " + b).padEnd(34)} ${("ΔE " + diff.toFixed(0)).padStart(6)}  ≥${SERIES_MIN_DELTA_E}  различимость серий`,
  );
}

console.log("Контраст палитры (WCAG 2.1 AA) и различимость серий (ΔE):");
console.log(rows.join("\n"));

if (failures.length) {
  console.error(`\n✗ не пройдено проверок: ${failures.length}`);
  for (const f of failures) console.error(`  - ${f}`);
  console.error("\nИсправить значения в packages/tokens/design-tokens.json.");
  process.exit(1);
}

console.log(`\n✓ Все ${rows.length} проверок пройдены.`);
