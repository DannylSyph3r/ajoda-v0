import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DirectDebitMandate(Base, TimestampMixin):
    __tablename__ = "direct_debit_mandates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('INITIATED','PENDING','PENDING_AUTHORIZATION',"
            "'PENDING_ACTIVATION','ACTIVE','ACTIVATED','AUTHORIZATION_EXPIRED',"
            "'EXPIRED','CANCELLED','SUSPENDED')",
            name="ck_direct_debit_mandates_status",
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
    # Our own reference, sent as `mandateReference` on create.
    mandate_reference: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True
    )
    # Monnify's generated code (e.g. "MTDD|..."), the id every subsequent call
    # (debit, cancel) actually uses. Null until the create call responds.
    mandate_code: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="INITIATED", server_default="INITIATED"
    )
    # Snapshot of the cooperative's contribution_amount_kobo at setup time — this is
    # the amount the mandate was actually authorized for. A later settings change
    # invalidates it (see CooperativeService.update_settings cascade).
    mandate_amount_kobo: Mapped[int] = mapped_column(BigInteger, nullable=False)
    authorization_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mandate_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    mandate_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    authorized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # A debit attempt in flight — set when a scheduled debit is initiated, cleared
    # once resolved (paid or failed). The reconciliation cron polls every mandate
    # with a non-null reference here to settle it (poll-only, no webhook — CLAUDE
    # §11 decision, revisit if Monnify confirms a debit-outcome webhook exists).
    pending_debit_reference: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    pending_debit_contribution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contributions.id"), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
