/**
 * Форматирование чисел для ru-RU.
 *
 * Локаль зафиксирована: первый релиз только на русском (v0.4 §23). Отдельная
 * абстракция локализации не вводится, но всё форматирование собрано здесь,
 * чтобы позже её можно было добавить в одном месте.
 */

const LOCALE = "ru-RU";

const decimal = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 });
const decimal1 = new Intl.NumberFormat(LOCALE, {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

/** 142750 → «142 750» */
export function formatNumber(value: number): string {
  return decimal.format(value);
}

/** 142750 → «142 750 ₽». Символ отделён неразрывным пробелом. */
export function formatCurrency(value: number): string {
  return `${decimal.format(Math.round(value))} ₽`;
}

/** 12 → «+12%», -7 → «−7%». Минус — типографский, не дефис. */
export function formatDelta(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${decimal1.format(Math.abs(value)).replace(",0", "")}%`;
}

/** 0.0532 → «5,3%» */
export function formatPercent(ratio: number): string {
  return `${decimal1.format(ratio * 100)}%`;
}

/** Компактная запись крупных чисел для осей: 150000 → «150K». */
export function formatCompact(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${decimal1.format(value / 1_000_000)}M`;
  if (Math.abs(value) >= 1_000) return `${decimal.format(Math.round(value / 1_000))}K`;
  return decimal.format(value);
}

const dayMonth = new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "long" });
const shortDate = new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "2-digit" });

/** «05 мая» */
export function formatDayMonth(date: Date): string {
  return dayMonth.format(date);
}

/** «05.05» — для подписей осей, где важна плотность. */
export function formatShortDate(date: Date): string {
  return shortDate.format(date);
}

/**
 * Относительное время: «10 минут назад».
 *
 * Свежесть данных — не косметика: Policy Engine опирается на неё при допуске
 * финансовых действий (v0.4 §9), поэтому возраст показывается пользователю
 * явно, а не прячется.
 */
export function formatRelativeTime(date: Date, now: Date = new Date()): string {
  const minutes = Math.round((now.getTime() - date.getTime()) / 60_000);
  if (minutes < 1) return "только что";
  if (minutes < 60) return `${minutes} ${plural(minutes, "минуту", "минуты", "минут")} назад`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} ${plural(hours, "час", "часа", "часов")} назад`;
  const days = Math.round(hours / 24);
  return `${days} ${plural(days, "день", "дня", "дней")} назад`;
}

/** Русское склонение после числительного. */
export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}
