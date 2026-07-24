"""
Auto-pay bot flow — member-facing direct-debit (recurring contribution) setup.

ConversationFlow.AUTOPAY_ENABLE is a blocking flow (free text routes back into
it), and Confirm/Cancel are reply buttons. A member with an existing mandate
never re-enters setup — tapping the entry point instead shows their current
status with a cancel option.

Bank selection is a fixed, numbered list, not a search: Direct Debit only
works against the ~26 banks Monnify's docs confirm as supported (a small
subset of the ~100+ banks get_banks() returns for disbursement), so there's
nothing to search — every eligible bank is shown up front and the member
replies with its number. That list comes from
WithdrawalService.get_direct_debit_banks() (a thin passthrough to the
PaymentProvider boundary), not a hardcoded constant here, so a future gateway
swap only needs a new provider implementation. Name enquiry still reuses
WithdrawalService.verify_recipient() — that has no disbursement-specific
logic, it's just Monnify Name Enquiry.
"""
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ConversationFlow, Intent, MANDATE_ACTIVE_STATUSES
from app.core.exceptions import AppException
from app.models.conversation_session import ConversationSession
from app.models.member import Member
from app.repositories.cooperative_repository import CooperativeRepository
from app.services.mandate_service import MandateService
from app.services.whatsapp_service import (
    send_cta_url_button,
    send_reply_buttons,
    send_text_message,
)
from app.services.withdrawal_service import (
    WithdrawalService,
    _mask_account,
)

logger = logging.getLogger("akoweai")

# current_step values within the AUTOPAY_ENABLE flow
_ACCOUNT = 1
_BANK = 2
_CONFIRM = 3

_FLOW = ConversationFlow.AUTOPAY_ENABLE.value


def _reset(session: ConversationSession) -> None:
    session.current_flow = None
    session.current_step = 0
    session.flow_data = {}


