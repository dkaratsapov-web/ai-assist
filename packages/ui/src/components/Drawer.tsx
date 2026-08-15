"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { cn } from "../lib/cn";
import { IconButton } from "./Button";
import { IconClose } from "../icons";

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
  width?: "sm" | "md" | "lg";
  className?: string;
}

const widthClasses = {
  sm: "sm:max-w-md",
  md: "sm:max-w-lg",
  lg: "sm:max-w-2xl",
} as const;

/**
 * Боковая панель.
 *
 * Основной способ показать подробности рекомендации: evidence, метрики и
 * ожидаемый эффект открываются здесь, а карточка остаётся компактной
 * (v0.3 §126).
 *
 * Как и Modal, построена на нативном <dialog> ради удержания фокуса и Esc.
 */
export function Drawer({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  width = "md",
  className,
}: DrawerProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={onClose}
      aria-labelledby="drawer-title"
      className={cn(
        "bg-surface shadow-overlay text-text-primary m-0 ml-auto h-full max-h-full w-full p-0",
        "backdrop:bg-[rgba(10,10,10,0.32)]",
        widthClasses[width],
        className,
      )}
    >
      <div className="flex h-full flex-col">
        <header className="border-border flex shrink-0 items-start justify-between gap-4 border-b px-6 py-4">
          <div className="min-w-0">
            <h2 id="drawer-title" className="text-h3 text-text-primary">
              {title}
            </h2>
            {description && <p className="text-caption text-text-secondary mt-1">{description}</p>}
          </div>
          <IconButton
            label="Закрыть панель"
            icon={<IconClose size={18} />}
            variant="ghost"
            size="sm"
            onClick={onClose}
          />
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-4">{children}</div>

        {footer && (
          <footer className="border-border flex shrink-0 flex-wrap justify-end gap-2 border-t px-6 py-4">
            {footer}
          </footer>
        )}
      </div>
    </dialog>
  );
}
