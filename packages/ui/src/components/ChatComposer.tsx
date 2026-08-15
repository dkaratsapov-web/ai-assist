"use client";

import { useState, type FormEvent, type KeyboardEvent } from "react";
import { cn } from "../lib/cn";
import { IconButton } from "./Button";
import { IconSend } from "../icons";

export interface ChatComposerProps {
  onSubmit: (text: string) => void;
  placeholder?: string;
  /** Текущий проект. Вопрос по умолчанию относится к нему (v0.3 §135). */
  projectContext?: string;
  /** Короткие подсказки для пустого экрана. */
  suggestions?: string[];
  disabled?: boolean;
  busy?: boolean;
  className?: string;
}

/**
 * Поле ввода AI-чата.
 *
 * Контекст проекта показывается рядом с полем: пользователь должен видеть, к
 * какому проекту относится его вопрос, а не догадываться (v0.3 §135).
 */
export function ChatComposer({
  onSubmit,
  placeholder = "Напишите сообщение…",
  projectContext,
  suggestions,
  disabled = false,
  busy = false,
  className,
}: ChatComposerProps) {
  const [value, setValue] = useState("");

  const submit = () => {
    const text = value.trim();
    if (!text || disabled || busy) return;
    onSubmit(text);
    setValue("");
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {suggestions && suggestions.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => onSubmit(suggestion)}
              disabled={disabled || busy}
              className={cn(
                "rounded-pill border-border text-caption text-text-secondary border px-3 py-1.5",
                "hover:bg-surface-hover focus-visible:outline-focus focus-visible:outline-2 focus-visible:outline-offset-2",
                "transition-colors duration-(--duration-fast) ease-out disabled:opacity-45",
              )}
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      {projectContext && (
        <span className="text-micro text-text-secondary">
          Вопрос по проекту: <span className="text-text-primary font-medium">{projectContext}</span>
        </span>
      )}

      <form
        onSubmit={handleSubmit}
        className={cn(
          "rounded-control border-border-input bg-surface flex items-end gap-2 border p-1.5",
          "focus-within:outline-focus focus-within:outline-2 focus-within:outline-offset-2",
        )}
      >
        <textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          aria-label="Сообщение AI-помощнику"
          className={cn(
            "text-body-sm text-text-primary placeholder:text-text-secondary max-h-32 min-h-9 flex-1 resize-none",
            "bg-transparent px-2 py-2 outline-none disabled:cursor-not-allowed",
          )}
        />
        <IconButton
          label="Отправить"
          icon={<IconSend size={18} />}
          type="submit"
          size="sm"
          loading={busy}
          disabled={disabled || value.trim().length === 0}
        />
      </form>
    </div>
  );
}
