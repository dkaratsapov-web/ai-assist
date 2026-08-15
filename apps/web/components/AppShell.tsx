"use client";

import { useState, type ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export interface AppShellProps {
  title: string;
  subtitle?: string;
  notifications?: number;
  /** Главное действие экрана. Показывается в верхней панели справа. */
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * Каркас приложения: Sidebar + Topbar + Content.
 *
 * На узких экранах sidebar превращается в выдвижную панель, но остаётся тем же
 * компонентом с той же структурой — «предсказуемость» из v0.3 §123 означает,
 * что состав и порядок пунктов не меняются вместе с шириной экрана.
 */
export function AppShell({ title, subtitle, notifications, actions, children }: AppShellProps) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="flex min-h-dvh">
      <Sidebar mobileOpen={mobileNavOpen} onNavigate={() => setMobileNavOpen(false)} />

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          title={title}
          subtitle={subtitle}
          notifications={notifications}
          action={actions}
          onMenuClick={() => setMobileNavOpen(true)}
        />

        <main className="mx-auto flex w-full max-w-(--layout-content-max-width) flex-1 flex-col gap-6 p-4 lg:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
