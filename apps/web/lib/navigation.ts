import type { ComponentType } from "react";
import {
  IconChart,
  IconClock,
  IconFolder,
  IconGlobe,
  IconHome,
  IconSearch,
  IconSettings,
  IconTarget,
  IconUsers,
  type IconProps,
} from "@ads-os/ui/icons";

export interface NavItem {
  key: string;
  label: string;
  href: string;
  icon: ComponentType<IconProps>;
  /** Число рядом с пунктом: непрочитанные рекомендации, задачи и т.п. */
  badge?: number;
}

export interface NavGroup {
  key: string;
  /** Заголовок группы. Отсутствует у верхнеуровневых пунктов. */
  title?: string;
  items: NavItem[];
}

/**
 * Глобальная навигация Web (v0.3 §123).
 *
 * Каждый пункт имеет иконку и текст: только иконки для ключевой навигации не
 * используются (v0.3 §145).
 *
 * В списке только те экраны, которые существуют. Раньше здесь было ещё
 * двенадцать пунктов — шаблоны, отчёты, эксперименты, генератор объявлений,
 * интеграции, — и каждый вёл на страницу «не найдено». Меню, половина которого
 * не работает, хуже короткого меню: человек перестаёт доверять и остальным
 * пунктам и не понимает, что сломалось, а что просто ещё не сделано. Пункты
 * вернутся вместе со своими экранами, по одному.
 */
export const globalNavigation: NavGroup[] = [
  {
    key: "root",
    items: [{ key: "home", label: "Главная", href: "/", icon: IconHome }],
  },
  {
    key: "projects",
    title: "Проекты",
    items: [{ key: "projects", label: "Проекты", href: "/projects", icon: IconFolder }],
  },
  {
    key: "research",
    title: "Исследование",
    items: [
      { key: "site-audit", label: "Аудит сайта", href: "/site-audit", icon: IconGlobe },
      { key: "competitors", label: "Конкуренты", href: "/competitors", icon: IconUsers },
      { key: "economics", label: "Экономика", href: "/economics", icon: IconChart },
    ],
  },
  {
    key: "build",
    title: "Сборка кампании",
    items: [{ key: "semantics", label: "Семантика", href: "/semantics", icon: IconSearch }],
  },
  {
    key: "launch",
    title: "Запуск",
    items: [{ key: "strategy", label: "Стратегия запуска", href: "/strategy", icon: IconTarget }],
  },
  {
    key: "history",
    title: "История",
    items: [{ key: "activity", label: "Журнал действий", href: "/activity", icon: IconClock }],
  },
];

export const settingsNavItem: NavItem = {
  key: "settings",
  label: "Настройки",
  href: "/settings",
  icon: IconSettings,
};

/**
 * Навигация внутри проекта (v0.4 §4).
 *
 * Заменяет три расходившихся списка из v0.3 (§78, §127, §130). Бот показывает
 * её сокращённо и уводит на Web через deep link.
 */
export const projectNavigation: {
  key: string;
  label: string;
  children?: { key: string; label: string }[];
}[] = [
  { key: "overview", label: "Обзор" },
  {
    key: "research",
    label: "Исследование",
    children: [
      { key: "website", label: "Сайт" },
      { key: "competitors", label: "Конкуренты" },
    ],
  },
  { key: "economics", label: "Экономика" },
  { key: "strategy", label: "Стратегия" },
  { key: "semantics", label: "Семантика" },
  { key: "campaigns", label: "Кампании" },
  { key: "analytics", label: "Аналитика" },
  { key: "leads", label: "Лиды" },
  { key: "recommendations", label: "Рекомендации" },
  { key: "experiments", label: "Эксперименты" },
  { key: "tasks", label: "Задачи" },
  { key: "settings", label: "Настройки" },
];
