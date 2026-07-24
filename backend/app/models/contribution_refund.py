import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ContributionRefund(Base, TimestampMixin):
    __tablename__ = "contribution_refunds"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','COMPLETED','FAILED')",
            name="ck_contribution_refunds_status",
        ),
        CheckConstraint(
            "refund_type IN ('PARTIAL_REFUND','FULL_REFUND')",
            name="ck_contribution_refunds_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    contribution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contributions.id"), nullable=False
    )
    requested_by_member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    refund_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Our own reference, sent as `refundReference`.
    refund_reference: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True
    )
    # Monnify's own tracking reference (the `reference` field in their response,
    # e.g. "TRFD|...") and the original contribution's transactionReference being
    # refunded — both captured for audit/display.
    monnify_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    original_transaction_reference: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING", server_default="PENDING"
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
