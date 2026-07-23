"""revalue spark balances after pricing v2

Revision ID: 0007_spark_revaluation
Revises: 0006_task_price
Create Date: 2026-07-24

"""
from typing import Sequence, Union

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


def upgrade() -> None:
    # Баланс меняем проводкой, а не молча: credit_transactions — append-only
    # ledger, и баланс обязан сходиться с суммой транзакций. Прямой UPDATE без
    # ADJUSTMENT развалил бы эту сверку.
    op.execute(
        f"""
        INSERT INTO credit_transactions (id, user_id, run_id, task_id, type, amount, idempotency_key, created_at)
        SELECT
            gen_random_uuid(), u.id, NULL, NULL, 'adjustment',
            ROUND(u.credit_balance * {NEW_RUN_SPARKS}.0 / {OLD_RUN_SPARKS}.0) - u.credit_balance,
            'revaluation:pricing_v2:' || u.id,
            now()
        FROM users u
        WHERE u.credit_balance > 0
        ON CONFLICT (idempotency_key) DO NOTHING
        """
    )
    op.execute(
        f"""
        UPDATE users
        SET credit_balance = ROUND(credit_balance * {NEW_RUN_SPARKS}.0 / {OLD_RUN_SPARKS}.0)
        WHERE credit_balance > 0
        """
    )


def downgrade() -> None:
    # Обратный пересчёт не восстановит исходные балансы точно: ROUND в upgrade
    # необратим. Возвращаем то же соотношение и снимаем проводку, чтобы ledger
    # снова сходился.
    op.execute(
        f"""
        UPDATE users
        SET credit_balance = ROUND(credit_balance * {OLD_RUN_SPARKS}.0 / {NEW_RUN_SPARKS}.0)
        WHERE credit_balance > 0
        """
    )
    op.execute("DELETE FROM credit_transactions WHERE idempotency_key LIKE 'revaluation:pricing_v2:%'")
