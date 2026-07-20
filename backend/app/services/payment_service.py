import logging
import secrets
import time
from uuid import UUID

from app.core.config import get_settings
from app.core.exceptions import BadRequestException
from app.models.pending_transaction import PendingTransaction
from app.repositories.payment_repository import PaymentRepository
from app.services.payment_provider import get_payment_provider
from app.services.period_service import PeriodService
from app.services.reminder_service import ReminderService

settings = get_settings()
logger = logging.getLogger("akoweai")


def generate_transaction_reference() -> str:
    """Generate a unique payment reference: AJODA-{timestamp_ms}-{6 hex chars}."""
    ts_ms = int(time.time() * 1000)
    rand = secrets.token_hex(3).upper()
    return f"AJODA-{ts_ms}-{rand}"


class PaymentService:
    def __init__(self, db):
        self.db = db
        self.payment_repo = PaymentRepository(db)
        self.period_service = PeriodService(db)

    async def create_pending_transaction(
        self,
        member_id: UUID,
        coop_id: UUID,
        period_data: list[dict],
        amount_kobo: int,
    ) -> PendingTransaction:
        """
        Create a pending transaction. Existing periods are bound by their id;
        future periods (id is None) are bound by their explicit `period_number`
        via an idempotent find-or-create on (coop_id, period_number) — never
        positionally. So a non-consecutive future selection (e.g. +1 and +3)
        settles exactly those periods, and two members paying the same future
        period cannot double-create it.
        """
        period_ids: list[UUID] = []
        schedule = None  # loaded once, only if a future period must be materialised

        for p in period_data:
            pid = p.get("id")
            if pid is not None:
                period_ids.append(UUID(str(pid)))
                continue

            period_number = p.get("period_number")
            if period_number is None:
                raise BadRequestException(
                    "A selected future period is missing its period number."
                )
            if schedule is None:
                schedule = await self.period_service.schedule_service.get_active_schedule(
                    coop_id
                )
            period = await self.period_service.get_or_create_period_by_number(
                coop_id, schedule, int(period_number)
            )
            period_ids.append(period.id)

        reference = generate_transaction_reference()
        transaction = await self.payment_repo.create(
            reference=reference,
            member_id=member_id,
            coop_id=coop_id,
            period_ids=period_ids,
            amount=amount_kobo,
        )
        await self.db.commit()
        await self.db.refresh(transaction)
        return transaction

    def build_payment_initiation_url(self, reference: str) -> str:
        """Build payment initiation URL for WhatsApp CTA button."""
        return f"{settings.prod_url}/api/payments/initiate/{reference}"

    async def poll_transaction_status(self, reference: str) -> dict:
        """
        Reconciliation fallback: verify a transaction directly with the PSP via
        Monnify's server-side Verify Transaction endpoint.
        Returns the provider's normalized dict: {"status", "amount_kobo", "raw"}.
        """
        return await get_payment_provider().verify_transaction(reference)

    async def is_transaction_already_processed(self, reference: str) -> bool:
        return await self.payment_repo.is_already_paid(reference)

    async def process_successful_payment(
        self, transaction: PendingTransaction
    ) -> None:
        """
        Apply settlement side-effects for a paid transaction: mark contributions
        paid, credit the pool, and cancel pending reminders. The pending_transaction
        row is flipped to 'paid' atomically by PaymentRepository.settle_if_pending()
        before this runs, so this method only handles the downstream effects and
        must be called exactly once per settlement.
        """
        await self.payment_repo.mark_contributions_paid(
            transaction.period_ids, transaction.member_id
        )
        await self.payment_repo.increment_pool_balance(
            transaction.cooperative_id, transaction.amount
        )
        await ReminderService(self.db).cancel_reminders_for_periods(
            transaction.period_ids, transaction.member_id
        )