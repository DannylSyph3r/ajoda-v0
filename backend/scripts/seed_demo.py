"""
Demo seed — one command populates a funded, ready-to-demo cooperative.

    cd backend
    python -m scripts.seed_demo          # create the demo coop (idempotent)
    python -m scripts.seed_demo --reset  # wipe the demo coop first, then recreate

Produces a cooperative with a funded pool, a loginable exco (phone + PIN for the
dashboard), members, a few contribution periods with paid/unpaid history, and a
couple of past disbursements (one completed, one failed) so the Withdrawals view
and the disbursement-history bot query are populated on first look.

Requires a populated backend/.env pointing at a reachable database, and
`alembic upgrade head` already run.
"""
import asyncio
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.database import AsyncSessionFactory
from app.core.security import hash_pin
from app.models.contribution import Contribution
from app.models.contribution_period import ContributionPeriod
from app.models.coop_member import CoopMember
from app.models.coop_schedule import CoopSchedule
from app.models.cooperative import Cooperative
from app.models.join_code import JoinCode
from app.models.member import Member
from app.models.withdrawal import Withdrawal
from app.services.payment_service import generate_disbursement_reference
from app.services.schedule_service import compute_next_period_dates

# --- Demo constants -------------------------------------------------------- #
COOP_NAME = "Unity Thrift Coop"
CONTRIB_KOBO = 1_000_000  # ₦10,000 / period
POOL_KOBO = 184_250_000  # ₦1,842,500 funded pool
DEMO_PIN = "1234"
JOIN_CODE = "DEMO01"

EXCO = ("+2348030000001", "Adaeze Okafor")
MEMBERS = [
    ("+2348030000002", "Chidi Nwosu"),
    ("+2348030000003", "Ngozi Eze"),
    ("+2348030000004", "Emeka Obi"),
    ("+2348030000005", "Fatima Bello"),
]


async def _wipe_demo(session) -> None:
    """Remove a previously-seeded demo coop and everything hanging off it."""
    coop = (
        await session.execute(select(Cooperative).where(Cooperative.name == COOP_NAME))
    ).scalar_one_or_none()
    if not coop:
        return
    member_ids = [
        row[0]
        for row in (
            await session.execute(
                select(CoopMember.member_id).where(
                    CoopMember.cooperative_id == coop.id
                )
            )
        ).all()
    ]
    await session.execute(delete(Contribution).where(Contribution.cooperative_id == coop.id))
    await session.execute(delete(Withdrawal).where(Withdrawal.cooperative_id == coop.id))
    await session.execute(delete(ContributionPeriod).where(ContributionPeriod.cooperative_id == coop.id))
    await session.execute(delete(JoinCode).where(JoinCode.cooperative_id == coop.id))
    await session.execute(delete(CoopMember).where(CoopMember.cooperative_id == coop.id))
    await session.execute(delete(CoopSchedule).where(CoopSchedule.cooperative_id == coop.id))
    if member_ids:
        await session.execute(delete(Member).where(Member.id.in_(member_ids)))
    await session.execute(delete(Cooperative).where(Cooperative.id == coop.id))
    await session.commit()


