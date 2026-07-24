import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import WithdrawalStatus
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.cooperative import Cooperative
from app.models.coop_member import CoopMember
from app.models.member import Member
from app.models.withdrawal import Withdrawal
from app.services.payment_provider import get_payment_provider
from app.services.payment_service import generate_disbursement_reference
from app.services.whatsapp_service import (
    TEMPLATE_WITHDRAWAL_ALERT,
    send_template_message,
)

settings = get_settings()
logger = logging.getLogger("akoweai")

_TERMINAL = (WithdrawalStatus.COMPLETED.value, WithdrawalStatus.FAILED.value)

# Map Monnify's various transfer status words (from initiate / authorize / poll /
# webhook) onto our five-state machine. Unknown -> PROCESSING (safe; re-polled).
_STATUS_MAP = {
    "SUCCESS": WithdrawalStatus.COMPLETED,
    "COMPLETED": WithdrawalStatus.COMPLETED,
    "PENDING_AUTHORIZATION": WithdrawalStatus.PENDING_AUTHORIZATION,
    "OTP_EMAIL_DISPATCH_FAILED": WithdrawalStatus.PENDING_AUTHORIZATION,
    "PENDING": WithdrawalStatus.PROCESSING,
    "AWAITING_PROCESSING": WithdrawalStatus.PROCESSING,
    "IN_PROGRESS": WithdrawalStatus.PROCESSING,
    "PROCESSING": WithdrawalStatus.PROCESSING,
    "FAILED": WithdrawalStatus.FAILED,
    "REVERSED": WithdrawalStatus.FAILED,
    "EXPIRED": WithdrawalStatus.FAILED,
}


def normalize_transfer_status(monnify_status: str) -> WithdrawalStatus:
    return _STATUS_MAP.get((monnify_status or "").upper(), WithdrawalStatus.PROCESSING)


def _mask_account(account_number: str | None) -> str:
    """Mask all but the last 4 digits of an account number for member-facing text."""
    if not account_number:
        return "••••"
    return "••••" + account_number[-4:]


# Common Nigerian bank acronyms/short names that never literally appear inside
# Monnify's full legal name (e.g. "uba" is not a substring of "United Bank For
# Africa Plc") — plain substring matching misses exactly the names people
# actually type. Not exhaustive; extend as real gaps surface.
BANK_NAME_ALIASES: dict[str, str] = {
    "uba": "united bank for africa",
    "gtb": "guaranty trust",
    "gtbank": "guaranty trust",
    "fcmb": "first city monument",
    "fbn": "first bank",
    "firstbank": "first bank",
    "ubn": "union bank",
    "stanbic": "stanbic ibtc",
    "sterling": "sterling bank",
    "polaris": "polaris bank",
    "keystone": "keystone bank",
    "unity": "unity bank",
    "wema": "wema bank",
    "fidelity": "fidelity bank",
    "heritage": "heritage bank",
    "titan": "titan trust",
    "providus": "providus bank",
    "jaiz": "jaiz bank",
    "suntrust": "suntrust bank",
    "globus": "globus bank",
}


def match_banks(banks: list[dict], query: str) -> list[dict]:
    """
    Substring-match banks by name, expanded with common Nigerian bank acronyms
    that don't literally appear in Monnify's full legal name. Falls back to a
    plain substring match against the raw query for anything not aliased.
    """
    q = query.strip().lower()
    fragment = BANK_NAME_ALIASES.get(q, q)
    return [
        b
        for b in banks
        if fragment in (b.get("name") or "").lower()
        or q in (b.get("name") or "").lower()
    ]


def truncate_bank_row_title(name: str, limit: int = 24) -> str:
    """
    WhatsApp list row titles are hard-capped at 24 characters. A blind slice
    can cut mid-word (e.g. "United Bank For Africa Plc" -> "United Bank For
    Africa P") which reads as broken. Cut at the last full word instead and
    mark the truncation with an ellipsis.
    """
    if len(name) <= limit:
        return name
    cut = name[: limit - 1].rsplit(" ", 1)[0].strip()
    return f"{cut}…" if cut else name[: limit - 1]


