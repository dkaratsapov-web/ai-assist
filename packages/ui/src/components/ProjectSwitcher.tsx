"use client";

import { useEffect, useRef, useState } from "react";
import type { ProjectStatusKey } from "@ads-os/tokens";
import { cn } from "../lib/cn";
import { ProjectStatusBadge } from "./StatusBadge";
import { IconChevronDown, IconCheck } from "../icons";

export interface SwitchableProject {
  id: string;
  name: string;
  status: ProjectStatusKey;
}

export interface ProjectSwitcherProps {
  projects: SwitchableProject[];
  selectedId: string;
  onSelect: (id: string) => void;
  className?: string;
}

/**
 * Переключатель проекта.
 *
 * Выбранный проект всегда виден: и Web, и бот обязаны явно показывать, в каком
 * проекте находится пользователь (v0.3 §130).
 */
export function ProjectSwitcher({
  projects,
  selectedId,
  onSelect,
  className,
}: ProjectSwitcherProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const selected = projects.find((project) => project.id === selectedId);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className={cn(
          "rounded-control border-border bg-surface flex w-full items-center justify-between gap-2 border px-3 py-2",
          "hover:bg-surface-hover focus-visible:outline-focus focus-visible:outline-2 focus-visible:outline-offset-2",
          "transition-colors duration-(--duration-fast) ease-out max-sm:min-h-11",
        )}
      >
        <span className="text-body-sm text-text-primary min-w-0 truncate font-medium">
          {selected?.name ?? "Выберите проект"}
        </span>
        <IconChevronDown size={16} className="text-text-secondary shrink-0" />
      </button>

      {open && (
        <ul
          role="listbox"
          aria-label="Проекты"
          className={cn(
            "bg-surface border-border shadow-overlay rounded-small-card absolute top-full left-0 z-(--z-drawer) mt-1.5 w-full border p-1",
            "max-h-72 overflow-y-auto",
          )}
        >
          {projects.map((project) => {
            const active = project.id === selectedId;
            return (
              <li key={project.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  onClick={() => {
                    onSelect(project.id);
                    setOpen(false);
                  }}
                  className={cn(
                    "rounded-control flex w-full items-center justify-between gap-2 px-2.5 py-2 text-left",
                    "hover:bg-surface-hover focus-visible:outline-focus focus-visible:outline-2 focus-visible:-outline-offset-2",
                    "transition-colors duration-(--duration-fast) ease-out",
                  )}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="text-body-sm text-text-primary truncate">{project.name}</span>
                    <ProjectStatusBadge status={project.status} />
                  </span>
                  {active && <IconCheck size={16} className="text-text-primary shrink-0" />}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
