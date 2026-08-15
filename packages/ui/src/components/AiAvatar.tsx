import { cn } from "../lib/cn";

export interface AiAvatarProps {
  size?: number;
  /** Мягкая пульсация во время анализа. */
  thinking?: boolean;
  className?: string;
}

/**
 * Символ AI-помощника: чёрная сфера с двумя светлыми элементами-глазами.
 *
 * Намеренно минималистичен и не является персонажем: сложный 3D-маскот
 * конфликтовал бы с монохромным интерфейсом (v0.3 §136).
 *
 * Пульсация показывает, что идёт анализ, и отключается при
 * prefers-reduced-motion — это оформление, а не единственный признак процесса.
 */
export function AiAvatar({ size = 64, thinking = false, className }: AiAvatarProps) {
  const eye = size * 0.16;
  const gap = size * 0.11;

  return (
    <span
      role="img"
      aria-label="AI-помощник"
      className={cn(
        "bg-surface-inverse inline-flex shrink-0 items-center justify-center rounded-full",
        thinking && "animate-pulse motion-reduce:animate-none",
        className,
      )}
      style={{ width: size, height: size, gap }}
    >
      <span
        aria-hidden="true"
        className="bg-text-inverse rounded-full"
        style={{ width: eye, height: eye * 1.25 }}
      />
      <span
        aria-hidden="true"
        className="bg-text-inverse rounded-full"
        style={{ width: eye, height: eye * 1.25 }}
      />
    </span>
  );
}
