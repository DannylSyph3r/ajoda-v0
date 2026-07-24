import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Contribution(Base, TimestampMixin):
    __tablename__ = "contributions"
    __table_args__ = (
        UniqueConstraint("member_id", "period_id"),
        CheckConstraint(
            "status IN ('unpaid','paid','refunded')", name="ck_contributions_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    cooperative_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cooperatives.id"), nullable=False
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contribution_periods.id"), nullable=False
    )
    pool_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pools.id"), nullable=True
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unpaid")
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The Monnify reference that settled this contribution — a hosted-checkout
    # PendingTransaction.reference (may cover several periods in one payment; a
    # refund against it can still be partial for just this contribution's amount)
    # or a direct-debit payment_reference. Set only when status becomes 'paid';
    # required for a refund to be initiated against this row.
    settlement_reference: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )