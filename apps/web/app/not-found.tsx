import Link from "next/link";

/**
 * Страница «не найдено».
 *
 * Своя, а не стандартная от Next.js: та выводит английское «404 This page
 * could not be found» на голом фоне, без единой ссылки. Человек, попавший туда
 * по старой закладке, оставался в тупике и не понимал, работает сервис вообще
 * или нет.
 */
export default function NotFound() {
  return (
    <main className="bg-bg flex min-h-dvh items-center justify-center p-6">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <h1 className="text-h2 text-text-primary">Такой страницы нет</h1>
        <p className="text-body-sm text-text-secondary">
          Возможно, адрес набран с ошибкой или экран ещё не сделан. Сервис при этом работает —
          вернитесь на главную и продолжайте.
        </p>
        <Link
          href="/"
          className="rounded-control bg-cta text-cta-text text-body-sm focus-visible:outline-focus inline-flex items-center px-4 py-2 font-medium focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          На главную
        </Link>
      </div>
    </main>
  );
}
