"""
Regression tests for the future-period bundling fix (Phase 2).

Covers the two compounding failures from Reference Part 7:
  (a) one member paying ahead must not shift another member's projected window;
  (b) a non-consecutive future selection (+1 and +3) must settle exactly those
      periods, never a positionally-mapped +1/+2;
and the idempotency guarantee behind the fix:
  (c) two writers materialising the same future period must not double-create it.

These require a real Postgres test DB (UUID/ARRAY + ON CONFLICT); they are skipped
when TEST_DATABASE_URL is unset (see conftest).
"""
from datetime import date, datetime, timezone

from sqlalchemy import func, select

from app.models.contribution import Contribution
from app.models.contribution_period import ContributionPeriod
from app.models.coop_member import CoopMember
from app.models.coop_schedule import CoopSchedule
from app.models.cooperative import Cooperative
from app.models.member import Member
from app.repositories.payment_repository import PaymentRepository
from app.repositories.period_repository import PeriodRepository
from app.services.payment_service import PaymentService
from app.services.period_service import PeriodService
from app.services.schedule_service import compute_next_period_dates

CONTRIB_KOBO = 1_000_000  # ₦10,000


async def _seed(session, num_members: int = 2):
    """Build a coop with an active monthly schedule, `num_members` members, and an
    open period 1 with an unpaid contribution per member."""
    members = []
    for i in range(num_members):
        m = Member(phone_number=f"+23480000000{i}", full_name=f"Member {i}")
        session.add(m)
        members.append(m)
    await session.flush()

    coop = Cooperative(
        name="Test Coop",
        contribution_amount=CONTRIB_KOBO,
        due_day_offset=5,
        created_by_member_id=members[0].id,
    )
    session.add(coop)
    await session.flush()

    schedule = CoopSchedule(
        cooperative_id=coop.id,
        frequency="monthly",
        anchor_date=date(2026, 1, 1),
        due_day_offset=5,
        version=1,
    )
    session.add(schedule)
    await session.flush()

    for m in members:
        session.add(
            CoopMember(
                member_id=m.id,
                cooperative_id=coop.id,
                role="member",
                joined_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        )

    start, due = compute_next_period_dates(schedule, 0)  # period 1
    p1 = ContributionPeriod(
        cooperative_id=coop.id,
        schedule_id=schedule.id,
        period_number=1,
        start_date=start,
        due_date=due,
    )
    session.add(p1)
    await session.flush()

    for m in members:
        session.add(
            Contribution(
                member_id=m.id,
                cooperative_id=coop.id,
                period_id=p1.id,
                amount=CONTRIB_KOBO,
                status="unpaid",
            )
        )
    await session.commit()
    return coop, schedule, members, p1


def _futures(periods: list[dict]) -> list[dict]:
    return [p for p in periods if p["is_future"]]


async def test_pay_ahead_does_not_shift_other_members(db):
    """(a) Member A paying ahead must not move Member B's future window/dates."""
    coop, schedule, members, _ = await _seed(db, num_members=2)
    a, b = members
    svc = PeriodService(db)

    before = _futures(await svc.get_payable_periods(coop.id, b.id))
    before_view = [(p["period_number"], p["start_date"]) for p in before]

    # A pays ahead for the immediate next future period (period 2) and settles it.
    a_futures = _futures(await svc.get_payable_periods(coop.id, a.id))
    plus1 = next(p for p in a_futures if p["period_number"] == 2)
    pay = PaymentService(db)
    tx = await pay.create_pending_transaction(a.id, coop.id, [plus1], plus1["amount"])
    repo = PaymentRepository(db)
    assert await repo.settle_if_pending(tx.reference) is True
    await repo.mark_contributions_paid(tx.period_ids, a.id)
    await db.commit()

    after = _futures(await svc.get_payable_periods(coop.id, b.id))
    after_view = [(p["period_number"], p["start_date"]) for p in after]

    assert before_view == after_view, (before_view, after_view)
    # B still sees period 2 as the immediate next payable future (not shifted to 3).
    assert after_view[0][0] == 2


async def test_non_consecutive_future_selection_lands_exactly(db):
    """(b) Selecting +1 and +3 settles exactly periods 2 and 4; 3 is untouched."""
    coop, _schedule, members, _ = await _seed(db, num_members=1)
    m = members[0]
    svc = PeriodService(db)

    futures = _futures(await svc.get_payable_periods(coop.id, m.id))
    plus1 = next(p for p in futures if p["period_number"] == 2)
    plus3 = next(p for p in futures if p["period_number"] == 4)

    pay = PaymentService(db)
    tx = await pay.create_pending_transaction(
        m.id, coop.id, [plus1, plus3], plus1["amount"] + plus3["amount"]
    )

    period_repo = PeriodRepository(db)
    covered = sorted(
        (await period_repo.get_by_id(pid)).period_number for pid in tx.period_ids
    )
    assert covered == [2, 4], covered
    # The skipped middle period must NOT have been created.
    assert await period_repo.get_by_number(coop.id, 3) is None


async def test_concurrent_same_future_period_not_double_created(db, session_factory):
    """(c) Two independent writers upserting the same future period yield one row."""
    coop, schedule, _members, _ = await _seed(db, num_members=2)
    start, due = compute_next_period_dates(schedule, 1)  # period 2

    async with session_factory() as s1, session_factory() as s2:
        first = await PeriodRepository(s1).get_or_create_by_number(
            coop.id, schedule.id, 2, start, due
        )
        await s1.commit()
        second = await PeriodRepository(s2).get_or_create_by_number(
            coop.id, schedule.id, 2, start, due
        )
        await s2.commit()

    assert first.id == second.id

    count = await db.execute(
        select(func.count())
        .select_from(ContributionPeriod)
        .where(
            ContributionPeriod.cooperative_id == coop.id,
            ContributionPeriod.period_number == 2,
        )
    )
    assert count.scalar_one() == 1
