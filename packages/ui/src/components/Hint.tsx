import type { ReactNode } from "react";
import { cn } from "../lib/cn";

export interface HintProps {
  children: ReactNode;
  className?: string;
}

/**
 * Пояснение к тому, что рядом.
 *
 * Отдельный компонент нужен потому, что в продукте много объяснений, и раньше
 * они верстались обычным абзацем — тем же весом, что и данные. Экран
 * превращался в сплошную серую стену, где «5400 в месяц» и «Вордстат запрещает
 * автоматический сбор» выглядели одинаково важными.
 *
 * Две вещи, которые эта обёртка делает, и обе про читаемость:
 *
 * **Длина строки ограничена.** Текст на всю ширину экрана глаз не удерживает:
 * на обратном ходе строки он теряет место, и человек перечитывает. Предел
 * примерно в семьдесят знаков — тот, на котором чтение перестаёт быть работой.
 *
 * **Вес приглушён.** Пояснение читают один раз и больше к нему не
 * возвращаются, поэтому оно уступает данным, а не спорит с ними.
 */
export function Hint({ children, className }: HintProps) {
  return (
    <p className={cn("text-caption text-text-secondary max-w-(--layout-measure)", className)}>
      {children}
    </p>
  );
}

export interface DetailsProps {
  summary: string;
  children: ReactNode;
  className?: string;
}

/**
 * Длинное объяснение, свёрнутое до одной строки.
 *
 * Объяснение на пять предложений нужно ровно один раз — когда человек видит
 * экран впервые. На сотый раз оно занимает половину первого экрана и отодвигает
 * работу вниз. Свёрнутый вид оставляет объяснение доступным и убирает его с
 * дороги; `details` выбран вместо своего раскрывающегося блока потому, что он
 * работает без скриптов, ищется поиском по странице и правильно читается
 * программой экранного доступа.
 */
export function Details({ summary, children, className }: DetailsProps) {
  return (
    <details className={cn("group", className)}>
      <summary
        className={cn(
          "text-caption text-text-secondary hover:text-text-primary cursor-pointer list-none",
          "focus-visible:outline-focus rounded-control focus-visible:outline-2 focus-visible:outline-offset-2",
          "inline-flex items-center gap-1.5 select-none",
        )}
      >
        <span
          aria-hidden="true"
          className="transition-transform duration-(--duration-fast) group-open:rotate-90"
        >
          ›
        </span>
        {summary}
      </summary>
      <div className="text-caption text-text-secondary mt-2 flex max-w-(--layout-measure) flex-col gap-2">
        {children}
      </div>
    </details>
  );
}
