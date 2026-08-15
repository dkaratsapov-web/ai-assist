"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { cn } from "../lib/cn";
import { formatCompact } from "../lib/format";

export interface ChartSeries {
  key: string;
  label: string;
  /** Цвет из палитры серий. Одна метрика — один цвет во всём продукте. */
  color: string;
  values: number[];
  /** Форматирование значения в подсказке и в текстовой альтернативе. */
  format?: (value: number) => string;
  /**
   * Ось, к которой привязана серия.
   *
   * Вторая ось нужна постоянно: расходы в рублях и лиды в штуках отличаются на
   * три порядка, и на общей шкале меньшая величина вырождается в прямую линию
   * у нижнего края — график перестаёт нести информацию.
   */
  axis?: "left" | "right";
}

export interface LineChartProps {
  series: ChartSeries[];
  /** Подписи оси X, по одной на точку. */
  labels: string[];
  height?: number;
  /** Заголовок для текстовой альтернативы. */
  caption: string;
  className?: string;
}

const GRID_LINES = 4;

/**
 * Линейный график с несколькими сериями.
 *
 * Написан на SVG без графической библиотеки: набор требований узкий (линии,
 * сетка, подсказка), а собственная реализация гарантирует, что цвета, шрифты и
 * тайминги берутся из токенов, а не из темы стороннего пакета.
 *
 * Доступность (v0.3 §139): под графиком выводится скрытая таблица со всеми
 * значениями, поэтому данные доступны и без восприятия цвета и формы.
 */
