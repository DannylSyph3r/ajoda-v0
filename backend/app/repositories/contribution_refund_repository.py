from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contribution_refund import ContributionRefund


class ContributionRefundRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        contribution_id: UUID,
        requested_by_member_id: UUID,
        amount: int,
        reason: str,
        refund_type: str,
        refund_reference: str,
        original_transaction_reference: str,
    ) -> ContributionRefund:
        refund = ContributionRefund(
            contribution_id=contribution_id,
            requested_by_member_id=requested_by_member_id,
            amount=amount,
            reason=reason,
            refund_type=refund_type,
            refund_reference=refund_reference,
            original_transaction_reference=original_transaction_reference,
            status="PENDING",
        )
        self.db.add(refund)
        await self.db.flush()
        return refund

    async def get_by_id(self, refund_id: UUID) -> ContributionRefund | None:
        result = await self.db.execute(
            select(ContributionRefund).where(ContributionRefund.id == refund_id)
        )
        return result.scalar_one_or_none()

    async def get_by_reference(self, refund_reference: str) -> ContributionRefund | None:
        result = await self.db.execute(
            select(ContributionRefund).where(
                ContributionRefund.refund_reference == refund_reference
            )
        )
        return result.scalar_one_or_none()

    async def get_total_refunded_for_contribution(self, contribution_id: UUID) -> int:
        """Sum of COMPLETED refunds already applied to a contribution — used to
        decide whether a new refund would exceed the original amount and whether
        cumulative refunds have reached the full amount."""
        result = await self.db.execute(
            select(ContributionRefund.amount).where(
                and_(
                    ContributionRefund.contribution_id == contribution_id,
                    ContributionRefund.status == "COMPLETED",
                )
            )
        )
        return sum(row[0] for row in result.all())

    async def complete_if_pending(
        self, refund_id: UUID, monnify_reference: str
    ) -> bool:
        """Atomic PENDING -> COMPLETED transition. Returns True only if this call
        performed it, so a duplicate poll/webhook cannot double-apply the pool debit."""
        result = await self.db.execute(
            update(ContributionRefund)
            .where(
                and_(
                    ContributionRefund.id == refund_id,
                    ContributionRefund.status == "PENDING",
                )
            )
            .values(
                status="COMPLETED",
                monnify_reference=monnify_reference or None,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(ContributionRefund.id)
        )
        return result.scalar_one_or_none() is not None

    async def fail_if_pending(self, refund_id: UUID, reason: str) -> bool:
        result = await self.db.execute(
            update(ContributionRefund)
            .where(
                and_(
                    ContributionRefund.id == refund_id,
                    ContributionRefund.status == "PENDING",
                )
            )
            .values(
                status="FAILED",
                failure_reason=(reason or "Refund failed")[:500],
                updated_at=datetime.now(timezone.utc),
            )
            .returning(ContributionRefund.id)
        )
        return result.scalar_one_or_none() is not None
