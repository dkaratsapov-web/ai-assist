import type { SVGProps } from "react";

/**
 * Набор иконок ADS OS.
 *
 * Все иконки тонкие, монохромные, с единым stroke-width 1.5 и currentColor
 * (v0.3 §121). Заливка не используется — так иконка одинаково читается на
 * светлом фоне, на чёрной кнопке и в отключённом состоянии.
 *
 * Иконка сама по себе никогда не является единственным носителем смысла:
 * у важных разделов и контролов есть текстовая подпись либо aria-label
 * (v0.3 §139, §145).
 */
export type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Icon({ size = 20, children, ...props }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  );
}

/* ── Навигация ─────────────────────────────────────────────────────────────── */

export const IconHome = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5 9.5V20h14V9.5" />
    <path d="M9.5 20v-6h5v6" />
  </Icon>
);

export const IconFolder = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l2 2.5h9A1.5 1.5 0 0 1 21 10v7.5A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5Z" />
  </Icon>
);

export const IconGrid = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
    <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
    <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
    <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
  </Icon>
);

export const IconLayers = (p: IconProps) => (
  <Icon {...p}>
    <path d="m12 3 8 4.5-8 4.5-8-4.5Z" />
    <path d="m4 12.5 8 4.5 8-4.5" />
    <path d="m4 16.5 8 4.5 8-4.5" />
  </Icon>
);

export const IconChart = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 20V4" />
    <path d="M4 20h16" />
    <path d="M8 20v-6" />
    <path d="M12.5 20V9" />
    <path d="M17 20v-9" />
  </Icon>
);

export const IconReport = (p: IconProps) => (
  <Icon {...p}>
    <path d="M6 3h8l4 4v14H6Z" />
    <path d="M14 3v4h4" />
    <path d="M9 12h6" />
    <path d="M9 16h4" />
  </Icon>
);

export const IconExperiment = (p: IconProps) => (
  <Icon {...p}>
    <path d="M10 3v6.5L5 18a2 2 0 0 0 1.7 3h10.6A2 2 0 0 0 19 18l-5-8.5V3" />
    <path d="M9 3h6" />
    <path d="M7.5 14h9" />
  </Icon>
);

export const IconSparkles = (p: IconProps) => (
  <Icon {...p}>
    <path d="m12 3 1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8Z" />
    <path d="M18 16.5 18.8 18.7 21 19.5l-2.2.8L18 22.5l-.8-2.2L15 19.5l2.2-.8Z" />
  </Icon>
);

export const IconBolt = (p: IconProps) => (
  <Icon {...p}>
    <path d="M13.5 3 5.5 13.5H11L10.5 21l8-10.5H13Z" />
  </Icon>
);

export const IconMegaphone = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 10.5v3a1.5 1.5 0 0 0 1.5 1.5H8l7 4.5V6L8 10.5H5.5A1.5 1.5 0 0 0 4 12" />
    <path d="M18 9.5a3.5 3.5 0 0 1 0 5" />
  </Icon>
);

export const IconSearch = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m20 20-3.6-3.6" />
  </Icon>
);

export const IconGlobe = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M3.5 12h17" />
    <path d="M12 3.5c2.2 2.4 3.3 5.4 3.3 8.5S14.2 18.1 12 20.5c-2.2-2.4-3.3-5.4-3.3-8.5S9.8 5.9 12 3.5Z" />
  </Icon>
);

export const IconPlug = (p: IconProps) => (
  <Icon {...p}>
    <path d="M9 3v5" />
    <path d="M15 3v5" />
    <path d="M6.5 8h11v3.5a5.5 5.5 0 0 1-11 0Z" />
    <path d="M12 17v4" />
  </Icon>
);

export const IconSettings = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 2.5v2.2M12 19.3v2.2M4.2 7.2l1.9 1.1M17.9 15.7l1.9 1.1M4.2 16.8l1.9-1.1M17.9 8.3l1.9-1.1" />
  </Icon>
);

export const IconTarget = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <circle cx="12" cy="12" r="4.5" />
    <circle cx="12" cy="12" r="1" />
  </Icon>
);

