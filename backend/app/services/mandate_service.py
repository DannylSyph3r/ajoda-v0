"""
MandateService — Direct Debit (recurring contributions) orchestration.

Wraps the Monnify mandate lifecycle (create -> customer authorises with their own
bank -> scheduled debit each period -> poll the outcome -> cancel) behind the
app's own primitives. Also owns the settings-change cascade: a coop-wide
frequency or amount change invalidates every outstanding mandate's authorised
amount (mandateAmount is fixed at creation on Monnify's side), so all of them are
cancelled and affected members notified to re-authorise.

Debit resolution is poll-only for now (no webhook wired), per an explicit
decision — a debit attempt's payment reference is stored on the mandate row and
resolved by a reconciliation pass, not synchronously.
"""
import logging
import secrets
import time
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import DebitStatus, MandateStatus
from app.core.exceptions import AppException, BadRequestException, NotFoundException
from app.models.contribution import Contribution
from app.models.direct_debit_mandate import DirectDebitMandate
from app.repositories.cooperative_repository import CooperativeRepository
from app.repositories.mandate_repository import MandateRepository
from app.repositories.member_repository import MemberRepository
from app.repositories.payment_repository import PaymentRepository
from app.services.payment_provider import get_payment_provider

settings = get_settings()
logger = logging.getLogger("akoweai")

_MANDATE_VALIDITY_YEARS = 5


def generate_mandate_reference() -> str:
    ts_ms = int(time.time() * 1000)
    rand = secrets.token_hex(3).upper()
    return f"AJODA-MANDATE-{ts_ms}-{rand}"


def generate_debit_reference() -> str:
    ts_ms = int(time.time() * 1000)
    rand = secrets.token_hex(3).upper()
    return f"AJODA-DEBIT-{ts_ms}-{rand}"


def _synth_email(phone_number: str) -> str:
    """Members have no email on file — synthesize a deterministic, non-PII
    address (same pattern as the hosted-checkout path in routers/payments.py)."""
    digits = "".join(ch for ch in (phone_number or "") if ch.isdigit())
    return f"{digits or 'member'}@ajoda.app"


