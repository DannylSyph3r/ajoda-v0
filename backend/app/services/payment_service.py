import logging
import secrets
import time
from uuid import UUID

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.enums import RefundStatus, RefundType
from app.core.exceptions import AppException, BadRequestException, NotFoundException
from app.models.contribution import Contribution
from app.models.contribution_refund import ContributionRefund
from app.models.cooperative import Cooperative
from app.models.pending_transaction import PendingTransaction
from app.repositories.contribution_refund_repository import ContributionRefundRepository
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


def generate_disbursement_reference() -> str:
    """Generate a unique disbursement reference: AJODA-DISB-{timestamp_ms}-{6 hex}."""
    ts_ms = int(time.time() * 1000)
    rand = secrets.token_hex(3).upper()
    return f"AJODA-DISB-{ts_ms}-{rand}"


def generate_refund_reference() -> str:
    """Generate a unique refund reference: AJODA-RFND-{timestamp_ms}-{6 hex}."""
    ts_ms = int(time.time() * 1000)
    rand = secrets.token_hex(3).upper()
    return f"AJODA-RFND-{ts_ms}-{rand}"


class PaymentService:
    def __init__(self, db):
        self.db = db
        self.payment_repo = PaymentRepository(db)
        self.refund_repo = ContributionRefundRepository(db)
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
        self, transaction: PendingTransaction, monnify_transaction_reference: str = ""
    ) -> None:
        """
        Apply settlement side-effects for a paid transaction: mark contributions
        paid, credit the pool, and cancel pending reminders. The pending_transaction
        row is flipped to 'paid' atomically by PaymentRepository.settle_if_pending()
        before this runs, so this method only handles the downstream effects and
        must be called exactly once per settlement.

        `monnify_transaction_reference` is Monnify's own transaction reference
        (from the Verify Transaction response) — distinct from our own
        `transaction.reference` (paymentReference) — and is what a later refund
        must be initiated against. Falls back to our own reference only if
        Monnify didn't return one, so settlement never fails on a missing value.
        """
        await self.payment_repo.mark_contributions_paid(
            transaction.period_ids,
            transaction.member_id,
            settlement_reference=monnify_transaction_reference or transaction.reference,
        )
        await self.payment_repo.increment_pool_balance(
            transaction.cooperative_id, transaction.amount
        )
        await ReminderService(self.db).cancel_reminders_for_periods(
            transaction.period_ids, transaction.member_id
        )

    # ================================================================== #
    # Refunds
    # ================================================================== #
    async def get_refund_for_coop(
        self, coop_id: UUID, refund_id: UUID
    ) -> ContributionRefund:
        """IDOR-guarded load — a refund scoped to its cooperative via its
        contribution, mirroring get_disbursement_for_coop."""
        result = await self.db.execute(
            select(ContributionRefund, Contribution.cooperative_id)
            .join(Contribution, Contribution.id == ContributionRefund.contribution_id)
            .where(
                ContributionRefund.id == refund_id,
                Contribution.cooperative_id == coop_id,
            )
        )
        row = result.first()
        if row is None:
            raise NotFoundException("Refund not found")
        return row[0]

    async def refund_contribution(
        self,
        *,
        coop_id: UUID,
        contribution_id: UUID,
        amount_kobo: int,
        reason: str,
        requested_by_member_id: UUID,
    ) -> ContributionRefund:
        """
        Initiate a refund (full or partial) against a paid contribution. Exco-only
        and step-up gated at the router — this method assumes that's already
        enforced. Never self-serve: `requested_by_member_id` is always the exco
        who authorised it, not the contributor.
        """
        result = await self.db.execute(
            select(Contribution).where(
                Contribution.id == contribution_id,
                Contribution.cooperative_id == coop_id,
            )
        )
        contribution = result.scalar_one_or_none()
        if not contribution:
            raise NotFoundException("Contribution not found")
        if contribution.status != "paid":
            raise BadRequestException("Only a paid contribution can be refunded.")
        if not contribution.settlement_reference:
            raise BadRequestException(
                "This contribution has no settlement reference on file and "
                "cannot be refunded."
            )

        already_refunded = await self.refund_repo.get_total_refunded_for_contribution(
            contribution_id
        )
        remaining = contribution.amount - already_refunded
        if amount_kobo > remaining:
            raise BadRequestException(
                "Refund amount exceeds what's left to refund. Already refunded: "
                f"₦{already_refunded // 100:,}, remaining: ₦{remaining // 100:,}."
            )

        refund_type = (
            RefundType.FULL_REFUND.value
            if amount_kobo == remaining
            else RefundType.PARTIAL_REFUND.value
        )

        reference = generate_refund_reference()
        refund = await self.refund_repo.create(
            contribution_id=contribution_id,
            requested_by_member_id=requested_by_member_id,
            amount=amount_kobo,
            reason=reason,
            refund_type=refund_type,
            refund_reference=reference,
            original_transaction_reference=contribution.settlement_reference,
        )
        await self.db.commit()
        await self.db.refresh(refund)

        try:
            result = await get_payment_provider().initiate_refund(
                transaction_reference=contribution.settlement_reference,
                refund_reference=reference,
                amount_kobo=amount_kobo,
                reason=reason,
                customer_note="Cooperative refund",
            )
        except AppException:
            await self.refund_repo.fail_if_pending(
                refund.id, "Refund initiation failed with the provider"
            )
            await self.db.commit()
            raise

        status = (result.get("status") or "").upper()
        if status == RefundStatus.COMPLETED.value:
            await self._complete_refund(refund.id, result.get("monnify_reference", ""))
        elif status == RefundStatus.FAILED.value:
            await self.refund_repo.fail_if_pending(
                refund.id, "The provider rejected the refund"
            )
            await self.db.commit()

        await self.db.refresh(refund)
        return refund

    async def get_refund_status(
        self, coop_id: UUID, refund_id: UUID
    ) -> ContributionRefund:
        """Reconciliation-on-read: if still PENDING, poll Monnify and resolve
        before returning, mirroring get_disbursement_status."""
        refund = await self.get_refund_for_coop(coop_id, refund_id)
        if refund.status == RefundStatus.PENDING.value:
            try:
                outcome = await get_payment_provider().get_refund_status(
                    refund.refund_reference
                )
                status = (outcome.get("status") or "").upper()
                if status == RefundStatus.COMPLETED.value:
                    await self._complete_refund(
                        refund.id, outcome.get("monnify_reference", "")
                    )
                elif status == RefundStatus.FAILED.value:
                    await self.refund_repo.fail_if_pending(
                        refund.id, "The provider rejected the refund"
                    )
                    await self.db.commit()
            except Exception as exc:  # noqa: BLE001 — read must not fail on poll error
                logger.warning("Refund status poll failed for %s: %s", refund_id, exc)
            refund = await self.get_refund_for_coop(coop_id, refund_id)
        return refund

    async def _complete_refund(self, refund_id: UUID, monnify_reference: str) -> None:
        """
        Atomically claim the refund, debit the pool, and — only if this refund's
        cumulative amount reaches the contribution's full amount — flip the
        contribution to 'refunded'. A partial refund leaves it 'paid': the member
        did fulfil the period, only the excess came back.
        """
        completed = await self.refund_repo.complete_if_pending(
            refund_id, monnify_reference
        )
        if not completed:
            return  # already resolved — idempotent

        refund = await self.refund_repo.get_by_id(refund_id)
        contribution_result = await self.db.execute(
            select(Contribution).where(Contribution.id == refund.contribution_id)
        )
        contribution = contribution_result.scalar_one_or_none()
        if contribution is None:
            await self.db.commit()
            return

        # Atomic pool debit, fail-closed guard — mirrors withdrawal completion.
        debit = await self.db.execute(
            update(Cooperative)
            .where(
                Cooperative.id == contribution.cooperative_id,
                Cooperative.pool_balance >= refund.amount,
            )
            .values(pool_balance=Cooperative.pool_balance - refund.amount)
            .returning(Cooperative.pool_balance)
        )
        if debit.scalar_one_or_none() is None:
            logger.critical(
                "Pool debit failed on refund completion for contribution %s "
                "(refund %s): pool insufficient — manual reconciliation required.",
                contribution.id, refund_id,
            )

        if refund.refund_type == RefundType.FULL_REFUND.value:
            await self.db.execute(
                update(Contribution)
                .where(Contribution.id == contribution.id)
                .values(status="refunded")
            )

        await self.db.commit()