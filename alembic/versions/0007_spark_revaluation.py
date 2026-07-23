"""revalue spark balances after pricing v2

Revision ID: 0007_spark_revaluation
Revises: 0006_task_price
Create Date: 2026-07-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_spark_revaluation"
down_revision: Union[str, None] = "0006_task_price"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Константы заморожены здесь намеренно и НЕ импортируются из orchestration.pricing:
# миграция обязана дать один и тот же результат через год, когда тарифы уже уедут.
#
# OLD — сколько искр стоил ролик из 6 сцен в прайсинге v1 (STAGE_COST:
# storyboard 50 + 6 × (image 30 + video 200 + audio 20 + lipsync 20) + composition 10).
# NEW — сколько стоит такой же ролик в v2: фактическая себестоимость $3.2744
# при номинале 1 искра = $0.001.
#
# Пересчёт сохраняет покупательную способность: сколько роликов баланс давал
# сделать до перехода, столько же даёт после.
OLD_RUN_SPARKS = 1680
NEW_RUN_SPARKS = 3275

NON_TERMINAL_STATUSES = "('pending', 'submitting', 'waiting_provider', 'processing', 'retry_scheduled')"


def _fail_if_pipeline_not_drained() -> None:
    """Незавершённые задачи держат холд в СТАРОЙ шкале, а миграция масштабирует
    только свободный баланс. Досчитать холды нельзя: они уже списаны с баланса, и
    увеличение task.cost вернуло бы при release больше, чем удерживалось.
    Поэтому пайплайн обязан быть пуст — иначе пользователь теряет покупательную
    способность удержанных искр, а мы теряем маржу на клампе старым холдом.

    Проверка, а не строчка в README: инструкцию можно пропустить, исключение — нет.
    """
    conn = op.get_bind()
    stuck = conn.execute(
        sa.text(f"SELECT count(*) FROM tasks WHERE status::text IN {NON_TERMINAL_STATUSES}")
    ).scalar_one()
    if stuck:
        raise RuntimeError(
            f"cannot revalue balances: {stuck} tasks are still in flight. "
            "Stop worker/beat, wait for the pipeline to drain, then run the migration. "
            "See deploy/README.md -> «Выкатка прайсинга v2»."
        )


def upgrade() -> None:
    _fail_if_pipeline_not_drained()

    # Одна операция вместо двух: два отдельных statement видят разные снапшоты, и
    # изменение баланса приложением между ними развело бы ledger с балансом.
    #
    # UPDATE прибавляет дельту, а не выставляет пересчитанное значение: сложение
    # остаётся корректным и при конкурентном изменении строки (Postgres перечитает
    # её под блокировкой), присваивание затёрло бы чужую операцию.
    #
    # Строки для UPDATE берутся ТОЛЬКО из RETURNING вставки: повторный ручной
    # прогон не вставит проводку (ON CONFLICT) и потому не тронет баланс дважды.
    op.execute(
        f"""
        WITH revalued AS (
            INSERT INTO credit_transactions
                (id, user_id, run_id, task_id, type, amount, idempotency_key, created_at)
            SELECT
                gen_random_uuid(), u.id, NULL, NULL, 'adjustment',
                ROUND(u.credit_balance * {NEW_RUN_SPARKS}.0 / {OLD_RUN_SPARKS}.0) - u.credit_balance,
                'revaluation:pricing_v2:' || u.id,
                now()
            FROM users u
            WHERE u.credit_balance > 0
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING user_id, amount
        )
        UPDATE users u
        SET credit_balance = u.credit_balance + revalued.amount
        FROM revalued
        WHERE u.id = revalued.user_id
        """
    )


def downgrade() -> None:
    # Симметрично upgrade: снимаем ровно ту дельту, которую начисляли, и только с
    # тех пользователей, у кого проводка действительно есть. Обратный пересчёт
    # умножением не восстановил бы исходные значения — ROUND необратим.
    op.execute(
        """
        WITH reverted AS (
            DELETE FROM credit_transactions
            WHERE idempotency_key LIKE 'revaluation:pricing_v2:%'
            RETURNING user_id, amount
        )
        UPDATE users u
        SET credit_balance = u.credit_balance - reverted.amount
        FROM reverted
        WHERE u.id = reverted.user_id
        """
    )
