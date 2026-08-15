import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Пакеты воркспейса поставляются исходниками на TypeScript и собираются вместе
  // с приложением — отдельный шаг сборки библиотеки не нужен.
  transpilePackages: ["@ads-os/ui", "@ads-os/tokens", "@ads-os/schemas"],
};

export default nextConfig;
