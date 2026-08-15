import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";
import { tokens } from "@ads-os/tokens";

/**
 * Размеры шрифта из токенов: display, h1, h2, h3, metric, body, body-sm,
 * caption, micro.
 *
 * Список берётся из design-tokens.json, а не пишется руками, — иначе новый
 * размер шрифта пришлось бы не забыть продублировать здесь.
 */
const fontSizes = Object.keys(tokens.text);

/**
 * tailwind-merge, обученный нашей шкале размеров.
 *
 * Без этой настройки утилиты вида `text-caption` (размер) и `text-cta-text`
 * (цвет) попадают в одну группу, и при слиянии выживает только последняя. На
 * практике это выглядело как чёрный текст на чёрной кнопке: цвет молча
 * выбрасывался. Проверка контраста такое поймать не может — палитра там
 * корректна, ломается именно склейка классов.
 */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: fontSizes }],
    },
  },
});

/**
 * Объединяет классы и разрешает конфликты Tailwind: класс, переданный
 * потребителем компонента, должен побеждать значение по умолчанию.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