export function LineChart({ series, labels, height = 260, caption, className }: LineChartProps) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const clipId = useId();

  const { ref: containerRef, width } = useContainerWidth(720);

  const hasRightAxis = series.some((s) => s.axis === "right");
  const padding = { top: 12, right: hasRightAxis ? 52 : 12, bottom: 28, left: 48 };

  const plotWidth = Math.max(width - padding.left - padding.right, 0);
  const plotHeight = height - padding.top - padding.bottom;

  /** Своя шкала на каждую ось, иначе меньшая метрика вырождается в прямую. */
  const scales = useMemo(() => {
    const maxFor = (side: "left" | "right") => {
      const values = series.filter((s) => (s.axis ?? "left") === side).flatMap((s) => s.values);
      return values.length ? niceCeil(Math.max(...values, 0)) : 0;
    };
    return { left: maxFor("left"), right: maxFor("right") };
  }, [series]);

  const ticks = Array.from({ length: GRID_LINES + 1 }, (_, i) => i / GRID_LINES);

  const pointCount = labels.length;
  const xAt = (index: number) =>
    padding.left + (pointCount <= 1 ? plotWidth / 2 : (index / (pointCount - 1)) * plotWidth);
  const yAtRatio = (ratio: number) => padding.top + plotHeight - ratio * plotHeight;
  const yAt = (value: number, side: "left" | "right" = "left") =>
    yAtRatio(value / (scales[side] || 1));

  return (
    <figure className={cn("m-0 flex flex-col gap-3", className)}>
      <div className="flex flex-wrap items-center gap-4">
        {series.map((s) => (
          <span key={s.key} className="text-caption text-text-secondary flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="h-0.5 w-4 rounded-full"
              style={{ backgroundColor: s.color }}
            />
            {s.label}
          </span>
        ))}
      </div>

      <div className="relative" ref={containerRef}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width={width}
          height={height}
          className="max-w-full"
          role="img"
          aria-label={caption}
          onMouseLeave={() => setHoverIndex(null)}
        >
          <defs>
            <clipPath id={clipId}>
              <rect x={padding.left} y={0} width={plotWidth} height={height} />
            </clipPath>
          </defs>

          {ticks.map((ratio) => (
            <g key={ratio}>
              <line
                x1={padding.left}
                x2={width - padding.right}
                y1={yAtRatio(ratio)}
                y2={yAtRatio(ratio)}
                stroke="var(--color-chart-grid)"
                strokeWidth={1}
              />
              <text
                x={padding.left - 10}
                y={yAtRatio(ratio)}
                textAnchor="end"
                dominantBaseline="middle"
                className="fill-text-secondary"
                style={{ fontSize: 11 }}
              >
                {formatCompact(scales.left * ratio)}
              </text>
              {hasRightAxis && (
                <text
                  x={width - padding.right + 10}
                  y={yAtRatio(ratio)}
                  textAnchor="start"
                  dominantBaseline="middle"
                  className="fill-text-secondary"
                  style={{ fontSize: 11 }}
                >
                  {formatCompact(scales.right * ratio)}
                </text>
              )}
            </g>
          ))}

          {labels.map((label, index) => (
            <text
              key={`${label}-${index}`}
              x={xAt(index)}
              y={height - 8}
              textAnchor="middle"
              className="fill-text-secondary"
              style={{ fontSize: 11 }}
            >
              {label}
            </text>
          ))}

          {hoverIndex !== null && (
            <line
              x1={xAt(hoverIndex)}
              x2={xAt(hoverIndex)}
              y1={padding.top}
              y2={padding.top + plotHeight}
              stroke="var(--color-border-strong)"
              strokeWidth={1}
            />
          )}

          <g clipPath={`url(#${clipId})`}>
            {series.map((s) => (
              <path
                key={s.key}
                d={s.values
                  .map((v, i) => `${i === 0 ? "M" : "L"}${xAt(i)} ${yAt(v, s.axis ?? "left")}`)
                  .join(" ")}
                fill="none"
                stroke={s.color}
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ))}

            {series.map((s) =>
              s.values.map((v, i) => (
                <circle
                  key={`${s.key}-${i}`}
                  cx={xAt(i)}
                  cy={yAt(v, s.axis ?? "left")}
                  r={hoverIndex === i ? 4 : 2.5}
                  fill={s.color}
                />
              )),
            )}
          </g>

          {/* Прозрачные зоны наведения — по одной на точку. */}
          {labels.map((label, index) => (
            <rect
              key={`hit-${label}-${index}`}
              x={xAt(index) - plotWidth / Math.max(pointCount - 1, 1) / 2}
              y={0}
              width={plotWidth / Math.max(pointCount - 1, 1)}
              height={height}
              fill="transparent"
              onMouseEnter={() => setHoverIndex(index)}
            />
          ))}
        </svg>

        {hoverIndex !== null && (
          <ChartTooltip
            series={series}
            index={hoverIndex}
            label={labels[hoverIndex] ?? ""}
            position={xAt(hoverIndex) / width}
          />
        )}
      </div>

      {/* Текстовая альтернатива: те же данные без опоры на цвет и форму. */}
      <figcaption className="sr-only">
        <table>
          <caption>{caption}</caption>
          <thead>
            <tr>
              <th scope="col">Период</th>
              {series.map((s) => (
                <th key={s.key} scope="col">
                  {s.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {labels.map((label, index) => (
              <tr key={label}>
                <th scope="row">{label}</th>
                {series.map((s) => {
                  const value = s.values[index] ?? 0;
                  return <td key={s.key}>{s.format ? s.format(value) : formatCompact(value)}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </figcaption>
    </figure>
  );
}

function ChartTooltip({
  series,
  index,
  label,
  position,
}: {
  series: ChartSeries[];
  index: number;
  label: string;
  position: number;
}) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "bg-surface border-border shadow-overlay rounded-small-card pointer-events-none absolute top-4 border p-3",
        "min-w-44",
      )}
      style={{
        left: `${position * 100}%`,
        transform: `translateX(${position > 0.6 ? "-110%" : "10%"})`,
      }}
    >
      <div className="text-caption text-text-secondary mb-2">{label}</div>
      <div className="flex flex-col gap-1.5">
        {series.map((s) => {
          const value = s.values[index] ?? 0;
          return (
            <div key={s.key} className="flex items-center justify-between gap-4">
              <span className="text-caption text-text-secondary flex items-center gap-1.5">
                <span className="size-1.5 rounded-full" style={{ backgroundColor: s.color }} />
                {s.label}
              </span>
              <span className="text-caption text-text-primary font-medium tabular-nums">
                {s.format ? s.format(value) : formatCompact(value)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Ширина контейнера в реальных пикселях.
 *
 * Без неё график рисуется в фиксированной системе координат и растягивается
 * средствами SVG — вместе с текстом. На узком экране подписи осей уезжали
 * примерно к 5px и переставали читаться, что противоречит требованию к
 * минимальному размеру шрифта (v0.3 §120). Здесь одна единица SVG равна одному
 * CSS-пикселю, поэтому подписи сохраняют заданный размер на любой ширине.
 */
function useContainerWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const observer = new ResizeObserver(([entry]) => {
      const next = entry?.contentRect.width ?? 0;
      if (next > 0) setWidth(Math.round(next));
    });

    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return { ref, width };
}

/** Округляет верх шкалы до «круглого» значения, чтобы подписи оси читались. */
function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}
