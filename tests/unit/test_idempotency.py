import uuid

from toontales_ai.domain.enums import Stage
from toontales_ai.orchestration.idempotency import task_idempotency_key


def test_idempotency_key_stable_across_repeated_calls():
    run_id = uuid.uuid4()
    scene_id = uuid.uuid4()

    key1 = task_idempotency_key(run_id=run_id, stage=Stage.IMAGE, scene_id=scene_id, input_version="v1")
    key2 = task_idempotency_key(run_id=run_id, stage=Stage.IMAGE, scene_id=scene_id, input_version="v1")

    assert key1 == key2


def test_idempotency_key_does_not_depend_on_attempt():
    """Регрессия на review.md §1: attempt не должен входить в ключ — повторная
    попытка обязана дать тот же ключ, а не создавать новый платный job."""
    run_id = uuid.uuid4()
    scene_id = uuid.uuid4()

    key_attempt_1 = task_idempotency_key(run_id=run_id, stage=Stage.VIDEO, scene_id=scene_id, input_version="v1")
    # Симулируем повторную попытку — при том же input_version ключ обязан совпасть,
    # т.к. сигнатура функции вообще не принимает attempt.
    key_attempt_2 = task_idempotency_key(run_id=run_id, stage=Stage.VIDEO, scene_id=scene_id, input_version="v1")

    assert key_attempt_1 == key_attempt_2


def test_idempotency_key_changes_with_input_version():
    run_id = uuid.uuid4()
    scene_id = uuid.uuid4()

    key_v1 = task_idempotency_key(run_id=run_id, stage=Stage.IMAGE, scene_id=scene_id, input_version="v1")
    key_v2 = task_idempotency_key(run_id=run_id, stage=Stage.IMAGE, scene_id=scene_id, input_version="v2")

    assert key_v1 != key_v2


def test_idempotency_key_differs_per_run_stage_scene():
    base = dict(run_id=uuid.uuid4(), stage=Stage.IMAGE, scene_id=uuid.uuid4(), input_version="v1")
    key_base = task_idempotency_key(**base)

    assert task_idempotency_key(**{**base, "run_id": uuid.uuid4()}) != key_base
    assert task_idempotency_key(**{**base, "stage": Stage.VIDEO}) != key_base
    assert task_idempotency_key(**{**base, "scene_id": uuid.uuid4()}) != key_base
