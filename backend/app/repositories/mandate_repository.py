from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import MANDATE_TERMINAL_STATUSES
from app.models.direct_debit_mandate import DirectDebitMandate


class MandateRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        member_id: UUID,
        cooperative_id: UUID,
        mandate_reference: str,
        mandate_amount_kobo: int,
        mandate_start_date,
        mandate_end_date,
    ) -> DirectDebitMandate:
        mandate = DirectDebitMandate(
            member_id=member_id,
            cooperative_id=cooperative_id,
            mandate_reference=mandate_reference,
            mandate_amount_kobo=mandate_amount_kobo,
            mandate_start_date=mandate_start_date,
            mandate_end_date=mandate_end_date,
        )
        self.db.add(mandate)
        await self.db.flush()
        return mandate

    async def get_by_id(self, mandate_id: UUID) -> DirectDebitMandate | None:
        result = await self.db.execute(
            select(DirectDebitMandate).where(DirectDebitMandate.id == mandate_id)
        )
        return result.scalar_one_or_none()

    async def get_active_mandate(
        self, member_id: UUID, coop_id: UUID
    ) -> DirectDebitMandate | None:
        """The member's current non-terminal mandate for this coop, if any (most
        recently created — a member can only usefully have one live mandate per
        coop, but a cancelled/expired one may still exist as history)."""
        result = await self.db.execute(
            select(DirectDebitMandate)
            .where(
                DirectDebitMandate.member_id == member_id,
                DirectDebitMandate.cooperative_id == coop_id,
                DirectDebitMandate.status.notin_(MANDATE_TERMINAL_STATUSES),
            )
            .order_by(DirectDebitMandate.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_non_terminal_for_coop(
        self, coop_id: UUID
    ) -> list[DirectDebitMandate]:
        """Every mandate for this coop that isn't already dead — the cascade-cancel
        target set. Bounded: a coop's own mandates are a small set by construction."""
        result = await self.db.execute(
            select(DirectDebitMandate).where(
                DirectDebitMandate.cooperative_id == coop_id,
                DirectDebitMandate.status.notin_(MANDATE_TERMINAL_STATUSES),
            )
        )
        return list(result.scalars().all())

    async def get_active_mandates_for_coop(
        self, coop_id: UUID
    ) -> list[DirectDebitMandate]:
        """Mandates in an ACTIVE/ACTIVATED state for this coop — the scheduled-debit
        target set on period open."""
        from app.core.enums import MANDATE_ACTIVE_STATUSES

        result = await self.db.execute(
            select(DirectDebitMandate).where(
                DirectDebitMandate.cooperative_id == coop_id,
                DirectDebitMandate.status.in_(MANDATE_ACTIVE_STATUSES),
            )
        )
        return list(result.scalars().all())

    async def get_latest_per_member_for_coop(self, coop_id: UUID) -> dict[UUID, DirectDebitMandate]:
        """The single most recent mandate per member for this coop, for the
        dashboard Members table's auto-pay column. Bounded to one coop's own
        mandates — a small, coop-scoped set."""
        result = await self.db.execute(
            select(DirectDebitMandate)
            .where(DirectDebitMandate.cooperative_id == coop_id)
            .order_by(DirectDebitMandate.member_id, DirectDebitMandate.created_at.desc())
        )
        latest: dict[UUID, DirectDebitMandate] = {}
        for m in result.scalars().all():
            if m.member_id not in latest:
                latest[m.member_id] = m
        return latest

    async def update_status(
        self,
        mandate_id: UUID,
        *,
        status: str,
        mandate_code: str | None = None,
        authorized_at: datetime | None = None,
    ) -> None:
        values: dict = {"status": status, "updated_at": datetime.now(timezone.utc)}
        if mandate_code is not None:
            values["mandate_code"] = mandate_code
        if authorized_at is not None:
            values["authorized_at"] = authorized_at
        await self.db.execute(
            update(DirectDebitMandate)
            .where(DirectDebitMandate.id == mandate_id)
            .values(**values)
        )

    async def mark_cancelled(self, mandate_id: UUID, reason: str) -> None:
        await self.db.execute(
            update(DirectDebitMandate)
            .where(DirectDebitMandate.id == mandate_id)
            .values(
                status="CANCELLED",
                cancelled_at=datetime.now(timezone.utc),
                cancellation_reason=reason[:255],
                updated_at=datetime.now(timezone.utc),
                # A cancelled mandate should never resolve a stale debit attempt.
                pending_debit_reference=None,
                pending_debit_contribution_id=None,
            )
        )

    async def set_authorization_link(self, mandate_id: UUID, link: str) -> None:
        await self.db.execute(
            update(DirectDebitMandate)
            .where(DirectDebitMandate.id == mandate_id)
            .values(authorization_link=link, updated_at=datetime.now(timezone.utc))
        )

    async def set_pending_debit(
        self, mandate_id: UUID, *, reference: str, contribution_id: UUID
    ) -> None:
        await self.db.execute(
            update(DirectDebitMandate)
            .where(DirectDebitMandate.id == mandate_id)
            .values(
                pending_debit_reference=reference,
                pending_debit_contribution_id=contribution_id,
                updated_at=datetime.now(timezone.utc),
            )
        )

    async def clear_pending_debit(self, mandate_id: UUID) -> None:
        await self.db.execute(
            update(DirectDebitMandate)
            .where(DirectDebitMandate.id == mandate_id)
            .values(
                pending_debit_reference=None,
                pending_debit_contribution_id=None,
                updated_at=datetime.now(timezone.utc),
            )
        )

    async def get_by_code_or_reference(
        self, mandate_code: str, mandate_reference: str
    ) -> DirectDebitMandate | None:
        """Look up a mandate for a webhook delivery, which may identify it by
        either Monnify's own mandateCode or our mandateReference — the exact
        field Monnify sends isn't confirmed against a captured payload, so both
        are tried."""
        conditions = []
        if mandate_code:
            conditions.append(DirectDebitMandate.mandate_code == mandate_code)
        if mandate_reference:
            conditions.append(DirectDebitMandate.mandate_reference == mandate_reference)
        if not conditions:
            return None
        result = await self.db.execute(
            select(DirectDebitMandate).where(or_(*conditions)).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_with_pending_debit(self) -> list[DirectDebitMandate]:
        """Every mandate with a debit attempt still awaiting resolution — the
        reconciliation cron's target set. Platform-wide but bounded: at most one
        in-flight debit per mandate, and mandates are themselves a small table."""
        result = await self.db.execute(
            select(DirectDebitMandate).where(
                DirectDebitMandate.pending_debit_reference.is_not(None)
            )
        )
        return list(result.scalars().all())
