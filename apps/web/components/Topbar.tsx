"use client";

import type { ReactNode } from "react";
import { IconButton, SearchInput, cn } from "@ads-os/ui";
import { UserMenu } from "./UserMenu";
import { IconBell, IconHelp, IconMenu } from "@ads-os/ui/icons";

export interface TopbarProps {
  title: string;
  subtitle?: string;
  /** Количество непрочитанных уведомлений. */
  notifications?: number;
  /**
   * Главное действие текущего экрана (v0.3 §124).
   *
   * Задаётся страницей, а не панелью. Раньше здесь стояла постоянная кнопка
   * «Новый проект», которая ничего не делала — неработающий элемент управления
   * хуже отсутствующего: по нему судят о том, что система умеет.
   */
  action?: ReactNode;
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
  action,
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
        {/* На телефоне колокольчик уступает место действию экрана: заголовок
            иначе сжимается до трёх букв. Вернётся вместе с экраном уведомлений,
            когда по нажатию будет что показывать. */}
        <span className="relative hidden sm:inline-flex">
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

        {/* Действие показывается и на телефоне. Скрывать его на узком экране
            означало бы, что с телефона нельзя завести или изменить проект —
            а работа специалиста часто начинается именно с телефона. */}
        {action && <span className="inline-flex shrink-0">{action}</span>}

        <UserMenu />
      </div>
    </header>
  );
}
