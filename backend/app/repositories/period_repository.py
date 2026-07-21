from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.contribution import Contribution
from app.models.contribution_period import ContributionPeriod


class PeriodRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_open_period(self, coop_id: UUID) -> ContributionPeriod | None:
        result = await self.db.execute(
            select(ContributionPeriod)
            .where(
                ContributionPeriod.cooperative_id == coop_id,
                ContributionPeriod.closed_at.is_(None),
            )
            .order_by(ContributionPeriod.period_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_current_period(self, coop_id: UUID) -> ContributionPeriod | None:
        """
        The current period cursor: the LOWEST-numbered still-open period. A future
        period materialised by a pay-ahead is also open (closed_at IS NULL), so the
        cursor is the earliest open period, not the latest. Distinct from
        get_open_period (highest open), which the scheduler path relies on.
        """
        result = await self.db.execute(
            select(ContributionPeriod)
            .where(
                ContributionPeriod.cooperative_id == coop_id,
                ContributionPeriod.closed_at.is_(None),
            )
            .order_by(ContributionPeriod.period_number.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def has_paid_future_period(
        self, coop_id: UUID, current_period_number: int
    ) -> bool:
        """
        Whether any member has a paid contribution for a period beyond the coop's
        current cursor. Bounded from this coop's own (small) period set outward to
        the platform-wide contributions table, not an unbounded scan of it.
        """
        result = await self.db.execute(
            select(Contribution.id)
            .join(ContributionPeriod, Contribution.period_id == ContributionPeriod.id)
            .where(
                ContributionPeriod.cooperative_id == coop_id,
                ContributionPeriod.period_number > current_period_number,
                Contribution.status == "paid",
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_latest_period_number(self, coop_id: UUID) -> int:
        result = await self.db.execute(
            select(ContributionPeriod.period_number)
            .where(ContributionPeriod.cooperative_id == coop_id)
            .order_by(ContributionPeriod.period_number.desc())
            .limit(1)
        )
        value = result.scalar_one_or_none()
        return value if value is not None else 0

    async def get_by_number(
        self, coop_id: UUID, period_number: int
    ) -> ContributionPeriod | None:
        result = await self.db.execute(
            select(ContributionPeriod).where(
                ContributionPeriod.cooperative_id == coop_id,
                ContributionPeriod.period_number == period_number,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_numbers(
        self, coop_id: UUID, numbers: list[int]
    ) -> list[ContributionPeriod]:
        """
        Fetch existing period rows for a bounded set of period_numbers in one
        query. Cost is bounded by the (small) `numbers` list and served by the
        UNIQUE(cooperative_id, period_number) index — never a scan driven by the
        size of contribution_periods.
        """
        if not numbers:
            return []
        result = await self.db.execute(
            select(ContributionPeriod).where(
                ContributionPeriod.cooperative_id == coop_id,
                ContributionPeriod.period_number.in_(numbers),
            )
        )
        return list(result.scalars().all())

    async def get_by_id(self, period_id: UUID) -> ContributionPeriod | None:
        result = await self.db.execute(
            select(ContributionPeriod).where(ContributionPeriod.id == period_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create_by_number(
        self,
        coop_id: UUID,
        schedule_id: UUID,
        period_number: int,
        start_date: date,
        due_date: date,
    ) -> ContributionPeriod:
        """
        Idempotently find-or-create a period by (cooperative_id, period_number).

        Uses INSERT ... ON CONFLICT DO NOTHING against the existing
        UNIQUE(cooperative_id, period_number) constraint. If this call inserted,
        the new id is returned; if the row already existed (or a concurrent writer
        won the race), the conflict is a no-op and we read the existing row. Two
        members paying the same future period therefore cannot double-create it —
        the unique index serialises them.
        """
        stmt = (
            pg_insert(ContributionPeriod)
            .values(
                cooperative_id=coop_id,
                schedule_id=schedule_id,
                period_number=period_number,
                start_date=start_date,
                due_date=due_date,
            )
            .on_conflict_do_nothing(
                index_elements=["cooperative_id", "period_number"]
            )
            .returning(ContributionPeriod.id)
        )
        result = await self.db.execute(stmt)
        new_id = result.scalar_one_or_none()
        if new_id is not None:
            created = await self.get_by_id(new_id)
            if created is not None:
                return created

        existing = await self.get_by_number(coop_id, period_number)
        if existing is None:
            raise NotFoundException(
                f"Could not resolve period {period_number} for cooperative {coop_id}"
            )
        return existing

    async def create(
        self,
        coop_id: UUID,
        schedule_id: UUID,
        period_number: int,
        start_date: date,
        due_date: date,
    ) -> ContributionPeriod:
        period = ContributionPeriod(
            cooperative_id=coop_id,
            schedule_id=schedule_id,
            period_number=period_number,
            start_date=start_date,
            due_date=due_date,
        )
        self.db.add(period)
        await self.db.flush()
        return period

    async def close(self, period_id: UUID) -> None:
        await self.db.execute(
            update(ContributionPeriod)
            .where(ContributionPeriod.id == period_id)
            .values(closed_at=datetime.now(timezone.utc))
        )

    async def get_member_debt_periods(
        self, member_id: UUID, coop_id: UUID
    ) -> list[ContributionPeriod]:
        result = await self.db.execute(
            select(ContributionPeriod)
            .join(
                Contribution,
                and_(
                    Contribution.period_id == ContributionPeriod.id,
                    Contribution.member_id == member_id,
                    Contribution.status == "unpaid",
                ),
            )
            .where(
                ContributionPeriod.cooperative_id == coop_id,
                ContributionPeriod.closed_at.is_not(None),
            )
            .order_by(ContributionPeriod.period_number)
        )
        return list(result.scalars().all())

    async def get_all_periods(self, coop_id: UUID) -> list[ContributionPeriod]:
        """All periods for a cooperative, newest first. Used for the history filter dropdown."""
        result = await self.db.execute(
            select(ContributionPeriod)
            .where(ContributionPeriod.cooperative_id == coop_id)
            .order_by(ContributionPeriod.period_number.desc())
        )
        return list(result.scalars().all())