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

function SignIn() {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "";

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center p-6">
      <Card>
        <div className="flex flex-col gap-5 text-center">
          <div className="flex flex-col gap-2">
            <h1 className="text-h2 text-text-primary">ADS OS</h1>
            <p className="text-body-sm text-text-secondary">Помощник по контекстной рекламе</p>
          </div>

          {/* Обычная ссылка, а не запрос из скрипта: вход — это переход на
              сторону Яндекса, и браузер должен уйти туда целиком. */}
          <a href={`${baseUrl}/api/v1/auth/login`} className="block">
            <Button fullWidth size="lg">
              Войти через Яндекс
            </Button>
          </a>

          <p className="text-caption text-text-secondary">
            Паролей здесь нет: вход и подтверждение личности — на стороне Яндекса. Доступ выдаёт
            владелец, добавляя вас в участники.
          </p>
        </div>
      </Card>
    </main>
  );
}
