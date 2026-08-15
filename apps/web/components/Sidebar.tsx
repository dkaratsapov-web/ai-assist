"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@ads-os/ui";
import { IconChevronRight } from "@ads-os/ui/icons";
import { globalNavigation, settingsNavItem, type NavItem } from "@/lib/navigation";

export interface SidebarProps {
  /** На узких экранах sidebar показывается как выдвижная панель. */
  mobileOpen: boolean;
  onNavigate: () => void;
}

/**
 * Постоянная левая навигация.
 *
 * Активный раздел выделяется мягким серым фоном, а не ярким цветом: акцентные
 * цвета зарезервированы за смысловыми состояниями (v0.3 §123).
 */
export function Sidebar({ mobileOpen, onNavigate }: SidebarProps) {
  return (
    <>
      {/* Затемнение под выдвинутой панелью — только на узких экранах. */}
      {mobileOpen && (
        <div
          aria-hidden="true"
          onClick={onNavigate}
          className="fixed inset-0 z-(--z-drawer) bg-[rgba(10,10,10,0.32)] lg:hidden"
        />
      )}

      <nav
        aria-label="Основная навигация"
        className={cn(
          "border-border bg-surface flex shrink-0 flex-col border-r",
          "w-(--layout-sidebar-width)",
          // Десктоп: липкая колонка на всю высоту. Мобильный: выдвижная панель.
          "lg:sticky lg:top-0 lg:h-dvh lg:translate-x-0",
          "fixed inset-y-0 left-0 z-(--z-drawer) transition-transform duration-(--duration-panel) ease-out",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-(--layout-topbar-height) shrink-0 items-center gap-2.5 px-4">
          <span
            aria-hidden="true"
            className="bg-surface-inverse text-text-inverse rounded-control flex size-8 items-center justify-center text-[15px] font-semibold"
          >
            A
          </span>
          <span className="text-h3 text-text-primary tracking-tight">ADS OS</span>
        </div>

        <div className="scrollbar-slim flex-1 overflow-y-auto px-3 pb-4">
          {globalNavigation.map((group) => (
            <div key={group.key} className="mb-1">
              {group.title && (
                <h2 className="text-micro text-text-secondary px-2.5 pt-4 pb-1.5 tracking-wide uppercase">
                  {group.title}
                </h2>
              )}
              <ul className="flex list-none flex-col gap-0.5">
                {group.items.map((item) => (
                  <li key={item.key}>
                    <SidebarLink item={item} onNavigate={onNavigate} />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="shrink-0 px-3 pb-4">
          <SidebarLink item={settingsNavItem} onNavigate={onNavigate} showChevron />
        </div>
      </nav>
    </>
  );
}

function SidebarLink({
  item,
  onNavigate,
  showChevron = false,
}: {
  item: NavItem;
  onNavigate: () => void;
  showChevron?: boolean;
}) {
  const pathname = usePathname();
  const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
  const Icon = item.icon;

  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "rounded-control text-body-sm flex items-center gap-2.5 px-2.5 py-2",
        "focus-visible:outline-focus focus-visible:outline-2 focus-visible:outline-offset-2",
        "transition-colors duration-(--duration-fast) ease-out max-sm:min-h-11",
        active
          ? "bg-bg-secondary text-text-primary font-medium"
          : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
      )}
    >
      <Icon size={18} className="shrink-0" />
      <span className="min-w-0 flex-1 truncate">{item.label}</span>

      {item.badge !== undefined && (
        <span className="text-micro text-text-secondary bg-bg-secondary rounded-pill shrink-0 px-1.5 py-0.5 font-medium">
          {item.badge}
        </span>
      )}
      {showChevron && <IconChevronRight size={16} className="text-text-secondary shrink-0" />}
    </Link>
  );
}