export const IconUsers = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="9" cy="8.5" r="3.5" />
    <path d="M3.5 20a5.5 5.5 0 0 1 11 0" />
    <path d="M16 5.5a3.5 3.5 0 0 1 0 6.9" />
    <path d="M17.5 14.6A5.5 5.5 0 0 1 20.5 20" />
  </Icon>
);

/* ── Действия и управление ─────────────────────────────────────────────────── */

export const IconBell = (p: IconProps) => (
  <Icon {...p}>
    <path d="M6.5 10a5.5 5.5 0 0 1 11 0c0 4 1.5 5.5 1.5 5.5H5S6.5 14 6.5 10Z" />
    <path d="M10 18.5a2 2 0 0 0 4 0" />
  </Icon>
);

export const IconHelp = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M9.8 9.3a2.3 2.3 0 0 1 4.4.8c0 1.6-2.2 2-2.2 3.4" />
    <path d="M12 17.2h.01" />
  </Icon>
);

export const IconPlus = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
);

export const IconClose = (p: IconProps) => (
  <Icon {...p}>
    <path d="m6 6 12 12M18 6 6 18" />
  </Icon>
);

export const IconMenu = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </Icon>
);

export const IconChevronRight = (p: IconProps) => (
  <Icon {...p}>
    <path d="m9.5 5 7 7-7 7" />
  </Icon>
);

export const IconChevronLeft = (p: IconProps) => (
  <Icon {...p}>
    <path d="m14.5 5-7 7 7 7" />
  </Icon>
);

export const IconChevronDown = (p: IconProps) => (
  <Icon {...p}>
    <path d="m5 9.5 7 7 7-7" />
  </Icon>
);

export const IconArrowRight = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 12h15" />
    <path d="m13.5 6.5 5.5 5.5-5.5 5.5" />
  </Icon>
);

export const IconArrowUp = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 19V5" />
    <path d="m6.5 10.5 5.5-5.5 5.5 5.5" />
  </Icon>
);

export const IconArrowDown = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 5v14" />
    <path d="m6.5 13.5 5.5 5.5 5.5-5.5" />
  </Icon>
);

export const IconSend = (p: IconProps) => (
  <Icon {...p}>
    <path d="M20 4 3.5 10.5l6.5 2.5 2.5 6.5Z" />
    <path d="m10 13 4-4" />
  </Icon>
);

export const IconAttachment = (p: IconProps) => (
  <Icon {...p}>
    <path d="M19 11.5 12.7 18a4 4 0 0 1-5.7-5.7l7-7a2.7 2.7 0 0 1 3.8 3.8l-7 7a1.3 1.3 0 0 1-1.9-1.9l6.3-6.3" />
  </Icon>
);

/* ── Статусы ───────────────────────────────────────────────────────────────── */

export const IconCheck = (p: IconProps) => (
  <Icon {...p}>
    <path d="m5 12.5 4.5 4.5L19 7" />
  </Icon>
);

export const IconCheckCircle = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="m8.5 12.2 2.4 2.4 4.6-4.9" />
  </Icon>
);

export const IconAlert = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 4.5 21 19.5H3Z" />
    <path d="M12 10v4" />
    <path d="M12 16.8h.01" />
  </Icon>
);

export const IconCritical = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 8v4.5" />
    <path d="M12 15.8h.01" />
  </Icon>
);

export const IconInfo = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 11.5V16" />
    <path d="M12 8.2h.01" />
  </Icon>
);

export const IconIdea = (p: IconProps) => (
  <Icon {...p}>
    <path d="M9 17.5a5.5 5.5 0 1 1 6 0v1.5a1.5 1.5 0 0 1-1.5 1.5h-3A1.5 1.5 0 0 1 9 19Z" />
    <path d="M9.5 17.5h5" />
  </Icon>
);

export const IconClock = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 1.8" />
  </Icon>
);

export const IconPause = (p: IconProps) => (
  <Icon {...p}>
    <path d="M9.5 5v14M14.5 5v14" />
  </Icon>
);

export const IconLock = (p: IconProps) => (
  <Icon {...p}>
    <rect x="5" y="10.5" width="14" height="10" rx="2" />
    <path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" />
  </Icon>
);
