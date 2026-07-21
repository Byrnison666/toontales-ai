"""Реальный Anthropic Claude адаптер для storyboard_generation (заменяет
StoryboardStubAdapter). Контракт — platform.claude.com/docs/en/build-with-claude/
structured-outputs (context7 был недоступен в этой сессии — OAuth не пройден;
документация получена прямым WebFetch):

    POST https://api.anthropic.com/v1/messages
    Headers: x-api-key, anthropic-version, Content-Type: application/json
    Body: {"model": ..., "max_tokens": ..., "messages": [...],
           "output_config": {"format": {"type": "json_schema", "schema": {...}}}}
    200 -> response.content[0].text содержит JSON, гарантированно соответствующий schema
    (grammar-constrained decoding — не tool-use эмуляция, доп. постобработка не нужна).

Ответ синхронный — эндпоинт не возвращает job id, поэтому submit() сразу отдаёт
готовый результат (как ElevenLabsAdapter), а poll() не реализован."""

import json

import httpx

from toontales_ai.adapters.base import ProviderJobResult, ProviderSubmission, StageInput
from toontales_ai.config.settings import get_settings
from toontales_ai.domain.enums import ProviderJobStatus

ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_API_VERSION = "2023-06-01"
REQUEST_TIMEOUT_SECONDS = 60.0

# v2.md ориентир: "до 5-6 сцен на 30-секундный ролик". Верхняя граница совпадает
# с MAX_ASSUMED_SCENES (pipeline_async.py) — max_budget рассчитан именно на 6 сцен,
# больше модель предлагать не должна (иначе _materialize_scenes_and_fanout обрежет
# лишние молча, а деньги за них не спишутся, но раскадровка не совпадёт с тем, что
# видела модель).
MIN_SCENES = 2
MAX_SCENES = 6

SCENE_SCHEMA = {
    "type": "object",
    "properties": {
        "script_text": {"type": "string", "description": "Реплика/закадровый текст для этой сцены"},
        "image_prompt": {"type": "string", "description": "Описание кадра для text-to-image генератора"},
        "camera_movement": {"type": "string", "description": "Движение камеры, напр. 'slow pan left', 'static'"},
        "mood_notes": {"type": "string", "description": "Настроение/тон сцены"},
    },
    "required": ["script_text", "image_prompt", "camera_movement", "mood_notes"],
    "additionalProperties": False,
}

STORYBOARD_SCHEMA = {
    "type": "object",
    "properties": {
        # minItems/maxItems > 1 не поддерживаются grammar-constrained decoding
        # ("'minItems' values other than 0 or 1 are not supported" — живой 400 от
        # API). Диапазон MIN_SCENES..MAX_SCENES задаётся текстом в SYSTEM_PROMPT
        # и проверяется программно в submit() после разбора ответа.
        "scenes": {"type": "array", "items": SCENE_SCHEMA},
    },
    "required": ["scenes"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "Ты сценарист коротких анимированных роликов. По сюжету пользователя составь "
    "раскадровку из {min_scenes}-{max_scenes} сцен для 20-30-секундного вертикального "
    "(9:16) ролика. Для каждой сцены дай: script_text (короткая реплика или закадровый "
    "текст на том же языке, что и исходный сюжет), image_prompt (детальное описание кадра "
    "на английском для text-to-image модели), camera_movement (короткое описание движения "
    "камеры на английском) и mood_notes (тон/настроение сцены на английском)."
).format(min_scenes=MIN_SCENES, max_scenes=MAX_SCENES)


class AnthropicConfigError(Exception):
    """TOONTALES_ANTHROPIC_API_KEY не задан — не транзиентная, не подлежащая
    retry ошибка конфигурации окружения."""

    pass


class AnthropicAPIError(Exception):
    """Не-2xx ответ Anthropic (кроме сетевых транспортных ошибок — те
    httpx.TransportError, см. workers/tasks.py TRANSIENT_ERRORS), пустой
    script_text или ответ, не прошедший разбор JSON."""

    pass


class AnthropicTransientError(AnthropicAPIError):
    """429 (rate limit) и 5xx — временная перегрузка/сбой на стороне Anthropic,
    а не ошибка запроса. Тот же класс проблемы, что у RunwayTransientError/
    SyncTransientError."""

    pass


def _raise_for_status(response: httpx.Response, *, context: str) -> None:
    if response.status_code == 429 or response.status_code >= 500:
        raise AnthropicTransientError(f"{context}: {response.status_code} {response.text[:500]}")
    if response.status_code >= 400:
        raise AnthropicAPIError(f"{context}: {response.status_code} {response.text[:500]}")


class AnthropicStoryboardAdapter:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise AnthropicConfigError("TOONTALES_ANTHROPIC_API_KEY must be set to use AnthropicStoryboardAdapter")
        self._api_key = settings.anthropic_api_key
        self._model = settings.anthropic_model

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "Content-Type": "application/json",
        }

    async def submit(self, payload: StageInput, *, idempotency_key: str) -> ProviderSubmission:
        script_text = str(payload.payload.get("script_text", "")).strip()
        if not script_text:
            raise AnthropicAPIError("empty script_text: nothing to break into scenes")

        body = {
            "model": self._model,
            "max_tokens": 4096,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": script_text}],
            "output_config": {"format": {"type": "json_schema", "schema": STORYBOARD_SCHEMA}},
        }

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{ANTHROPIC_BASE_URL}/messages", headers=self._headers(), json=body)

        _raise_for_status(response, context="Anthropic messages request failed")

        data = response.json()
        content = data.get("content") or []
        text_block = next((block.get("text") for block in content if block.get("type") == "text"), None)
        if not text_block:
            raise AnthropicAPIError(f"Anthropic response missing text content: {data}")

        try:
            parsed = json.loads(text_block)
        except json.JSONDecodeError as exc:
            raise AnthropicAPIError(f"Anthropic structured output is not valid JSON: {exc}") from exc

        scenes = parsed.get("scenes")
        if not scenes:
            raise AnthropicAPIError(f"Anthropic response has no scenes: {parsed}")
        if not (MIN_SCENES <= len(scenes) <= MAX_SCENES):
            raise AnthropicAPIError(
                f"Anthropic returned {len(scenes)} scenes, expected {MIN_SCENES}-{MAX_SCENES}"
            )

        result = ProviderJobResult(
            provider_job_id=None,
            status=ProviderJobStatus.SUCCEEDED,
            artifacts=({"scenes": scenes},),
            usage={
                "input_tokens": data["usage"]["input_tokens"],
                "output_tokens": data["usage"]["output_tokens"],
            },
        )
        return ProviderSubmission(provider_job_id=None, status=ProviderJobStatus.SUCCEEDED, result=result)

    async def poll(self, provider_job_id: str) -> ProviderJobResult:
        raise NotImplementedError("AnthropicStoryboardAdapter завершает работу синхронно в submit()")
