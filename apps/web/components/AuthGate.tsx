"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { CurrentUserRead } from "@ads-os/schemas";
import { Button, Card, ErrorState, Skeleton } from "@ads-os/ui";
import { createApiClient } from "@/lib/api";
import { toApiError } from "@/lib/errors";

const CurrentUserContext = createContext<CurrentUserRead | null>(null);

/** Кто сейчас вошёл. Внутри AuthGate значение всегда есть. */
export function useCurrentUser(): CurrentUserRead {
  const user = useContext(CurrentUserContext);
  if (user === null) {
    throw new Error("useCurrentUser вызван вне AuthGate");
  }
  return user;
}

type State =
  | { kind: "loading" }
  | { kind: "anonymous" }
  | { kind: "signed-in"; user: CurrentUserRead }
  | { kind: "error"; message: string };

/**
 * Не пускает внутрь приложения без входа.
 *
 * Проверка идёт на сервере при каждом запросе — это и есть настоящая защита.
 * Здесь решается другой вопрос: что показать человеку. Без этой обёртки
 * невошедший увидел бы каркас приложения и десяток ошибок «требуется вход»
 * вместо понятной страницы входа.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const api = useMemo(() => createApiClient(), []);
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let ignore = false;

    void (async () => {
      try {
        const user = await api.getCurrentUser();
        if (ignore) return;
        setState(user ? { kind: "signed-in", user } : { kind: "anonymous" });
      } catch (err) {
        if (ignore) return;
        // Недоступный backend — это не «вы не вошли». Показывать в таком случае
        // страницу входа значит врать: кнопка всё равно не сработает.
        setState({ kind: "error", message: toApiError(err).message });
      }
    })();

    return () => {
      ignore = true;
    };
  }, [api]);

  if (state.kind === "loading") {
    return (
      <div className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-4 p-6">
        <Skeleton shape="card" />
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="mx-auto flex min-h-dvh max-w-md flex-col justify-center p-6">
        <Card>
          <ErrorState
            title="Сервис недоступен"
            description={state.message}
            onRetry={() => window.location.reload()}
          />
        </Card>
      </div>
    );
  }

  if (state.kind === "anonymous") {
    return <SignIn />;
  }

  return <CurrentUserContext.Provider value={state.user}>{children}</CurrentUserContext.Provider>;
}

/**
 * Что показать, когда вход не состоялся.
 *
 * Раньше отказ прилетал в браузер строкой JSON в адресной строке. Формально там
 * было написано всё нужное, практически это выглядит как сломавшийся сайт —
 * человек не понимает, дело в нём, в ссылке или в сервисе. Поэтому у каждой
 * причины здесь свой заголовок, своё объяснение и своё следующее действие.
 */
const LOGIN_ERRORS: Record<string, { title: string; text: string; retryOther: boolean }> = {
  access_denied: {
    title: "Этого аккаунта пока нет в участниках",
    text: "Вход в Яндексе прошёл, но доступ выдаёт владелец: он добавляет почту в список участников. Попросите добавить вас — или войдите тем аккаунтом, который уже добавлен.",
    retryOther: true,
  },
  expired: {
    title: "Страница входа устарела",
    text: "Так бывает, если вкладка провисела открытой слишком долго или вход начался в другом окне. Ничего не сломалось — начните заново.",
    retryOther: false,
  },
  yandex_failed: {
    title: "Яндекс не подтвердил вход",
    text: "Похоже, вход был отменён или Яндекс сейчас не отвечает. Попробуйте ещё раз через минуту.",
    retryOther: false,
  },
  not_configured: {
    title: "Вход пока не настроен",
    text: "На этом сервере не заданы ключи приложения Яндекс ID. Это настройка на стороне сервиса — сам по себе повтор не поможет.",
    retryOther: false,
  },
};

function SignIn() {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "";

  // Читается при первом же построении экрана, а не в эффекте. Экран входа
  // появляется только после ответа сервера «вы не вошли», то есть всегда в
  // браузере, — и лишнего кадра без объяснения тут быть не должно.
  const [failure] = useState(() => {
    const reason = new URLSearchParams(window.location.search).get("login_error");
    return reason ? (LOGIN_ERRORS[reason] ?? LOGIN_ERRORS.access_denied) : null;
  });

  useEffect(() => {
    // Причина убирается из адреса: иначе она останется в закладке и в истории,
    // и человек будет видеть отказ при каждом заходе.
    if (failure) window.history.replaceState(null, "", window.location.pathname);
  }, [failure]);

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center p-6">
      <Card>
        <div className="flex flex-col gap-5 text-center">
          <div className="flex flex-col gap-2">
            <h1 className="text-h2 text-text-primary">AI Helper Pro</h1>
            <p className="text-body-sm text-text-secondary">Помощник по контекстной рекламе</p>
          </div>

          {failure && (
            <div className="border-warning-border bg-warning-bg rounded-control border p-4 text-left">
              <p className="text-body-sm text-text-primary font-medium">{failure.title}</p>
              <p className="text-body-sm text-text-secondary mt-1">{failure.text}</p>
            </div>
          )}

          {/* Обычная ссылка, а не запрос из скрипта: вход — это переход на
              сторону Яндекса, и браузер должен уйти туда целиком. */}
          <a href={`${baseUrl}/api/v1/auth/login`} className="block">
            <Button fullWidth size="lg">
              {failure ? "Попробовать снова" : "Войти через Яндекс"}
            </Button>
          </a>

          {failure?.retryOther && (
            // Без этой ссылки повтор молча приводит тем же аккаунтом к тому же
            // отказу: браузер помнит вход, и кнопка выглядит сломанной.
            <a href={`${baseUrl}/api/v1/auth/login?other=1`} className="block">
              <Button fullWidth variant="secondary">
                Войти другим аккаунтом
              </Button>
            </a>
          )}

          <p className="text-caption text-text-secondary">
            Паролей здесь нет: вход и подтверждение личности — на стороне Яндекса. Доступ выдаёт
            владелец, добавляя вас в участники.
          </p>
        </div>
      </Card>
    </main>
  );
}
