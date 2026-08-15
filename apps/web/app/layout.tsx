import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AuthGate } from "@/components/AuthGate";

/**
 * Один основной шрифт, без смешения семейств (v0.3 §120).
 *
 * Переменная подставляется в --font-sans, объявленную в токенах: если шрифт по
 * какой-то причине не загрузился, стек падает на системный, а источник правды
 * остаётся один.
 */
const inter = Inter({
  subsets: ["latin", "cyrillic"],
  display: "swap",
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "ADS OS",
  description: "Операционная система для специалиста по контекстной рекламе",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className={inter.variable}>
      <body>
        {/* Вход проверяется один раз для всего приложения, а не на каждой
            странице по отдельности: забыть обёртку на одной странице — значит
            открыть её всем. */}
        <AuthGate>{children}</AuthGate>
      </body>
    </html>
  );
}