class MandateService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.mandate_repo = MandateRepository(db)
        self.payment_repo = PaymentRepository(db)
        self.coop_repo = CooperativeRepository(db)
        self.member_repo = MemberRepository(db)

    async def get_active_mandate(
        self, member_id: UUID, coop_id: UUID
    ) -> DirectDebitMandate | None:
        return await self.mandate_repo.get_active_mandate(member_id, coop_id)

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #
    async def setup(
        self,
        *,
        member,
        coop_id: UUID,
        account_number: str,
        bank_code: str,
    ) -> DirectDebitMandate:
        """Create a mandate authorising Monnify to debit `member` for `coop_id`'s
        current contribution amount each period. Raises if one is already live."""
        existing = await self.mandate_repo.get_active_mandate(member.id, coop_id)
        if existing:
            raise BadRequestException(
                "You already have an auto-pay mandate set up for this cooperative."
            )

        coop = await self.coop_repo.get_by_id(coop_id)
        if not coop:
            raise NotFoundException("Cooperative not found")

        today = date.today()
        end_date = today.replace(year=today.year + _MANDATE_VALIDITY_YEARS)
        reference = generate_mandate_reference()

        mandate = await self.mandate_repo.create(
            member_id=member.id,
            cooperative_id=coop_id,
            mandate_reference=reference,
            mandate_amount_kobo=coop.contribution_amount,
            mandate_start_date=today,
            mandate_end_date=end_date,
        )
        await self.db.commit()
        await self.db.refresh(mandate)

        try:
            result = await get_payment_provider().create_mandate(
                mandate_reference=reference,
                amount_kobo=coop.contribution_amount,
                customer_name=member.full_name,
                customer_phone=member.phone_number,
                customer_email=_synth_email(member.phone_number),
                # Members have no address on file; Monnify requires one. Not a
                # real address collection flow — out of scope for this feature.
                customer_address="Nigeria",
                account_number=account_number,
                bank_code=bank_code,
                description=f"{coop.name} contribution"[:100],
                start_date=today,
                end_date=end_date,
                redirect_url=f"{settings.prod_url}/api/payments/direct-debit/callback",
            )
        except AppException:
            await self.mandate_repo.mark_cancelled(
                mandate.id, "Mandate creation failed with the provider"
            )
            await self.db.commit()
            raise

        await self.mandate_repo.update_status(
            mandate.id,
            status=result["status"] or MandateStatus.INITIATED.value,
            mandate_code=result["mandate_code"],
        )
        if result.get("authorization_link"):
            await self.mandate_repo.set_authorization_link(
                mandate.id, result["authorization_link"]
            )
        await self.db.commit()
        await self.db.refresh(mandate)
        return mandate

    # ------------------------------------------------------------------ #
    # Cancellation
    # ------------------------------------------------------------------ #
    async def cancel(self, mandate: DirectDebitMandate, reason: str) -> None:
        """Cancel a single mandate. Best-effort against Monnify — the local
        CANCELLED status is authoritative for Ajoda's own scheduling regardless of
        whether the provider call itself succeeds, so a transient Monnify failure
        never leaves a member stuck with a mandate we've stopped honouring."""
        if mandate.mandate_code:
            try:
                await get_payment_provider().cancel_mandate(mandate.mandate_code)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Monnify cancel_mandate failed for %s: %s — cancelling locally anyway",
                    mandate.mandate_code, exc,
                )
        await self.mandate_repo.mark_cancelled(mandate.id, reason)
        await self.db.commit()

    async def cancel_all_for_coop(self, coop_id: UUID, reason: str) -> None:
        """
        The settings-change cascade: cancel every non-terminal mandate for this
        coop and notify each affected member. mandateAmount is fixed on Monnify's
        side at creation, so any frequency or contribution-amount change makes
        every outstanding mandate authorise the wrong figure — there is no way to
        "update" a mandate's amount, only cancel and re-authorise. Best-effort per
        mandate: one failure is logged and does not block the others or roll back
        the settings change that triggered this.
        """
        mandates = await self.mandate_repo.get_non_terminal_for_coop(coop_id)
        if not mandates:
            return

        coop = await self.coop_repo.get_by_id(coop_id)
        coop_name = coop.name if coop else "your cooperative"

        for mandate in mandates:
            try:
                await self.cancel(mandate, reason)
            except Exception as exc:  # noqa: BLE001 — cascade must not stop on one failure
                logger.warning(
                    "Cascade cancel failed for mandate %s: %s", mandate.id, exc
                )
                continue

            member = await self.member_repo.get_by_id(mandate.member_id)
            if not member:
                continue
            from app.services.whatsapp_service import send_text_message

            try:
                await send_text_message(
                    member.phone_number,
                    f"⚠️ *{coop_name}* changed its contribution schedule or "
                    "amount, so your auto-pay was cancelled — the old mandate "
                    "authorised the previous figure and can't just be updated.\n\n"
                    "Reply *autopay* to set it up again with the new amount.",
                )
            except Exception as exc:  # noqa: BLE001 — notification is best-effort
                logger.warning(
                    "Auto-pay cascade notification failed to %s: %s",
                    member.phone_number, exc,
                )

    # ------------------------------------------------------------------ #
    # Scheduled debit (called from period_service on period open)
    # ------------------------------------------------------------------ #
    async def debit_for_contribution(
        self, mandate: DirectDebitMandate, contribution: Contribution
    ) -> None:
        """
        Attempt one scheduled debit for a period's contribution. Best-effort and
        never raises — a failed or unresolved attempt simply leaves the
        contribution unpaid for the existing manual pay-link fallback.
        """
        if not mandate.mandate_code:
            return
        if mandate.pending_debit_reference:
            # A previous attempt for this mandate hasn't resolved yet — don't
            # stack a second one.
            return

        member = await self.member_repo.get_by_id(mandate.member_id)
        reference = generate_debit_reference()
        try:
            await get_payment_provider().debit_mandate(
                mandate_code=mandate.mandate_code,
                payment_reference=reference,
                amount_kobo=contribution.amount,
                narration="Cooperative contribution auto-pay"[:100],
                customer_email=_synth_email(member.phone_number if member else ""),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Auto-pay debit failed to initiate for contribution %s: %s",
                contribution.id, exc,
            )
            return

        await self.mandate_repo.set_pending_debit(
            mandate.id, reference=reference, contribution_id=contribution.id
        )
        await self.db.commit()

    async def resolve_pending_debits(self) -> dict:
        """
        Reconciliation pass: poll every mandate with a debit attempt still
        awaiting resolution and settle it. Intended to run alongside the existing
        hourly period-close cron.
        """
        mandates = await self.mandate_repo.get_with_pending_debit()
        resolved, failed = 0, 0
        for mandate in mandates:
            try:
                outcome = await get_payment_provider().get_debit_status(
                    mandate.pending_debit_reference
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Debit status poll failed for mandate %s: %s", mandate.id, exc
                )
                continue

            status = (outcome.get("status") or "").upper()
            if status == DebitStatus.PAID.value:
                # Monnify's own transaction reference — not our pending_debit_reference
                # (paymentReference) — is what a later refund must target.
                settled = await self.payment_repo.settle_single_contribution_if_unpaid(
                    mandate.pending_debit_contribution_id,
                    settlement_reference=(
                        outcome.get("transaction_reference")
                        or mandate.pending_debit_reference
                    ),
                )
                if settled:
                    amount_result = await self.db.execute(
                        select(Contribution.amount).where(
                            Contribution.id == mandate.pending_debit_contribution_id
                        )
                    )
                    amount = amount_result.scalar_one_or_none()
                    if amount is not None:
                        await self.payment_repo.increment_pool_balance(
                            mandate.cooperative_id, amount
                        )
                await self.mandate_repo.clear_pending_debit(mandate.id)
                await self.db.commit()
                resolved += 1
            elif status == DebitStatus.FAILED.value:
                await self.mandate_repo.clear_pending_debit(mandate.id)
                await self.db.commit()
                failed += 1
                member = await self.member_repo.get_by_id(mandate.member_id)
                if member:
                    from app.services.whatsapp_service import send_text_message

                    try:
                        await send_text_message(
                            member.phone_number,
                            "⚠️ Your auto-pay contribution could not be charged "
                            "this period. You can still pay manually from the "
                            "payment link, or reply *autopay* to check your "
                            "mandate.",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Auto-pay failure notification failed to %s: %s",
                            member.phone_number, exc,
                        )
            # else PENDING — leave it, resolved on the next reconciliation pass

        return {"resolved": resolved, "failed": failed, "checked": len(mandates)}
