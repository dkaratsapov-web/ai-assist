"""Детерминированный провайдер для разработки и тестов.

Пока провайдер не выбран, вся работа идёт здесь. Заглушка не обращается к сети,
не тратит квоту и даёт один и тот же ответ на один и тот же запрос — благодаря
этому тесты AI-модулей стабильны и не зависят от того, какую модель в итоге
подключат.

Значения заполняются из схемы ответа: заглушка не знает заранее, какие модели
появятся у будущих модулей, и не должна знать.
"""

from __future__ import annotations

import hashlib
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from .contracts import AiRequest, AiResult, AiUsage, PayloadT


class StubProvider:
    """Возвращает валидный по схеме ответ без обращения к модели."""

    name = "stub"

    async def complete(self, request: AiRequest[PayloadT]) -> AiResult[PayloadT]:
        seed = self._seed(request)
        payload = _build(request.response_model, seed)

        # Уверенность выводится из запроса, а не берётся случайной: тест,
        # проверяющий поведение при низкой уверенности, должен быть
        # воспроизводимым.
        confidence = 0.5 + (seed % 50) / 100

        return AiResult(
            payload=payload,
            confidence=round(confidence, 2),
            reasoning_summary=(
                f"Заглушка провайдера: ответ построен по схеме "
                f"{request.response_model.__name__} без обращения к модели."
            ),
            usage=AiUsage(
                provider=self.name,
                model="stub-deterministic",
                input_tokens=sum(len(c.text) for c in request.content) // 4,
                output_tokens=32,
            ),
            evidence=tuple(c.source_id or c.source for c in request.content),
        )

    @staticmethod
    def _seed(request: AiRequest[Any]) -> int:
        material = request.task.value + request.instruction
        material += "".join(c.text for c in request.content)
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return int(digest[:8], 16)


def _build(model: type[BaseModel], seed: int) -> Any:
    """Строит экземпляр модели, заполняя поля значениями по типу."""
    values: dict[str, Any] = {}
    for name, info in model.model_fields.items():
        values[name] = _value_for(info, name, seed)
    return model.model_validate(values)


def _value_for(info: FieldInfo, name: str, seed: int) -> Any:
    # У необязательного поля берём его значение по умолчанию. Проверять надо
    # именно is_required(): у обязательного поля default равен
    # PydanticUndefined, а не None и не Ellipsis.
    if not info.is_required():
        return info.get_default(call_default_factory=True)

    annotation = info.annotation
    origin = get_origin(annotation)

    # Optional[X] — заглушка предпочитает заполнить, а не оставить пустым:
    # пустые поля скрыли бы ошибки в разметке интерфейса.
    if origin is not None:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if args:
            annotation = args[0]
            origin = get_origin(annotation)

    if origin in (list, tuple, set):
        inner = get_args(annotation)
        if inner and isinstance(inner[0], type) and issubclass(inner[0], BaseModel):
            return [_build(inner[0], seed)]
        return []
    if origin is dict:
        return {}

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _build(annotation, seed)

    if annotation is bool:
        return bool(seed % 2)
    if annotation is int:
        return seed % 100
    if annotation is float:
        return round((seed % 100) / 100, 2)
    if annotation is str:
        return f"stub:{name}"

    # Перечисления: берём первое значение — детерминированно и валидно.
    choices = getattr(annotation, "__members__", None)
    if choices:
        return next(iter(choices.values()))

    return f"stub:{name}"
