import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Самодостаточная сборка для контейнера: в образ попадает только то, что
  // реально используется, вместе с нужными файлами пакетов воркспейса.
  output: "standalone",
  outputFileTracingRoot: path.join(import.meta.dirname, "../.."),
  // Пакеты воркспейса поставляются исходниками на TypeScript и собираются вместе
  // с приложением — отдельный шаг сборки библиотеки не нужен.
  transpilePackages: ["@ads-os/ui", "@ads-os/tokens", "@ads-os/schemas"],
};

export default nextConfig;