def humanize_failure(description: str, status: str) -> str:
    """
    Map Monnify's raw failure classes onto specific, exco-facing messages so a
    live failure is diagnosable on the spot (Phase 8 graceful-failure UX). The
    raw Monnify description is preserved as the fallback rather than discarded.
    """
    text = f"{description} {status}".lower()

    if "insufficient" in text:
        return (
            "The disbursement wallet had insufficient funds for this transfer. "
            "Fund the wallet and retry."
        )
    if "duplicate" in text:
        return (
            "A duplicate transfer was blocked. Wait a moment, then retry the same "
            "withdrawal — a new transfer is never created for a retry."
        )
    if "reversed" in text:
        return "The transfer was reversed; the funds were returned to the wallet."
    if "expired" in text:
        return "The transfer expired before it was authorized. Start a new withdrawal."
    if any(k in text for k in ("timeout", "timed out", "not respond", "unavailable")):
        return (
            "The recipient's bank did not respond in time, so no money was sent. "
            "Please retry the withdrawal."
        )
    if any(k in text for k in ("invalid account", "account name", "name mismatch", "not found")):
        return (
            "The recipient account could not be validated. Check the account number "
            "and bank, then try again."
        )

    return description.strip() or "The transfer failed and no money was sent."


class WithdrawalService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # record_withdrawal (log-only, debited at record time) was retired in Phase 4 —
    # every withdrawal is now a real disbursement through the engine below.
    # _broadcast_withdrawal_notification is retained for Phase 6, which fires the
    # member broadcast on COMPLETED.

    async def _broadcast_withdrawal_notification(
        self,
        withdrawal: Withdrawal,
        coop: Cooperative,
        authorized_member_name: str,
    ) -> None:
        """
        Send the coop_withdrawal_alert template to every active member.
        Template variables:
          {{1}} cooperative name
          {{2}} amount in naira (integer string)
          {{3}} reason
          {{4}} authorized by name
          {{5}} date e.g. "24 Mar 2026"
          {{6}} pool balance after in naira (integer string)
        """
        result = await self.db.execute(
            select(Member.phone_number, Member.full_name)
            .join(CoopMember, CoopMember.member_id == Member.id)
            .where(CoopMember.cooperative_id == withdrawal.cooperative_id)
        )
        members = result.all()

        amount_naira = str(withdrawal.amount // 100)
        balance_naira = str(withdrawal.pool_balance_after // 100)
        date_str = withdrawal.created_at.strftime("%d %b %Y")

        components = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": coop.name},
                    {"type": "text", "text": amount_naira},
                    {"type": "text", "text": withdrawal.reason},
                    {"type": "text", "text": authorized_member_name},
                    {"type": "text", "text": date_str},
                    {"type": "text", "text": balance_naira},
                ],
            }
        ]

        for phone, _name in members:
            try:
                await send_template_message(
                    to=phone,
                    template_name=TEMPLATE_WITHDRAWAL_ALERT,
                    components=components,
                )
            except Exception as exc:
                logger.warning(
                    "Withdrawal broadcast failed to %s: %s", phone, exc
                )

    async def get_withdrawals(
        self,
        coop_id: UUID,
        page: int,
        page_size: int,
    ) -> dict:
        """
        Return paginated withdrawal log for a cooperative, newest first.
        Joins the authorized member's name for display.
        Returns total count and has_more flag per D33.
        """
        offset = (page - 1) * page_size

        # Total count — separate query, cheap on indexed FK column
        count_result = await self.db.execute(
            select(func.count(Withdrawal.id)).where(
                Withdrawal.cooperative_id == coop_id
            )
        )
        total = count_result.scalar_one()

        result = await self.db.execute(
            select(
                Withdrawal.id,
                Withdrawal.amount,
                Withdrawal.reason,
                Withdrawal.pool_balance_after,
                Withdrawal.status,
                Withdrawal.transfer_reference,
                Withdrawal.created_at,
                Member.full_name.label("authorized_by_name"),
            )
            .join(Member, Member.id == Withdrawal.authorized_by_member_id)
            .where(Withdrawal.cooperative_id == coop_id)
            .order_by(Withdrawal.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )

        items = [
            {
                "id": row.id,
                "amount": row.amount,
                "reason": row.reason,
                "authorized_by_name": row.authorized_by_name,
                "pool_balance_after": row.pool_balance_after,
                "status": row.status,
                "transfer_reference": row.transfer_reference,
                "created_at": row.created_at,
            }
            for row in result.all()
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "has_more": total > page * page_size,
        }

    # ================================================================== #
    # Disbursement engine (Phase 3) — consumed by the dashboard (Phase 4)
    # and the bot (Phase 5) surfaces.
    # ================================================================== #

    # --- Thin provider passthroughs (keep surfaces off the provider directly) ---
    async def get_banks(self) -> list[dict]:
        return await get_payment_provider().get_banks()

    async def get_direct_debit_banks(self) -> list[dict]:
        return await get_payment_provider().get_direct_debit_banks()

    async def verify_recipient(self, account_number: str, bank_code: str) -> dict:
        """Name Enquiry — returns the verified holder name for a Confirm/Cancel beat."""
        return await get_payment_provider().name_enquiry(account_number, bank_code)

    async def get_wallet_balance(self) -> dict:
        return await get_payment_provider().wallet_balance()

    async def check_precondition_gate(self, coop_id: UUID, amount_kobo: int) -> None:
        """Public gate check for surfaces that evaluate it before initiation (the
        bot confirm beat). Raises BadRequestException with the specific reason."""
        result = await self.db.execute(
            select(Cooperative).where(Cooperative.id == coop_id)
        )
        coop = result.scalar_one_or_none()
        if not coop:
            raise NotFoundException("Cooperative not found")
        await self._evaluate_precondition_gate(coop, amount_kobo)

    async def get_withdrawal_by_reference(self, reference: str) -> Withdrawal | None:
        result = await self.db.execute(
            select(Withdrawal).where(Withdrawal.transfer_reference == reference)
        )
        return result.scalar_one_or_none()

    async def get_disbursement_for_coop(
        self, coop_id: UUID, withdrawal_id: UUID
    ) -> Withdrawal:
        """
        Load a withdrawal scoped to its cooperative (IDOR guard). An exco of one
        cooperative can never act on another cooperative's withdrawal.
        """
        result = await self.db.execute(
            select(Withdrawal).where(
                Withdrawal.id == withdrawal_id,
                Withdrawal.cooperative_id == coop_id,
            )
        )
        withdrawal = result.scalar_one_or_none()
        if withdrawal is None:
            raise NotFoundException("Withdrawal not found")
        return withdrawal

    async def get_disbursement_status(
        self, coop_id: UUID, withdrawal_id: UUID
    ) -> Withdrawal:
        """
        Scoped status read with reconciliation-on-read: if the transfer is still
        PROCESSING, poll Monnify and resolve before returning, so the dashboard
        settles terminal status even when the webhook cannot reach a local instance.
        """
        withdrawal = await self.get_disbursement_for_coop(coop_id, withdrawal_id)
        if (
            withdrawal.status == WithdrawalStatus.PROCESSING.value
            and withdrawal.transfer_reference
        ):
            try:
                await self.poll_and_resolve_transfer(withdrawal.transfer_reference)
            except Exception as exc:  # noqa: BLE001 — read must not fail on poll error
                logger.warning("Status poll failed for %s: %s", withdrawal_id, exc)
            withdrawal = await self.get_disbursement_for_coop(coop_id, withdrawal_id)
        return withdrawal

    # --- Precondition gate ---
    async def _evaluate_precondition_gate(
        self, coop: Cooperative, amount_kobo: int
    ) -> None:
        """
        The bound gate: BOTH the pool AND the disbursement wallet must be sufficient
        before any transfer is initiated. Distinct messages so the failure is
        diagnosable in a live demo.
        """
        # 1. Pool sufficiency (is the withdrawal legitimate?)
        if amount_kobo > coop.pool_balance:
            raise BadRequestException(
                "The cooperative pool has insufficient funds. "
                f"Available: ₦{coop.pool_balance // 100:,}, "
                f"requested: ₦{amount_kobo // 100:,}."
            )
        # 2. Wallet sufficiency incl. fee buffer (can we actually execute it?)
        wallet = await get_payment_provider().wallet_balance()
        needed = amount_kobo + settings.monnify_transfer_fee_buffer_kobo
        if wallet["available_kobo"] < needed:
            raise BadRequestException(
                "The disbursement wallet needs funding. "
                f"Available: ₦{wallet['available_kobo'] // 100:,}, "
                f"required (incl. fees): ₦{needed // 100:,}."
            )

    # --- Initiation ---
    async def initiate_disbursement(
        self,
        *,
        coop_id: UUID,
        amount_kobo: int,
        reason: str,
        account_number: str,
        bank_code: str,
        account_name: str,
        authorized_by_member_id: UUID,
    ) -> Withdrawal:
        """
        Run the precondition gate, create the withdrawal, and initiate the Monnify
        transfer (async=true → PENDING_AUTHORIZATION with MFA on). The reference is
        generated once and persisted before the transfer exists, so a webhook can
        always resolve back to this withdrawal.
        """
        if amount_kobo <= 0:
            raise BadRequestException("Withdrawal amount must be greater than zero")

        coop_result = await self.db.execute(
            select(Cooperative).where(Cooperative.id == coop_id)
        )
        coop = coop_result.scalar_one_or_none()
        if not coop:
            raise NotFoundException("Cooperative not found")

        await self._evaluate_precondition_gate(coop, amount_kobo)

        withdrawal = Withdrawal(
            cooperative_id=coop_id,
            amount=amount_kobo,
            reason=reason,
            authorized_by_member_id=authorized_by_member_id,
            status=WithdrawalStatus.INITIATED.value,
            transfer_reference=generate_disbursement_reference(),
            destination_account_number=account_number,
            destination_bank_code=bank_code,
            destination_account_name=account_name,
        )
        self.db.add(withdrawal)
        await self.db.commit()
        await self.db.refresh(withdrawal)

        return await self._run_initiation(withdrawal)

    async def reinitiate_disbursement(self, withdrawal: Withdrawal) -> Withdrawal:
        """
        Retry initiation for a withdrawal, REUSING its existing reference (never a
        fresh one). Monnify dedups on the reference, so a retry cannot create a
        second transfer. Only INITIATED/FAILED withdrawals are retryable.
        """
        if not withdrawal.transfer_reference:
            raise BadRequestException("This withdrawal has no reference to retry.")
        if withdrawal.status not in (
            WithdrawalStatus.INITIATED.value,
            WithdrawalStatus.FAILED.value,
        ):
            raise BadRequestException("This withdrawal is not in a retryable state.")

        coop_result = await self.db.execute(
            select(Cooperative).where(Cooperative.id == withdrawal.cooperative_id)
        )
        coop = coop_result.scalar_one_or_none()
        if not coop:
            raise NotFoundException("Cooperative not found")
        await self._evaluate_precondition_gate(coop, withdrawal.amount)

        await self.db.execute(
            update(Withdrawal)
            .where(Withdrawal.id == withdrawal.id)
            .values(
                status=WithdrawalStatus.INITIATED.value,
                failure_reason=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()
        await self.db.refresh(withdrawal)
        return await self._run_initiation(withdrawal)

    async def _run_initiation(self, withdrawal: Withdrawal) -> Withdrawal:
        """
        Call Monnify to initiate the transfer for an already-persisted withdrawal,
        reusing its stored reference and destination. Shared by initiate and retry.
        """
        now = datetime.now(timezone.utc)
        try:
            result = await get_payment_provider().initiate_transfer(
                reference=withdrawal.transfer_reference,
                amount_kobo=withdrawal.amount,
                bank_code=withdrawal.destination_bank_code,
                account_number=withdrawal.destination_account_number,
                account_name=withdrawal.destination_account_name,
                narration=withdrawal.reason[:100],
            )
        except Exception as exc:
            reason_txt = getattr(exc, "message", None) or "Transfer initiation failed."
            await self.db.execute(
                update(Withdrawal)
                .where(Withdrawal.id == withdrawal.id)
                .values(
                    status=WithdrawalStatus.FAILED.value,
                    failure_reason=reason_txt[:500],
                    updated_at=now,
                )
            )
            await self.db.commit()
            raise

        our_status = normalize_transfer_status(result["status"])
        await self.db.execute(
            update(Withdrawal)
            .where(Withdrawal.id == withdrawal.id)
            .values(status=our_status.value, updated_at=now)
        )
        await self.db.commit()
        await self.db.refresh(withdrawal)
        return withdrawal

    # --- OTP authorization ---
    async def authorize_disbursement(
        self, withdrawal: Withdrawal, otp: str
    ) -> Withdrawal:
        if withdrawal.status != WithdrawalStatus.PENDING_AUTHORIZATION.value:
            raise BadRequestException(
                "This transfer is not awaiting OTP authorization."
            )
        result = await get_payment_provider().authorize_transfer(
            withdrawal.transfer_reference, otp
        )
        our_status = normalize_transfer_status(result["status"])
        now = datetime.now(timezone.utc)

        if our_status == WithdrawalStatus.FAILED:
            await self._fail_withdrawal(
                withdrawal.transfer_reference, "Transfer failed during authorization."
            )
        else:
            # async=true: the terminal state comes from the webhook/poll, not here.
            # Conditional so a fast webhook that already resolved isn't clobbered.
            await self.db.execute(
                update(Withdrawal)
                .where(
                    Withdrawal.id == withdrawal.id,
                    Withdrawal.status == WithdrawalStatus.PENDING_AUTHORIZATION.value,
                )
                .values(status=WithdrawalStatus.PROCESSING.value, updated_at=now)
            )
            await self.db.commit()
        await self.db.refresh(withdrawal)
        return withdrawal

    async def resend_disbursement_otp(self, withdrawal: Withdrawal) -> None:
        if withdrawal.status != WithdrawalStatus.PENDING_AUTHORIZATION.value:
            raise BadRequestException(
                "This transfer is not awaiting OTP authorization."
            )
        await get_payment_provider().resend_transfer_otp(withdrawal.transfer_reference)

    # --- Terminal resolution (webhook + poll), idempotent ---
    async def resolve_transfer_status(
        self,
        reference: str,
        monnify_status: str,
        monnify_reference: str = "",
        description: str = "",
    ) -> None:
        our_status = normalize_transfer_status(monnify_status)
        if our_status == WithdrawalStatus.COMPLETED:
            await self._complete_withdrawal(reference, monnify_reference)
        elif our_status == WithdrawalStatus.FAILED:
            await self._fail_withdrawal(
                reference, humanize_failure(description, monnify_status)
            )
        else:
            # Non-terminal update (e.g. still processing) — advance from a pre-processing
            # state only; never regress a terminal one.
            await self.db.execute(
                update(Withdrawal)
                .where(
                    Withdrawal.transfer_reference == reference,
                    Withdrawal.status.in_(
                        [
                            WithdrawalStatus.INITIATED.value,
                            WithdrawalStatus.PENDING_AUTHORIZATION.value,
                        ]
                    ),
                )
                .values(
                    status=WithdrawalStatus.PROCESSING.value,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await self.db.commit()

    async def poll_and_resolve_transfer(self, reference: str) -> None:
        """Reconciliation fallback for a missed disbursement webhook."""
        status = await get_payment_provider().get_transfer_status(reference)
        await self.resolve_transfer_status(
            reference,
            status["status"],
            status.get("monnify_reference", ""),
            status.get("description", ""),
        )

    async def _complete_withdrawal(
        self, reference: str, monnify_reference: str
    ) -> None:
        now = datetime.now(timezone.utc)
        # Atomically claim the withdrawal — only the first caller (webhook or poll)
        # transitions it to COMPLETED and runs the pool debit. A duplicate delivery
        # finds it already terminal and is a no-op.
        claim = await self.db.execute(
            update(Withdrawal)
            .where(
                Withdrawal.transfer_reference == reference,
                Withdrawal.status.notin_(_TERMINAL),
            )
            .values(
                status=WithdrawalStatus.COMPLETED.value,
                monnify_transaction_reference=(
                    monnify_reference or Withdrawal.monnify_transaction_reference
                ),
                updated_at=now,
            )
            .returning(
                Withdrawal.id, Withdrawal.cooperative_id, Withdrawal.amount
            )
        )
        row = claim.first()
        if row is None:
            return  # already resolved — idempotent
        wid, coop_id, amount = row

        # Debit the pool once, at COMPLETED, with the atomic fail-closed guard.
        debit = await self.db.execute(
            update(Cooperative)
            .where(Cooperative.id == coop_id, Cooperative.pool_balance >= amount)
            .values(pool_balance=Cooperative.pool_balance - amount)
            .returning(Cooperative.pool_balance)
        )
        new_balance = debit.scalar_one_or_none()
        if new_balance is None:
            # Money already left the wallet but the pool can't cover it — critical
            # reconciliation gap. Keep the completion (do not lose the transfer).
            logger.critical(
                "Pool debit failed at COMPLETED for withdrawal %s (ref=%s): pool "
                "insufficient — manual reconciliation required.",
                wid,
                reference,
            )
            await self.db.commit()
        else:
            await self.db.execute(
                update(Withdrawal)
                .where(Withdrawal.id == wid)
                .values(pool_balance_after=new_balance)
            )
            await self.db.commit()
        await self._notify_exco_terminal(wid)
        # Phase 6: transparency broadcast to all members — fires ONLY here, on
        # COMPLETED, never on FAILED.
        await self._broadcast_completed_disbursement(wid)

    async def _fail_withdrawal(self, reference: str, reason: str) -> None:
        claim = await self.db.execute(
            update(Withdrawal)
            .where(
                Withdrawal.transfer_reference == reference,
                Withdrawal.status.notin_(_TERMINAL),
            )
            .values(
                status=WithdrawalStatus.FAILED.value,
                failure_reason=(reason or "Transfer failed")[:500],
                updated_at=datetime.now(timezone.utc),
            )
            .returning(Withdrawal.id)
        )
        wid = claim.scalar_one_or_none()
        if wid is None:
            return  # already terminal — no debit, idempotent
        await self.db.commit()
        await self._notify_exco_terminal(wid)

    async def _notify_exco_terminal(self, withdrawal_id: UUID) -> None:
        """Message the initiating exco with the outcome. Errors are logged, not raised."""
        result = await self.db.execute(
            select(Withdrawal).where(Withdrawal.id == withdrawal_id)
        )
        w = result.scalar_one_or_none()
        if not w:
            return
        member_result = await self.db.execute(
            select(Member).where(Member.id == w.authorized_by_member_id)
        )
        member = member_result.scalar_one_or_none()
        if not member:
            return

        amount_naira = w.amount // 100
        masked = _mask_account(w.destination_account_number)
        if w.status == WithdrawalStatus.COMPLETED.value:
            text = (
                f"✅ Disbursement complete.\n₦{amount_naira:,} sent to "
                f"{w.destination_account_name} ({masked}).\nRef: {w.transfer_reference}"
            )
        elif w.status == WithdrawalStatus.FAILED.value:
            text = (
                f"⚠️ Disbursement failed.\n₦{amount_naira:,} to {masked} was not sent.\n"
                f"Reason: {w.failure_reason or 'unknown'}.\nThe pool was not debited."
            )
        else:
            return

        from app.services.whatsapp_service import send_text_message

        try:
            await send_text_message(member.phone_number, text)
        except Exception as exc:  # noqa: BLE001 — notification is best-effort
            logger.warning("Exco disbursement notification failed: %s", exc)

    async def _broadcast_completed_disbursement(self, withdrawal_id: UUID) -> None:
        """
        Phase 6 transparency broadcast. Fires only on COMPLETED. Sends every member a
        FREE-FORM message (send_text_message — not a Meta template, so no re-approval)
        carrying the real Monnify transfer reference and completed status. The
        recipient account is masked to the last 4; the verified holder name is exco-only
        and is NOT broadcast. Best-effort — per-member failures are logged, not raised.

        Note: free-form messages only deliver within WhatsApp's 24h session window; a
        member silent >24h will not receive this. Switch on the retained
        `_broadcast_withdrawal_notification` template for guaranteed delivery if needed.
        """
        w_result = await self.db.execute(
            select(Withdrawal).where(Withdrawal.id == withdrawal_id)
        )
        w = w_result.scalar_one_or_none()
        if not w or w.status != WithdrawalStatus.COMPLETED.value:
            return

        coop_result = await self.db.execute(
            select(Cooperative).where(Cooperative.id == w.cooperative_id)
        )
        coop = coop_result.scalar_one_or_none()
        coop_name = coop.name if coop else "your cooperative"

        auth_result = await self.db.execute(
            select(Member.full_name).where(Member.id == w.authorized_by_member_id)
        )
        authoriser = auth_result.scalar_one_or_none() or "an exco"

        members_result = await self.db.execute(
            select(Member.phone_number)
            .join(CoopMember, CoopMember.member_id == Member.id)
            .where(CoopMember.cooperative_id == w.cooperative_id)
        )
        phones = [row[0] for row in members_result.all()]

        amount_naira = w.amount // 100
        date_str = (w.updated_at or w.created_at).strftime("%d %b %Y")
        masked = _mask_account(w.destination_account_number)
        lines = [
            f"📢 *{coop_name}* — pool disbursement",
            "",
            f"₦{amount_naira:,} was disbursed from the pool on {date_str}.",
            "",
            f"For: {w.reason}",
            f"Authorised by: {authoriser}",
            f"To account: {masked}",
            f"Ref: {w.transfer_reference} (completed)",
        ]
        if w.pool_balance_after is not None:
            lines.append("")
            lines.append(f"Pool balance now: ₦{w.pool_balance_after // 100:,}")
        text = "\n".join(lines)

        from app.services.whatsapp_service import send_text_message

        for phone in phones:
            try:
                await send_text_message(phone, text)
            except Exception as exc:  # noqa: BLE001 — broadcast is best-effort
                logger.warning("Disbursement broadcast failed to %s: %s", phone, exc)