"""contribution refunds

Adds the contribution_refunds table and extends contributions.status to allow
'refunded' (full refunds only — a partial refund leaves the contribution 'paid').

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The Monnify reference that settled a contribution — needed to initiate a
    # refund against it. Nullable/backfill-free: existing paid rows simply won't
    # be refundable until settled again; nothing reads this column until refund
    # does.
    op.add_column(
        'contributions',
        sa.Column('settlement_reference', sa.String(length=100), nullable=True),
    )

    op.create_table(
        'contribution_refunds',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('contribution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('contributions.id'), nullable=False),
        sa.Column('requested_by_member_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('members.id'), nullable=False),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('refund_type', sa.String(length=20), nullable=False),
        sa.Column('refund_reference', sa.String(length=100), nullable=False),
        sa.Column('monnify_reference', sa.String(length=100), nullable=True),
        sa.Column('original_transaction_reference', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='PENDING'),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        'uq_contribution_refunds_refund_reference',
        'contribution_refunds',
        ['refund_reference'],
    )
    op.create_check_constraint(
        'ck_contribution_refunds_status',
        'contribution_refunds',
        "status IN ('PENDING','COMPLETED','FAILED')",
    )
    op.create_check_constraint(
        'ck_contribution_refunds_type',
        'contribution_refunds',
        "refund_type IN ('PARTIAL_REFUND','FULL_REFUND')",
    )
    op.create_index(
        'idx_contribution_refunds_contribution',
        'contribution_refunds',
        ['contribution_id'],
    )

    op.drop_constraint('ck_contributions_status', 'contributions', type_='check')
    op.create_check_constraint(
        'ck_contributions_status',
        'contributions',
        "status IN ('unpaid','paid','refunded')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_contributions_status', 'contributions', type_='check')
    op.create_check_constraint(
        'ck_contributions_status',
        'contributions',
        "status IN ('unpaid','paid')",
    )
    op.drop_index('idx_contribution_refunds_contribution', table_name='contribution_refunds')
    op.drop_table('contribution_refunds')
    op.drop_column('contributions', 'settlement_reference')
