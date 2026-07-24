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

# Прайсинг v3: число сцен ФИКСИРОВАНО выбранной длительностью ролика
# (pricing.scene_count_for_duration), а не выбирается моделью. Схема и промпт
# строятся под это N в submit() — модель обязана вернуть ровно N сцен, каждый
# клип детерминирован (pricing.clip_seconds_for). Схема требует ровно N сцен.

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


def _scene_keys(scene_count: int) -> tuple[str, ...]:
    return tuple(f"scene_{i}" for i in range(1, scene_count + 1))


def _storyboard_schema(scene_count: int) -> dict:
    # Объект с фиксированными ключами scene_1..scene_N, ВСЕ required:
    # additionalProperties=False не даёт вернуть больше N, required — меньше.
    # minItems/maxItems grammar-constrained decoding не поддерживает.
    keys = _scene_keys(scene_count)
    return {
        "type": "object",
        # $ref вместо N копий SCENE_SCHEMA — экономит input-токены.
        "$defs": {"scene": SCENE_SCHEMA},
        "properties": {key: {"$ref": "#/$defs/scene"} for key in keys},
        "required": list(keys),
        "additionalProperties": False,
    }


def _system_prompt(scene_count: int, clip_seconds: int) -> str:
    style = get_settings().image_style_prompt.strip()
    return (
        f"Ты сценарист коротких анимированных роликов. По сюжету пользователя составь "
        f"раскадровку ровно из {scene_count} сцен для вертикального (9:16) ролика. "
        f"Каждая сцена — это клип примерно {clip_seconds} секунд; закадровый текст "
        f"(script_text) должен произноситься примерно за это время, не длиннее. "
        f"Заполни ключи scene_1..scene_{scene_count} подряд, все до одного, равномерно "
        f"распределив сюжет. Для каждой сцены дай: script_text (короткая реплика или "
        f"закадровый текст на том же языке, что и исходный сюжет), image_prompt "
        f"(детальное описание кадра на английском для text-to-image модели), "
        f"camera_movement (короткое описание движения камеры на английском) и "
        f"mood_notes (тон/настроение сцены на английском). "
        f"ВАЖНО про стиль: все кадры — в едином мультяшном/диснеевском стиле, БЕЗ "
        f"фотореализма. Каждый image_prompt описывай именно как рисованную "
        f"мультипликацию в этом стиле: {style}"
    )


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
        # Прокси вне РФ для обхода гео-блока Anthropic (см. settings.anthropic_proxy_url).
        self._proxy = settings.anthropic_proxy_url or None

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

        # Прайсинг v3: число сцен и длина клипа детерминированы длительностью ролика.
        from toontales_ai.orchestration.pricing import clip_seconds_for, scene_count_for_duration

        duration_seconds = int(payload.payload.get("duration_seconds", 0)) or 30
        scene_count = scene_count_for_duration(duration_seconds)
        clip_seconds = clip_seconds_for(duration_seconds, scene_count)
        scene_keys = _scene_keys(scene_count)

        body = {
            "model": self._model,
            "max_tokens": 4096,
            "system": _system_prompt(scene_count, clip_seconds),
            "messages": [{"role": "user", "content": script_text}],
            "output_config": {"format": {"type": "json_schema", "schema": _storyboard_schema(scene_count)}},
        }

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, proxy=self._proxy) as client:
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

        # Объект scene_1..scene_N -> упорядоченный список. Схема требует ВСЕ N ключей
        # (required=all), но проверяем и на парсинге: меньше N сцен изменило бы
        # фактическую длительность после фиксации цены (P1, ревью денежных путей) —
        # клипы перераспределятся, но при недоборе сцен теряется маржа/качество.
        # Лучше отклонить и ретраить, чем собрать не тот ролик за фикс-цену.
        scenes = [parsed[key] for key in scene_keys if key in parsed]
        if len(scenes) != scene_count:
            raise AnthropicAPIError(
                f"Anthropic returned {len(scenes)} scenes, expected exactly {scene_count}"
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
