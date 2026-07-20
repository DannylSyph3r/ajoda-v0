"""withdrawal disbursement columns

Adds the Monnify disbursement state machine + transfer fields to `withdrawals`
and makes pool_balance_after nullable (the pool is now debited at COMPLETED, not
at record time).

Revision ID: b7f3a9c2e1d4
Revises: 9153fb5d44ed
Create Date: 2026-07-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f3a9c2e1d4'
down_revision: Union[str, None] = '9153fb5d44ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'withdrawals',
        sa.Column('status', sa.String(length=30), nullable=False,
                  server_default='INITIATED'),
    )
    op.add_column('withdrawals', sa.Column('transfer_reference', sa.String(length=100), nullable=True))
    op.add_column('withdrawals', sa.Column('monnify_transaction_reference', sa.String(length=100), nullable=True))
    op.add_column('withdrawals', sa.Column('destination_account_number', sa.String(length=20), nullable=True))
    op.add_column('withdrawals', sa.Column('destination_bank_code', sa.String(length=10), nullable=True))
    op.add_column('withdrawals', sa.Column('destination_account_name', sa.String(length=255), nullable=True))
    op.add_column('withdrawals', sa.Column('failure_reason', sa.Text(), nullable=True))
    op.add_column('withdrawals', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

    op.alter_column('withdrawals', 'pool_balance_after', existing_type=sa.BigInteger(), nullable=True)

    op.create_unique_constraint('uq_withdrawals_transfer_reference', 'withdrawals', ['transfer_reference'])
    op.create_check_constraint(
        'ck_withdrawals_status',
        'withdrawals',
        "status IN ('INITIATED','PENDING_AUTHORIZATION','PROCESSING','COMPLETED','FAILED')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_withdrawals_status', 'withdrawals', type_='check')
    op.drop_constraint('uq_withdrawals_transfer_reference', 'withdrawals', type_='unique')
    op.alter_column('withdrawals', 'pool_balance_after', existing_type=sa.BigInteger(), nullable=False)
    op.drop_column('withdrawals', 'updated_at')
    op.drop_column('withdrawals', 'failure_reason')
    op.drop_column('withdrawals', 'destination_account_name')
    op.drop_column('withdrawals', 'destination_bank_code')
    op.drop_column('withdrawals', 'destination_account_number')
    op.drop_column('withdrawals', 'monnify_transaction_reference')
    op.drop_column('withdrawals', 'transfer_reference')
    op.drop_column('withdrawals', 'status')