async def seed(reset: bool) -> None:
    async with AsyncSessionFactory() as session:
        if reset:
            await _wipe_demo(session)

        existing = (
            await session.execute(select(Member).where(Member.phone_number == EXCO[0]))
        ).scalar_one_or_none()
        if existing and not reset:
            _print_credentials()
            print("\n(Demo data already present — pass --reset to rebuild it.)")
            return

        now = datetime.now(timezone.utc)

        # Members (exco first so it can own the coop) -------------------------
        exco = Member(phone_number=EXCO[0], full_name=EXCO[1], pin_hash=hash_pin(DEMO_PIN))
        session.add(exco)
        members = []
        for phone, name in MEMBERS:
            m = Member(phone_number=phone, full_name=name, pin_hash=hash_pin(DEMO_PIN))
            session.add(m)
            members.append(m)
        await session.flush()
        everyone = [exco, *members]

        # Cooperative + schedule ---------------------------------------------
        coop = Cooperative(
            name=COOP_NAME,
            contribution_amount=CONTRIB_KOBO,
            due_day_offset=5,
            created_by_member_id=exco.id,
            pool_balance=POOL_KOBO,
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

        session.add(
            CoopMember(
                member_id=exco.id,
                cooperative_id=coop.id,
                role="exco",
                joined_at=now,
            )
        )
        for m in members:
            session.add(
                CoopMember(
                    member_id=m.id,
                    cooperative_id=coop.id,
                    role="member",
                    joined_at=now,
                )
            )

        # Three periods: two closed (fully paid), one open (partly paid) ------
        for n in (1, 2, 3):
            start, due = compute_next_period_dates(schedule, n - 1)
            closed = (
                datetime.combine(due, datetime.min.time(), tzinfo=timezone.utc)
                if n < 3
                else None
            )
            period = ContributionPeriod(
                cooperative_id=coop.id,
                schedule_id=schedule.id,
                period_number=n,
                start_date=start,
                due_date=due,
                closed_at=closed,
            )
            session.add(period)
            await session.flush()
            for i, m in enumerate(everyone):
                # Closed periods fully paid; open period: first three paid, rest unpaid.
                paid = n < 3 or i < 3
                session.add(
                    Contribution(
                        member_id=m.id,
                        cooperative_id=coop.id,
                        period_id=period.id,
                        amount=CONTRIB_KOBO,
                        status="paid" if paid else "unpaid",
                        paid_at=now if paid else None,
                    )
                )

        # A join code so a judge can join over WhatsApp ----------------------
        session.add(
            JoinCode(
                cooperative_id=coop.id,
                code=JOIN_CODE,
                role="member",
                expires_at=now + timedelta(days=30),
            )
        )

        # Past disbursements: one completed, one failed ----------------------
        session.add(
            Withdrawal(
                cooperative_id=coop.id,
                amount=25_000_000,  # ₦250,000
                reason="Generator repair",
                authorized_by_member_id=exco.id,
                pool_balance_after=POOL_KOBO,
                status="COMPLETED",
                transfer_reference=generate_disbursement_reference(),
                monnify_transaction_reference="MFDS|20260720|DEMO001",
                destination_account_number="0123456789",
                destination_bank_code="058",
                destination_account_name="ADEBAYO OKONKWO",
                updated_at=now - timedelta(days=1),
            )
        )
        session.add(
            Withdrawal(
                cooperative_id=coop.id,
                amount=1_710_000,  # ₦17,100
                reason="Vendor refund",
                authorized_by_member_id=exco.id,
                pool_balance_after=None,
                status="FAILED",
                transfer_reference=generate_disbursement_reference(),
                destination_account_number="0035785417",
                destination_bank_code="044",
                destination_account_name="MARVELOUS BENJI",
                failure_reason=(
                    "The disbursement wallet had insufficient funds for this transfer. "
                    "Fund the wallet and retry."
                ),
                updated_at=now - timedelta(hours=6),
            )
        )

        await session.commit()
        print("Seeded demo cooperative successfully.\n")
        _print_credentials()


def _print_credentials() -> None:
    print("=" * 52)
    print("  Ajoda demo — ready to sign in")
    print("=" * 52)
    print(f"  Cooperative : {COOP_NAME}")
    print(f"  Dashboard   : phone {EXCO[0]}  ·  PIN {DEMO_PIN}  (exco)")
    print(f"  Members     : {', '.join(p for p, _ in MEMBERS)}  (PIN {DEMO_PIN})")
    print(f"  Join code   : {JOIN_CODE}  (for a member joining via WhatsApp)")
    print("=" * 52)


if __name__ == "__main__":
    asyncio.run(seed(reset="--reset" in sys.argv))
