from uuid import UUID

from sqlalchemy import cast, select
from sqlalchemy import Date as SADate
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Frequency
from app.models.contribution import Contribution
from app.models.contribution_period import ContributionPeriod
from app.models.coop_member import CoopMember
from app.models.coop_schedule import CoopSchedule
from app.repositories.contribution_repository import ContributionRepository
from app.repositories.cooperative_repository import CooperativeRepository
from app.repositories.period_repository import PeriodRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.services.schedule_service import (
    ScheduleService,
    compute_next_period_dates,
    compute_period_end_date,
    format_period_label,
)


class PeriodService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.period_repo = PeriodRepository(db)
        self.schedule_repo = ScheduleRepository(db)
        self.schedule_service = ScheduleService(db)
        self.coop_repo = CooperativeRepository(db)
        self.contribution_repo = ContributionRepository(db)

    async def get_or_create_current_period(
        self, coop_id: UUID
    ) -> ContributionPeriod:
        open_period = await self.period_repo.get_open_period(coop_id)
        if open_period:
            return open_period

        schedule = await self.schedule_service.get_active_schedule(coop_id)
        last_number = await self.period_repo.get_latest_period_number(coop_id)
        start_date, due_date = compute_next_period_dates(schedule, last_number)

        return await self.period_repo.create(
            coop_id=coop_id,
            schedule_id=schedule.id,
            period_number=last_number + 1,
            start_date=start_date,
            due_date=due_date,
        )

    async def close_period_and_create_next(
        self, period: ContributionPeriod
    ) -> tuple[ContributionPeriod, list[UUID]]:
        """
        Close the given period, open the next one, and pre-generate contribution
        records for all members who had joined by the new period's start date.
        Returns the new period and the list of member_ids for whom contributions
        were created (used by the caller to schedule reminders).
        """
        await self.period_repo.close(period.id)

        next_period = await self.get_or_create_current_period(period.cooperative_id)

        # Members who joined on or before the new period's start date
        result = await self.db.execute(
            select(CoopMember).where(
                CoopMember.cooperative_id == period.cooperative_id,
                cast(CoopMember.joined_at, SADate) <= next_period.start_date,
            )
        )
        active_members = result.scalars().all()

        coop = await self.coop_repo.get_by_id(period.cooperative_id)

        # Idempotent: skips members who already hold a contribution for this period
        # (e.g. a pay-ahead materialised it). Returns only genuinely-new member_ids
        # so reminders are not scheduled for members who already paid ahead.
        member_ids = await self.contribution_repo.create_bulk([
            {
                "member_id": cm.member_id,
                "cooperative_id": period.cooperative_id,
                "period_id": next_period.id,
                "amount": coop.contribution_amount,
                "status": "unpaid",
            }
            for cm in active_members
        ])

        await self.db.commit()

        return next_period, member_ids

    async def close_overdue_periods(self) -> dict:
        """
        Find all contribution periods whose due_date has passed and are still open,
        close each one, create the next period, and schedule reminders for new members.
        Returns a dict with the count of periods closed and created.
        """
        from datetime import date as _date
        from app.services.reminder_service import ReminderService

        today = _date.today()

        result = await self.db.execute(
            select(ContributionPeriod).where(
                ContributionPeriod.due_date <= today,
                ContributionPeriod.closed_at.is_(None),
            )
        )
        overdue_periods = result.scalars().all()

        if not overdue_periods:
            return {"closed": 0, "created": 0}

        reminder_service = ReminderService(self.db)
        closed_count = 0
        created_count = 0

        for period in overdue_periods:
            next_period, member_ids = await self.close_period_and_create_next(period)
            await reminder_service.schedule_reminders_for_period(next_period, member_ids)
            closed_count += 1
            created_count += 1

        return {"closed": closed_count, "created": created_count}

    async def get_or_create_period_by_number(
        self, coop_id: UUID, schedule: CoopSchedule, period_number: int
    ) -> ContributionPeriod:
        """
        Idempotently find-or-create a single future period, bound by its explicit
        `period_number` (never positionally). Dates are recomputed deterministically
        from the schedule so a period_number always maps to the same dates and two
        members paying the same future period cannot double-create it.
        """
        start_date, due_date = compute_next_period_dates(schedule, period_number - 1)
        return await self.period_repo.get_or_create_by_number(
            coop_id=coop_id,
            schedule_id=schedule.id,
            period_number=period_number,
            start_date=start_date,
            due_date=due_date,
        )

    async def get_member_debt_periods(
        self, member_id: UUID, coop_id: UUID
    ) -> list[ContributionPeriod]:
        return await self.period_repo.get_member_debt_periods(member_id, coop_id)

    async def get_payable_periods(
        self, coop_id: UUID, member_id: UUID
    ) -> list[dict]:
        """
        Pure read — returns current open period, all debt periods, and up to 3
        computed future periods. Future periods are NOT persisted here.
        """
        schedule = await self.schedule_service.get_active_schedule(coop_id)
        freq = Frequency(schedule.frequency)
        coop = await self.coop_repo.get_by_id(coop_id)

        result: list[dict] = []

        # --- Debt periods (closed, member has unpaid contribution) ---
        debt_periods = await self.period_repo.get_member_debt_periods(
            member_id, coop_id
        )
        # Fetch snapshotted amounts for debt periods in one query
        debt_amounts = await self.contribution_repo.get_amounts_for_periods(
            member_id, [p.id for p in debt_periods]
        )
        for p in debt_periods:
            end_date = compute_period_end_date(schedule.anchor_date, freq, p.period_number)
            result.append({
                "id": p.id,
                "period_number": p.period_number,
                "start_date": p.start_date,
                "due_date": p.due_date,
                "amount": debt_amounts.get(p.id, coop.contribution_amount),
                "label": format_period_label(p.period_number, p.start_date, end_date),
                "is_debt": True,
                "is_future": False,
            })

        # --- Current period (only if member has not already paid for it) ---
        # The current period is the LOWEST-numbered open period. Materialising a
        # future period (pay-ahead) also leaves it open (closed_at IS NULL), so the
        # highest open period is not the cursor — the earliest open one is.
        current_period = await self.period_repo.get_current_period(coop_id)
        if current_period:
            paid_check = await self.db.execute(
                select(Contribution.id).where(
                    Contribution.member_id == member_id,
                    Contribution.period_id == current_period.id,
                    Contribution.status == "paid",
                )
            )
            if paid_check.scalar_one_or_none() is None:
                end_date = compute_period_end_date(
                    schedule.anchor_date, freq, current_period.period_number
                )
                result.append({
                    "id": current_period.id,
                    "period_number": current_period.period_number,
                    "start_date": current_period.start_date,
                    "due_date": current_period.due_date,
                    "amount": coop.contribution_amount,
                    "label": format_period_label(
                        current_period.period_number, current_period.start_date, end_date
                    ),
                    "is_debt": False,
                    "is_future": False,
                })

        # --- Up to 3 unpaid future periods, anchored on the current-period cursor ---
        # Locked out while any debt or unpaid-current period is outstanding — a
        # member must be caught up before pre-paying ahead, so arrears can't be
        # masked by a paid future period while an earlier one sits unpaid.
        if result:
            return result

        # Anchor on the current period (scheduler-advanced), NOT MAX(period_number):
        # one member materialising future rows by paying ahead must not shift any
        # other member's projected window. Periods the member has already paid
        # (materialised by a prior pay-ahead) are skipped so they are not re-offered.
        base_number = (
            current_period.period_number
            if current_period
            else await self.period_repo.get_latest_period_number(coop_id)
        )
        LOOKAHEAD = 10  # bounded scan to find 3 still-unpaid future periods
        candidate_numbers = [base_number + i for i in range(1, LOOKAHEAD + 1)]
        existing_future = {
            p.period_number: p
            for p in await self.period_repo.get_by_numbers(coop_id, candidate_numbers)
        }
        paid_future_ids = await self.contribution_repo.get_paid_period_ids(
            member_id, [p.id for p in existing_future.values()]
        )

        collected = 0
        for i in range(1, LOOKAHEAD + 1):
            if collected >= 3:
                break
            future_number = base_number + i
            existing = existing_future.get(future_number)
            if existing is not None and existing.id in paid_future_ids:
                continue  # member already paid this future period — don't re-offer
            start_date, due_date = compute_next_period_dates(schedule, future_number - 1)
            end_date = compute_period_end_date(schedule.anchor_date, freq, future_number)
            result.append({
                # Bind to the real row if it already exists; otherwise the write
                # path find-or-creates it by explicit period_number.
                "id": existing.id if existing is not None else None,
                "period_number": future_number,
                "start_date": start_date,
                "due_date": due_date,
                "amount": coop.contribution_amount,
                "label": format_period_label(future_number, start_date, end_date),
                "is_debt": False,
                "is_future": True,
            })
            collected += 1

        return result

    async def has_future_paid_contribution(self, coop_id: UUID) -> bool:
        """Whether any member has already paid ahead of the coop's current period."""
        current_period = await self.period_repo.get_current_period(coop_id)
        if not current_period:
            return False
        return await self.period_repo.has_paid_future_period(
            coop_id, current_period.period_number
        )

    async def get_all_periods(self, coop_id: UUID) -> list[dict]:
        """All persisted periods for the coop, for the history filter dropdown."""
        periods = await self.period_repo.get_all_periods(coop_id)

        # Label each period from its OWN schedule (frequency may have changed
        # since it was created), not the coop's current active schedule.
        schedules = await self.schedule_repo.get_by_ids(
            list({p.schedule_id for p in periods})
        )
        schedule_by_id = {s.id: s for s in schedules}

        # A future period materialised by a pay-ahead is also closed_at IS NULL,
        # so every un-closed row would read "current" — only the single
        # lowest-numbered open period actually is (see get_current_period).
        current_period = await self.period_repo.get_current_period(coop_id)
        current_id = current_period.id if current_period else None

        result = []
        for p in periods:
            schedule = schedule_by_id.get(p.schedule_id)
            if schedule:
                end_date = compute_period_end_date(
                    schedule.anchor_date, Frequency(schedule.frequency), p.period_number
                )
                label = format_period_label(p.period_number, p.start_date, end_date)
            else:
                label = p.start_date.strftime("%B %Y")
            result.append({
                "id": p.id,
                "period_number": p.period_number,
                "label": label,
                "start_date": p.start_date,
                "due_date": p.due_date,
                "is_open": p.id == current_id,
            })
        return result