async def handle_autopay_flow(
    phone: str,
    session: ConversationSession,
    coop_id: UUID,
    member: Member,
    db: AsyncSession,
    intent: Intent,
    entities: dict,
) -> None:
    mandate_svc = MandateService(db)

    # Entry — decide whether this is "set up" or "manage an existing one".
    if session.current_flow != _FLOW:
        existing = await mandate_svc.get_active_mandate(member.id, coop_id)
        if existing:
            await _show_existing_mandate(phone, existing, mandate_svc)
            return

        coop = await CooperativeRepository(db).get_by_id(coop_id)
        amount_naira = (coop.contribution_amount // 100) if coop else 0
        session.current_flow = _FLOW
        session.current_step = _ACCOUNT
        session.flow_data = {}
        await send_text_message(
            phone,
            "🔁 *Set up auto-pay*\n\n"
            f"This authorises your bank to send *₦{amount_naira:,}* to "
            f"{coop.name if coop else 'this cooperative'} automatically each "
            "contribution period — no more tapping a link every time. You "
            "confirm it on your own bank's page, Ajoda never sees your bank "
            "login.\n\nIf the cooperative's amount or schedule ever changes, "
            "this mandate is cancelled and you'll be asked to set up a new one "
            "for the new amount.\n\n"
            "Enter the 10-digit account number to debit.",
        )
        return

    fd = dict(session.flow_data)
    session.flow_data = fd
    step = session.current_step
    text = (fd.get("current_text") or "").strip()

    if step == _ACCOUNT:
        acct = "".join(ch for ch in text if ch.isdigit())
        if len(acct) != 10:
            await send_text_message(
                phone, "Please enter a valid 10-digit account number."
            )
            return
        fd["account_number"] = acct
        session.current_step = _BANK
        await _prompt_bank_selection(phone, db)
        return

    if step == _BANK:
        banks = await WithdrawalService(db).get_direct_debit_banks()
        choice = text.strip()
        if not choice.isdigit() or not (1 <= int(choice) <= len(banks)):
            await send_text_message(
                phone, f"Please reply with a number from 1 to {len(banks)}."
            )
            return
        bank = banks[int(choice) - 1]
        await _bank_selected(phone, session, fd, coop_id, member, db, bank["code"])
        return

    if step == _CONFIRM:
        if intent == Intent.AUTOPAY_ENABLE:
            await _setup(phone, session, fd, coop_id, member, mandate_svc)
        else:
            await send_reply_buttons(
                phone,
                "Please confirm or cancel.",
                [
                    {"id": "autopay_enable", "title": "✅ Confirm"},
                    {"id": "cancel", "title": "❌ Cancel"},
                ],
            )
        return


async def handle_autopay_cancel_flow(
    phone: str,
    coop_id: UUID,
    member: Member,
    db: AsyncSession,
    intent: Intent,
) -> None:
    """
    Separate from the setup flow — triggered by the "Cancel auto-pay" button
    shown alongside an existing mandate's status. Stateless: re-resolves the
    member's active mandate for the current coop rather than carrying it in
    session state, since it's a single confirm step.
    """
    mandate_svc = MandateService(db)
    mandate = await mandate_svc.get_active_mandate(member.id, coop_id)
    if not mandate:
        await send_text_message(phone, "You don't have an active auto-pay mandate.")
        return

    if intent == Intent.AUTOPAY_CONFIRM_CANCEL:
        await mandate_svc.cancel(mandate, "Cancelled by member")
        await send_text_message(phone, "✅ Auto-pay cancelled.")
        return

    await send_reply_buttons(
        phone,
        "Cancel your auto-pay mandate? You'll go back to paying manually each "
        "period.",
        [
            {"id": "autopay_confirm_cancel", "title": "❌ Yes, cancel"},
            {"id": "cancel", "title": "Keep it"},
        ],
    )


async def _show_existing_mandate(
    phone: str, mandate, mandate_svc: MandateService
) -> None:
    # Reconciliation-on-read: our row is only ever written once at creation
    # (or by a webhook that's never confirmed registered), so actively check
    # with Monnify before deciding what to tell the member — a mandate can
    # activate on Monnify's own timeline with no action from us in between.
    if mandate.status not in MANDATE_ACTIVE_STATUSES:
        mandate = await mandate_svc.refresh_mandate_status(mandate)

    amount_naira = mandate.mandate_amount_kobo // 100
    if mandate.status in MANDATE_ACTIVE_STATUSES:
        await send_reply_buttons(
            phone,
            f"🔁 Auto-pay is *active* — ₦{amount_naira:,} is charged automatically "
            "each period.",
            [
                {"id": "autopay_cancel", "title": "❌ Cancel auto-pay"},
                {"id": "cancel", "title": "OK"},
            ],
        )
        return

    if mandate.authorization_link:
        await send_cta_url_button(
            phone,
            f"🔁 Auto-pay for ₦{amount_naira:,} is still awaiting your bank's "
            "authorisation. Tap below to finish it.",
            "Authorise",
            mandate.authorization_link,
        )
    else:
        await send_text_message(
            phone,
            f"🔁 Auto-pay for ₦{amount_naira:,} is still being set up with the "
            "provider. Try again shortly.",
        )
    await send_reply_buttons(
        phone,
        "Or, if you'd rather not continue:",
        [{"id": "autopay_cancel", "title": "❌ Cancel auto-pay"}],
    )


async def _prompt_bank_selection(phone: str, db: AsyncSession) -> None:
    """
    Direct Debit only works against a fixed, small set of banks — not the full
    disbursement bank universe — so there's nothing to search. Show all of them
    numbered and let the member reply with a digit.
    """
    banks = await WithdrawalService(db).get_direct_debit_banks()
    listing = "\n".join(f"{i}. {b['name']}" for i, b in enumerate(banks, start=1))
    await send_text_message(
        phone, f"🔎 Select your bank — reply with its number:\n\n{listing}"
    )


async def _bank_selected(
    phone: str,
    session: ConversationSession,
    fd: dict,
    coop_id: UUID,
    member: Member,
    db: AsyncSession,
    bank_code: str,
) -> None:
    svc = WithdrawalService(db)
    banks = await svc.get_direct_debit_banks()
    bank = next((b for b in banks if b["code"] == bank_code), None)
    if not bank:
        await send_text_message(
            phone, "That bank wasn't recognised. Please try again."
        )
        await _prompt_bank_selection(phone, db)
        return

    try:
        verified = await svc.verify_recipient(fd["account_number"], bank_code)
    except AppException as exc:
        await send_text_message(
            phone, f"⚠️ {exc.message}\n\nSelect your bank again to retry."
        )
        await _prompt_bank_selection(phone, db)
        return

    fd["bank_code"] = bank_code
    fd["bank_name"] = bank["name"]
    fd["account_name"] = verified["account_name"]
    session.current_step = _CONFIRM

    coop = await CooperativeRepository(db).get_by_id(coop_id)
    amount_naira = (coop.contribution_amount // 100) if coop else 0
    await send_reply_buttons(
        phone,
        f"Set up auto-pay of *₦{amount_naira:,}* each period from:\n\n"
        f"*{verified['account_name']}*\n"
        f"{bank['name']} · {_mask_account(verified['account_number'])}\n\n"
        "You'll confirm this on your bank's own page next.",
        [
            {"id": "autopay_enable", "title": "✅ Confirm"},
            {"id": "cancel", "title": "❌ Cancel"},
        ],
    )


async def _setup(
    phone: str,
    session: ConversationSession,
    fd: dict,
    coop_id: UUID,
    member: Member,
    mandate_svc: MandateService,
) -> None:
    try:
        mandate = await mandate_svc.setup(
            member=member,
            coop_id=coop_id,
            account_number=fd["account_number"],
            bank_code=fd["bank_code"],
        )
    except AppException as exc:
        await send_text_message(phone, f"⚠️ {exc.message}")
        _reset(session)
        return

    _reset(session)
    if mandate.authorization_link:
        await send_cta_url_button(
            phone,
            "One more step — authorise this with your own bank to activate it.",
            "Authorise",
            mandate.authorization_link,
        )
    else:
        await send_text_message(
            phone,
            "Your mandate was created and is being set up with the provider. "
            "Reply *autopay* shortly to check on it.",
        )
