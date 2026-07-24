"""
Auto-pay bot flow — member-facing direct-debit (recurring contribution) setup.

Reuses the base flow machinery the same way disbursement_flows.py does:
ConversationFlow.AUTOPAY_ENABLE is a blocking flow (free text routes back into
it), the bank step uses an interactive list, and Confirm/Cancel are reply
buttons. A member with an existing mandate never re-enters setup — tapping the
entry point instead shows their current status with a cancel option.

The account/bank fields are member-supplied, so bank search and name enquiry
reuse WithdrawalService's thin provider passthroughs (get_banks / verify_recipient)
rather than duplicating them — those methods have no disbursement-specific logic,
they're just Monnify Get Banks / Name Enquiry.
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
    send_list_message,
    send_reply_buttons,
    send_text_message,
)
from app.services.withdrawal_service import (
    WithdrawalService,
    _mask_account,
    match_banks,
    truncate_bank_row_title,
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
            await _show_existing_mandate(phone, existing)
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
        await send_text_message(
            phone, "🔎 Type your bank's name (e.g. Access, GTBank, Opay, Kuda)."
        )
        return

    if step == _BANK:
        row_id = entities.get("row_id", "")
        if row_id.startswith("bank_"):
            await _bank_selected(
                phone, session, fd, coop_id, member, db, row_id.removeprefix("bank_")
            )
        else:
            await _search_banks(phone, db, text)
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


async def _show_existing_mandate(phone: str, mandate) -> None:
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


async def _search_banks(phone: str, db: AsyncSession, query: str) -> None:
    query = query.strip()
    if len(query) < 2:
        await send_text_message(phone, "Type at least 2 letters of your bank's name.")
        return
    svc = WithdrawalService(db)
    try:
        banks = await svc.get_banks()
    except AppException as exc:
        await send_text_message(phone, f"⚠️ {exc.message}")
        return
    matches = match_banks(banks, query)
    if not matches:
        await send_text_message(
            phone, f"No bank matches '{query}'. Try a different spelling."
        )
        return
    shown = matches[:10]

    # 3 or fewer matches (the common case once acronyms resolve to one bank)
    # fit as reply buttons — a single tap, no extra "Choose Bank" step.
    if len(shown) <= 3:
        await send_reply_buttons(
            phone,
            "Select your bank:",
            [
                {
                    "id": f"bank_{b['code']}",
                    "title": truncate_bank_row_title(b["name"] or b["code"], limit=20),
                }
                for b in shown
            ],
        )
        return

    rows = [
        {"id": f"bank_{b['code']}", "title": truncate_bank_row_title(b["name"] or b["code"])}
        for b in shown
    ]
    body = (
        "Select your bank:"
        if len(matches) <= 10
        else "Showing the first 10 matches — type more of the name to narrow it down."
    )
    await send_list_message(
        phone,
        header="Select Bank",
        body=body,
        button_text="Choose Bank",
        sections=[{"title": "Banks", "rows": rows}],
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
    banks = await svc.get_banks()
    bank = next((b for b in banks if b["code"] == bank_code), None)
    if not bank:
        await send_text_message(
            phone, "That bank wasn't recognised. Type your bank's name again."
        )
        return

    try:
        verified = await svc.verify_recipient(fd["account_number"], bank_code)
    except AppException as exc:
        await send_text_message(
            phone, f"⚠️ {exc.message}\n\nType your bank's name again to retry."
        )
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
