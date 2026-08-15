"use client";

import { Button, IconButton, SearchInput, cn } from "@ads-os/ui";
import { IconBell, IconHelp, IconMenu, IconPlus } from "@ads-os/ui/icons";

export interface TopbarProps {
  title: string;
  subtitle?: string;
  /** Количество непрочитанных уведомлений. */
  notifications?: number;
  onMenuClick: () => void;
  className?: string;
}

/**
 * Верхняя панель (v0.3 §124).
 *
 * Содержит только поиск, уведомления, справку, профиль и контекстное действие.
 * Дополнительными кнопками не перегружается — иначе она превращается во вторую
 * панель инструментов.
 */
export function Topbar({
  title,
  subtitle,
  notifications = 0,
  onMenuClick,
  className,
}: TopbarProps) {
  return (
    <header
      className={cn(
        "border-border bg-bg sticky top-0 z-(--z-sticky) flex items-center gap-4 border-b px-4",
        "min-h-(--layout-topbar-height)",
        className,
      )}
    >
      <IconButton
        label="Открыть меню"
        icon={<IconMenu size={20} />}
        variant="ghost"
        size="sm"
        onClick={onMenuClick}
        className="lg:hidden"
      />

      <div className="min-w-0 flex-1">
        <h1 className="text-h3 text-text-primary truncate">{title}</h1>
        {subtitle && <p className="text-caption text-text-secondary truncate">{subtitle}</p>}
      </div>

      {/* Ширина задана явно, а не через flex-1: два растягивающихся соседа
          делят место непредсказуемо, и поле схлопывалось до иконок. */}
      <div className="hidden shrink-0 md:block md:w-56 lg:w-72 xl:w-96">
        <SearchInput
          placeholder="Поиск по проектам, кампаниям, ключевым словам…"
          shortcut="⌘K"
          aria-label="Поиск по проектам, кампаниям и ключевым словам"
        />
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        <span className="relative inline-flex">
          <IconButton
            label={
              notifications > 0 ? `Уведомления, непрочитанных: ${notifications}` : "Уведомления"
            }
            icon={<IconBell size={20} />}
            variant="ghost"
            size="sm"
          />
          {notifications > 0 && (
            <span
              aria-hidden="true"
              className="bg-critical text-text-inverse absolute -top-0.5 -right-0.5 flex size-4 items-center justify-center rounded-full text-[10px] font-medium"
            >
              {notifications > 9 ? "9+" : notifications}
            </span>
          )}
        </span>

        <IconButton
          label="Справка"
          icon={<IconHelp size={20} />}
          variant="ghost"
          size="sm"
          className="hidden sm:inline-flex"
        />

        <Button size="sm" iconLeft={<IconPlus size={16} />} className="hidden sm:inline-flex">
          Новый проект
        </Button>

        <button
          type="button"
          aria-label="Профиль пользователя: Иван Петров"
          className={cn(
            "rounded-pill hover:bg-surface-hover flex items-center gap-2 py-1 pr-2 pl-1",
            "focus-visible:outline-focus focus-visible:outline-2 focus-visible:outline-offset-2",
            "transition-colors duration-(--duration-fast) ease-out",
          )}
        >
          <span
            aria-hidden="true"
            className="bg-bg-secondary text-text-secondary text-micro flex size-7 items-center justify-center rounded-full font-medium"
          >
            ИП
          </span>
          <span className="text-caption text-text-primary hidden lg:inline">Иван Петров</span>
        </button>
      </div>
    </header>
  );
}
