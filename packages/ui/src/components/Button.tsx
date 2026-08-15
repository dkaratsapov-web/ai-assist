import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "../lib/cn";
import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "critical";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "disabled"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Показывает индикатор и блокирует повторное нажатие. */
  loading?: boolean;
  disabled?: boolean;
  iconLeft?: ReactNode;
  iconRight?: ReactNode;
  fullWidth?: boolean;
}

const variantClasses: Record<ButtonVariant, string> = {
  primary: "bg-cta text-cta-text hover:bg-cta-hover active:bg-cta-active border border-transparent",
  secondary:
    "bg-surface text-text-primary border border-border-strong hover:bg-surface-hover active:bg-surface-active",
  ghost:
    "bg-transparent text-text-primary border border-transparent hover:bg-surface-hover active:bg-surface-active",
  critical:
    "bg-critical text-text-inverse border border-transparent hover:opacity-90 active:opacity-100",
};

const sizeClasses: Record<ButtonSize, string> = {
  // На тач-экранах высота поднимается до 44px — минимум из v0.3 §139.
  sm: "h-8 px-3 text-caption gap-1.5 rounded-control max-sm:min-h-11",
  md: "h-10 px-4 text-body-sm gap-2 rounded-control max-sm:min-h-11",
  lg: "h-11 px-5 text-body gap-2 rounded-control",
};

/**
 * Кнопка.
 *
 * Кольцо фокуса рисуется со смещением наружу, поэтому ложится на фон страницы
 * и остаётся различимым даже вокруг чёрной primary-кнопки.
 *
 * В состоянии loading кнопка блокируется: повторное нажатие не должно приводить
 * к повторному выполнению действия (v0.3 §113).
 */
export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  disabled = false,
  iconLeft,
  iconRight,
  fullWidth = false,
  className,
  children,
  type = "button",
  ...props
}: ButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <button
      type={type}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex shrink-0 cursor-pointer items-center justify-center font-medium whitespace-nowrap",
        "transition-[background-color,color,opacity,border-color] duration-(--duration-fast) ease-out",
        "focus-visible:outline-focus focus-visible:outline-2 focus-visible:outline-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-45",
        variantClasses[variant],
        sizeClasses[size],
        fullWidth && "w-full",
        className,
      )}
      {...props}
    >
      {loading ? <Spinner size={size === "sm" ? 14 : 16} /> : iconLeft}
      {children}
      {!loading && iconRight}
    </button>
  );
}

export interface IconButtonProps extends Omit<ButtonProps, "iconLeft" | "iconRight" | "children"> {
  /** Обязателен: контрол без видимого текста должен иметь подпись (v0.3 §139). */
  label: string;
  icon: ReactNode;
}

export function IconButton({ label, icon, size = "md", className, ...props }: IconButtonProps) {
  const box = size === "sm" ? "size-8" : size === "lg" ? "size-11" : "size-10";
  return (
    <Button
      aria-label={label}
      title={label}
      size={size}
      className={cn("px-0", box, "max-sm:min-h-11 max-sm:min-w-11", className)}
      {...props}
    >
      {icon}
    </Button>
  );
}
