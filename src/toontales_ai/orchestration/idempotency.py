import hashlib
import uuid

from toontales_ai.domain.enums import Stage


def task_idempotency_key(
    *,
    run_id: uuid.UUID,
    stage: Stage,
    scene_id: uuid.UUID | None,
    input_version: str,
) -> str:
    """Стабильный ключ логической операции: hash(run_id + stage + scene_id + input_version).
    Номер технической попытки НЕ входит в ключ (review.md §1) — тот хранится
    отдельно в Task.attempt_no."""
    raw = f"{run_id}:{stage.value}:{scene_id or ''}:{input_version}"
    return hashlib.sha256(raw.encode()).hexdigest()


def credit_hold_key(task_id: uuid.UUID) -> str:
    return f"hold:{task_id}"


def credit_charge_key(task_id: uuid.UUID) -> str:
    return f"charge:{task_id}"


def credit_release_key(task_id: uuid.UUID) -> str:
    return f"release:{task_id}"


def input_hash(payload: dict) -> str:
    import json

    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
