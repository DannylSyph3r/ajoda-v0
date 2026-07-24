"""direct debit mandates

Adds the direct_debit_mandates table for the recurring-contribution auto-pay
feature (Monnify Direct Debit).

Revision ID: d4e5f6a7b8c9
Revises: b7f3a9c2e1d4
Create Date: 2026-07-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'b7f3a9c2e1d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'direct_debit_mandates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('member_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('members.id'), nullable=False),
        sa.Column('cooperative_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('cooperatives.id'), nullable=False),
        sa.Column('mandate_reference', sa.String(length=100), nullable=False),
        sa.Column('mandate_code', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='INITIATED'),
        sa.Column('mandate_amount_kobo', sa.BigInteger(), nullable=False),
        sa.Column('authorization_link', sa.String(length=500), nullable=True),
        sa.Column('mandate_start_date', sa.Date(), nullable=False),
        sa.Column('mandate_end_date', sa.Date(), nullable=False),
        sa.Column('authorized_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancellation_reason', sa.String(length=255), nullable=True),
        sa.Column('pending_debit_reference', sa.String(length=100), nullable=True),
        sa.Column('pending_debit_contribution_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('contributions.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        'uq_direct_debit_mandates_mandate_reference',
        'direct_debit_mandates',
        ['mandate_reference'],
    )
    op.create_unique_constraint(
        'uq_direct_debit_mandates_mandate_code',
        'direct_debit_mandates',
        ['mandate_code'],
    )
    op.create_check_constraint(
        'ck_direct_debit_mandates_status',
        'direct_debit_mandates',
        "status IN ('INITIATED','PENDING','PENDING_AUTHORIZATION',"
        "'PENDING_ACTIVATION','ACTIVE','ACTIVATED','AUTHORIZATION_EXPIRED',"
        "'EXPIRED','CANCELLED','SUSPENDED')",
    )
    # Bounded lookups this feature actually runs: "does this member have an active
    # mandate for this coop" and "cascade-cancel every mandate for this coop".
    op.create_index(
        'idx_direct_debit_mandates_member_coop',
        'direct_debit_mandates',
        ['member_id', 'cooperative_id'],
    )
    op.create_index(
        'idx_direct_debit_mandates_coop_status',
        'direct_debit_mandates',
        ['cooperative_id', 'status'],
    )


def downgrade() -> None:
    op.drop_index('idx_direct_debit_mandates_coop_status', table_name='direct_debit_mandates')
    op.drop_index('idx_direct_debit_mandates_member_coop', table_name='direct_debit_mandates')
    op.drop_table('direct_debit_mandates')
