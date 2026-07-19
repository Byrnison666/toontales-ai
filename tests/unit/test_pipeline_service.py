import uuid

from toontales_ai.domain.enums import Stage
from toontales_ai.orchestration.pipeline_service import plan_next_tasks


def test_video_not_planned_until_image_predecessor_satisfied():
    run_id = uuid.uuid4()
    scene_id = uuid.uuid4()

    plans = plan_next_tasks(
        run_id=run_id,
        completed_stage=Stage.IMAGE,
        scene_id=scene_id,
        input_version="v1",
        predecessor_satisfied={Stage.IMAGE: True},
    )

    assert [p.stage for p in plans] == [Stage.VIDEO]


def test_lipsync_join_requires_both_video_and_audio():
    run_id = uuid.uuid4()
    scene_id = uuid.uuid4()

    # video завершился, audio ещё нет — lipsync не должен планироваться.
    plans_partial = plan_next_tasks(
        run_id=run_id,
        completed_stage=Stage.VIDEO,
        scene_id=scene_id,
        input_version="v1",
        predecessor_satisfied={Stage.VIDEO: True, Stage.AUDIO: False},
    )
    assert plans_partial == []

    # оба предшественника готовы — lipsync планируется.
    plans_ready = plan_next_tasks(
        run_id=run_id,
        completed_stage=Stage.VIDEO,
        scene_id=scene_id,
        input_version="v1",
        predecessor_satisfied={Stage.VIDEO: True, Stage.AUDIO: True},
    )
    assert [p.stage for p in plans_ready] == [Stage.LIPSYNC]


def test_composition_is_run_level_not_scene_scoped():
    run_id = uuid.uuid4()
    scene_id = uuid.uuid4()

    plans = plan_next_tasks(
        run_id=run_id,
        completed_stage=Stage.LIPSYNC,
        scene_id=scene_id,
        input_version="v1",
        predecessor_satisfied={Stage.LIPSYNC: True},
    )

    assert len(plans) == 1
    assert plans[0].stage == Stage.COMPOSITION
    assert plans[0].scene_id is None  # run-level join, не привязан к конкретной сцене


def test_plan_idempotency_key_is_deterministic_for_same_scene():
    run_id = uuid.uuid4()
    scene_id = uuid.uuid4()

    plans_1 = plan_next_tasks(
        run_id=run_id,
        completed_stage=Stage.IMAGE,
        scene_id=scene_id,
        input_version="v1",
        predecessor_satisfied={Stage.IMAGE: True},
    )
    plans_2 = plan_next_tasks(
        run_id=run_id,
        completed_stage=Stage.IMAGE,
        scene_id=scene_id,
        input_version="v1",
        predecessor_satisfied={Stage.IMAGE: True},
    )

    assert plans_1[0].idempotency_key == plans_2[0].idempotency_key
