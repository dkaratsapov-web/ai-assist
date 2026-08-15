import { ApiError } from "@ads-os/schemas";

/**
 * Приводит любую ошибку к отображаемому виду.
 *
 * Нужно потому, что до этого экраны ловили только ApiError, а всё остальное —
 * сбой сети, ошибка CORS, недоступный backend — превращалось в null, и экран
 * молча оставался в скелетонах. Тихие сбои запрещены (v0.3 §63): пользователь
 * должен видеть, что произошло, и иметь возможность повторить.
 */
export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  return new ApiError(0, {
    error_code: "network_error",
    message: err instanceof Error ? `Сервис недоступен: ${err.message}` : "Сервис недоступен",
    request_id: "-",
    retryable: true,
  });
}
