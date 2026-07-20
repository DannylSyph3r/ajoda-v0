import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Withdrawal(Base, TimestampMixin):
    __tablename__ = "withdrawals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('INITIATED','PENDING_AUTHORIZATION','PROCESSING',"
            "'COMPLETED','FAILED')",
            name="ck_withdrawals_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cooperative_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cooperatives.id"), nullable=False
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    authorized_by_member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    # Nullable now: the pool is debited at COMPLETED (money actually left), not at
    # initiation, so the post-debit balance is unknown until then.
    pool_balance_after: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # --- Disbursement (Phase 3) ---
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="INITIATED", server_default="INITIATED"
    )
    # Our own transfer reference (AJODA-DISB-...), one per withdrawal, reused on retry.
    transfer_reference: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True
    )
    # Monnify's own transactionReference, captured on terminal status for audit/display.
    monnify_transaction_reference: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    destination_account_number: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    destination_bank_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    destination_account_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
