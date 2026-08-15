"use client";

import { useId, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "../lib/cn";
import { IconSearch } from "../icons";

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  label?: string;
  /** Пояснение под полем. Скрывается, когда показана ошибка. */
  hint?: string;
  /** Текст ошибки. Связывается с полем через aria-describedby. */
  error?: string;
  iconLeft?: ReactNode;
  iconRight?: ReactNode;
}

/**
 * Текстовое поле.
 *
 * Граница использует border-input, а не декоративный border: поле опознаётся
 * именно по границе, поэтому она обязана держать контраст 3:1 (WCAG 1.4.11).
 *
 * Ошибка передаётся текстом и через aria-invalid, а не одним лишь цветом
 * рамки (v0.3 §139).
 */
export function Input({
  label,
  hint,
  error,
  iconLeft,
  iconRight,
  className,
  id,
  ...props
}: InputProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const messageId = `${inputId}-message`;
  const hasMessage = Boolean(error ?? hint);

  return (
    <div className="flex w-full flex-col gap-1.5">
      {label && (
        <label htmlFor={inputId} className="text-caption text-text-secondary font-medium">
          {label}
        </label>
      )}

      <div className="relative flex items-center">
        {iconLeft && (
          <span className="text-text-secondary pointer-events-none absolute left-3 flex">
            {iconLeft}
          </span>
        )}

        <input
          id={inputId}
          aria-invalid={error ? true : undefined}
          aria-describedby={hasMessage ? messageId : undefined}
          className={cn(
            "text-body-sm text-text-primary placeholder:text-text-secondary h-10 w-full max-sm:min-h-11",
            "rounded-control bg-surface border transition-colors duration-(--duration-fast) ease-out",
            "focus-visible:outline-focus focus-visible:outline-2 focus-visible:outline-offset-2",
            "disabled:text-text-disabled disabled:bg-bg-secondary disabled:cursor-not-allowed",
            error ? "border-critical" : "border-border-input hover:border-text-secondary",
            iconLeft ? "pl-10" : "pl-3.5",
            iconRight ? "pr-10" : "pr-3.5",
            className,
          )}
          {...props}
        />

        {iconRight && (
          <span className="text-text-secondary absolute right-3 flex">{iconRight}</span>
        )}
      </div>

      {hasMessage && (
        <p
          id={messageId}
          className={cn("text-caption", error ? "text-critical" : "text-text-secondary")}
        >
          {error ?? hint}
        </p>
      )}
    </div>
  );
}

export interface SearchInputProps extends Omit<InputProps, "iconLeft" | "type"> {
  /** Подсказка сочетания клавиш, например «⌘K». Чисто визуальная. */
  shortcut?: string;
}

export function SearchInput({
  placeholder = "Поиск…",
  shortcut,
  className,
  ...props
}: SearchInputProps) {
  return (
    <Input
      type="search"
      placeholder={placeholder}
      iconLeft={<IconSearch size={18} />}
      iconRight={
        shortcut ? (
          <kbd
            aria-hidden="true"
            className="text-micro text-text-secondary border-border bg-bg-secondary rounded-md border px-1.5 py-0.5"
          >
            {shortcut}
          </kbd>
        ) : undefined
      }
      className={cn("bg-bg-secondary hover:border-border-input border-transparent", className)}
      {...props}
    />
  );
}
