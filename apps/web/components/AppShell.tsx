"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { createApiClient } from "@/lib/api";

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
  const unread = useUnreadCount();

  return (
    <div className="flex min-h-dvh">
      <Sidebar mobileOpen={mobileNavOpen} onNavigate={() => setMobileNavOpen(false)} />

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          title={title}
          subtitle={subtitle}
          notifications={notifications ?? unread}
          action={actions}
          onMenuClick={() => setMobileNavOpen(true)}
        />

        {/* Зазор между блоками — 16 пикселей, а не 24. На экранах здесь по
            шесть-восемь карточек подряд, и лишние восемь пикселей между
            каждой уводят половину работы за нижний край. */}
        <main className="mx-auto flex w-full max-w-(--layout-content-max-width) flex-1 flex-col gap-4 p-4 lg:px-6 lg:py-5">
          {children}
        </main>
      </div>
    </div>
  );
}

/**
 * Непрочитанные уведомления для колокольчика.
 *
 * Считается здесь, в каркасе, а не на каждом экране: иначе счётчик появлялся бы
 * на тех страницах, где его не забыли подключить, и пропадал на остальных — то
 * есть работал бы случайным образом.
 *
 * Ошибка запроса гасится молча. Колокольчик — не то, ради чего стоит показывать
 * человеку экран ошибки поверх работающей страницы.
 */
function useUnreadCount(): number {
  const api = useMemo(() => createApiClient(), []);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    let ignore = false;

    void (async () => {
      try {
        const list = await api.listNotifications(true);
        if (!ignore) setUnread(list.unread);
      } catch {
        // Не вошёл или сервис недоступен — счётчик просто остаётся нулём.
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api]);

  return unread;
}
