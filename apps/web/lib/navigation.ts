import type { ComponentType } from "react";
import {
  IconBolt,
  IconChart,
  IconExperiment,
  IconFolder,
  IconGlobe,
  IconHome,
  IconLayers,
  IconMegaphone,
  IconPlug,
  IconReport,
  IconSearch,
  IconSettings,
  IconSparkles,
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
 */
export const globalNavigation: NavGroup[] = [
  {
    key: "root",
    items: [{ key: "home", label: "Главная", href: "/", icon: IconHome }],
  },
  {
    key: "projects",
    title: "Проекты",
    items: [
      { key: "projects", label: "Проекты", href: "/projects", icon: IconFolder },
      // «Обзор всех проектов» временно убран. Его экрана ещё нет, а адрес
      // /projects/overview теперь попадает в страницу проекта и открывает её с
      // идентификатором «overview» — то есть с ошибкой. Пункт вернётся вместе с
      // самим экраном, по адресу, который не спорит с карточкой проекта.
      { key: "templates", label: "Шаблоны стратегий", href: "/templates", icon: IconLayers },
    ],
  },
  {
    key: "analytics",
    title: "Аналитика",
    items: [
      { key: "analytics", label: "Аналитика", href: "/analytics", icon: IconChart },
      { key: "reports", label: "Отчёты", href: "/reports", icon: IconReport },
      { key: "experiments", label: "Эксперименты", href: "/experiments", icon: IconExperiment },
    ],
  },
  {
    key: "ai",
    title: "AI-инструменты",
    items: [
      {
        key: "recommendations",
        label: "AI-рекомендации",
        href: "/recommendations",
        icon: IconSparkles,
        badge: 12,
      },
      { key: "quick-analysis", label: "Быстрый анализ", href: "/quick-analysis", icon: IconBolt },
      {
        key: "ad-generator",
        label: "Генератор объявлений",
        href: "/ad-generator",
        icon: IconMegaphone,
      },
      { key: "semantics", label: "Подбор семантики", href: "/semantics", icon: IconSearch },
      { key: "site-audit", label: "Аудит сайта", href: "/site-audit", icon: IconGlobe },
      { key: "competitors", label: "Конкуренты", href: "/competitors", icon: IconUsers },
    ],
  },
  {
    key: "integrations",
    title: "Интеграции",
    items: [
      { key: "direct", label: "Яндекс Директ", href: "/integrations/direct", icon: IconTarget },
      { key: "metrica", label: "Яндекс Метрика", href: "/integrations/metrica", icon: IconChart },
      { key: "crm", label: "CRM", href: "/integrations/crm", icon: IconUsers },
      { key: "channels", label: "Telegram / MAX", href: "/integrations/channels", icon: IconPlug },
    ],
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
