import { cn } from "../lib/cn";

export interface SpinnerProps {
  size?: number;
  className?: string;
  /** Подпись для скринридера. Указывается, если рядом нет видимого текста. */
  label?: string;
}

/**
 * Индикатор выполнения.
 *
 * Вращение сохраняется и при prefers-reduced-motion: это не декоративная
 * анимация, а единственный признак того, что процесс идёт. Скорость при этом
 * снижается, чтобы движение не раздражало.
 */
export function Spinner({ size = 16, className, label }: SpinnerProps) {
  return (
    <span
      role={label ? "status" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cn("inline-flex shrink-0", className)}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        className="animate-spin motion-reduce:[animation-duration:1.8s]"
      >
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity="0.2" />
        <path
          d="M21 12a9 9 0 0 0-9-9"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
    </span>
  );
}
