import type { Tone } from "@ads-os/tokens";

/**
 * Классы для смысловых тонов.
 *
 * Записаны явно, а не собираются из строк: Tailwind сканирует исходники
 * статически и не увидит класс, склеенный в рантайме.
 *
 * Цвет здесь — вспомогательный носитель смысла. Текстовая подпись у статуса
 * есть всегда (v0.3 §139), поэтому интерфейс остаётся понятным и без цвета.
 */
export interface ToneClasses {
  /** Фон + текст + граница для бейджа. */
  badge: string;
  /** Заливка точки-индикатора. */
  dot: string;
  /** Только цвет текста. */
  text: string;
  /** Только цвет границы. */
  border: string;
  /** Мягкая подложка — для акцентной полосы или выделенного блока. */
  surface: string;
}

export const toneClasses: Record<Tone, ToneClasses> = {
  success: {
    badge: "bg-success-bg text-success border-success-border",
    dot: "bg-success",
    text: "text-success",
    border: "border-success-border",
    surface: "bg-success-bg",
  },
  warning: {
    badge: "bg-warning-bg text-warning border-warning-border",
    dot: "bg-warning",
    text: "text-warning",
    border: "border-warning-border",
    surface: "bg-warning-bg",
  },
  critical: {
    badge: "bg-critical-bg text-critical border-critical-border",
    dot: "bg-critical",
    text: "text-critical",
    border: "border-critical-border",
    surface: "bg-critical-bg",
  },
  info: {
    badge: "bg-info-bg text-info border-info-border",
    dot: "bg-info",
    text: "text-info",
    border: "border-info-border",
    surface: "bg-info-bg",
  },
  neutral: {
    badge: "bg-neutral-bg text-neutral border-neutral-border",
    dot: "bg-neutral",
    text: "text-neutral",
    border: "border-neutral-border",
    surface: "bg-neutral-bg",
  },
};
