"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { cn } from "../lib/cn";
import { IconButton } from "./Button";
import { IconClose } from "../icons";

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children?: ReactNode;
  /** Кнопки внизу. Порядок: подтверждающее действие последним справа. */
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const sizeClasses = {
  sm: "max-w-md",
  md: "max-w-lg",
  lg: "max-w-2xl",
} as const;

/**
 * Модальное окно.
 *
 * Построено на нативном <dialog>: браузер сам обеспечивает удержание фокуса,
 * закрытие по Esc и инертность фона. Собственная реализация фокус-ловушки была
 * бы и объёмнее, и хуже.
 */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
  className,
}: ModalProps) {
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
      aria-labelledby="modal-title"
      className={cn(
        "bg-surface rounded-card shadow-overlay text-text-primary m-auto w-[calc(100vw-2rem)] p-0",
        "backdrop:bg-[rgba(10,10,10,0.32)]",
        "open:animate-none",
        sizeClasses[size],
        className,
      )}
    >
      {/* Клик по подложке закрывает окно; клик внутри — нет. */}
      <div className="p-6" onClick={(event) => event.stopPropagation()} role="presentation">
        <div className="mb-4 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 id="modal-title" className="text-h2 text-text-primary">
              {title}
            </h2>
            {description && (
              <p className="text-body-sm text-text-secondary mt-1.5">{description}</p>
            )}
          </div>
          <IconButton
            label="Закрыть"
            icon={<IconClose size={18} />}
            variant="ghost"
            size="sm"
            onClick={onClose}
          />
        </div>

        {children}

        {footer && <div className="mt-6 flex flex-wrap justify-end gap-2">{footer}</div>}
      </div>
    </dialog>
  );
}
