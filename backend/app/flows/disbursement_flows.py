"""
Disbursement bot flow (Phase 5) — exco-only money-out via WhatsApp.

Reuses the base flow machinery: ConversationFlow.DISBURSE is a blocking flow
(free text routes back into it), the bank step uses an interactive list, and
Confirm/Resend/Cancel are reply buttons. All money work goes through the Phase 3
WithdrawalService engine — the same code path the dashboard uses.

The admin gate lives in dispatch_intent (is_exco); this handler is only reached
for an exco in the active cooperative.
"""
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ConversationFlow, Intent, WithdrawalStatus
from app.core.exceptions import AppException
from app.models.conversation_session import ConversationSession
from app.models.member import Member
from app.services.whatsapp_service import (
    send_list_message,
    send_reply_buttons,
    send_text_message,
)
from app.services.withdrawal_service import (
    WithdrawalService,
    match_banks,
    truncate_bank_row_title,
)

logger = logging.getLogger("akoweai")

# current_step values within the DISBURSE flow
_AMOUNT = 1
_REASON = 2
_ACCOUNT = 3
_BANK = 4
_CONFIRM = 5
_OTP = 6

_FLOW = ConversationFlow.DISBURSE.value


def _reset(session: ConversationSession) -> None:
    session.current_flow = None
    session.current_step = 0
    session.flow_data = {}


def _parse_amount_kobo(text: str) -> int | None:
    cleaned = text.replace("₦", "").replace(",", "").replace(" ", "")
    try:
        naira = float(cleaned)
    except ValueError:
        return None
    if naira <= 0:
        return None
    return int(round(naira * 100))


async def _otp_prompt(phone: str, body: str) -> None:
    await send_reply_buttons(
        phone,
        body,
        [
            {"id": "disburse_resend_otp", "title": "🔁 Resend OTP"},
            {"id": "cancel", "title": "❌ Cancel"},
        ],
    )


async def handle_disbursement_flow(
    phone: str,
    session: ConversationSession,
    coop_id: UUID,
    member: Member,
    db: AsyncSession,
    intent: Intent,
    entities: dict,
) -> None:
    svc = WithdrawalService(db)

    # Entry — begin the flow.
    if session.current_flow != _FLOW:
        session.current_flow = _FLOW
        session.current_step = _AMOUNT
        session.flow_data = {}
        await send_text_message(
            phone,
            "💸 *Withdraw funds*\n\nHow much would you like to withdraw? "
            "Enter an amount in naira (e.g. 50000).",
        )
        return

    # Mark flow_data dirty for the whole request (plain JSONB — in-place mutation
    # is not auto-tracked; the webhook only reassigns it for text messages).
    fd = dict(session.flow_data)
    session.flow_data = fd
    step = session.current_step
    text = (fd.get("current_text") or "").strip()

    # Resend OTP — valid only while awaiting OTP.
    if intent == Intent.DISBURSE_RESEND_OTP:
        if step != _OTP:
            return
        try:
            wd = await svc.get_disbursement_for_coop(
                coop_id, UUID(fd["withdrawal_id"])
            )
            await svc.resend_disbursement_otp(wd)
            await send_text_message(
                phone,
                "📧 A new OTP has been sent to the account owner's email.",
            )
        except AppException as exc:
            await send_text_message(phone, f"⚠️ {exc.message}")
        return

    if step == _AMOUNT:
        amount_kobo = _parse_amount_kobo(text)
        if amount_kobo is None:
            await send_text_message(
                phone, "Please enter a valid amount in naira (e.g. 50000)."
            )
            return
        fd["amount_kobo"] = amount_kobo
        session.current_step = _REASON
        await send_text_message(
            phone, "📝 What is this withdrawal for? (e.g. Generator repair)"
        )
        return

    if step == _REASON:
        if len(text) < 3:
            await send_text_message(
                phone, "Please enter a short reason (at least 3 characters)."
            )
            return
        fd["reason"] = text[:500]
        session.current_step = _ACCOUNT
        await send_text_message(
            phone, "🏦 Enter the destination account number (10 digits)."
        )
        return

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
                phone, session, fd, coop_id, member, svc, row_id.removeprefix("bank_")
            )
        else:
            await _search_banks(phone, svc, text)
        return

    if step == _CONFIRM:
        if intent == Intent.CONFIRM_DISBURSE:
            await _initiate(phone, session, fd, coop_id, member, svc)
        else:
            await send_reply_buttons(
                phone,
                "Please confirm or cancel the transfer.",
                [
                    {"id": "confirm_disburse", "title": "✅ Confirm"},
                    {"id": "cancel", "title": "❌ Cancel"},
                ],
            )
        return

    if step == _OTP:
        otp = "".join(ch for ch in text if ch.isdigit())
        if len(otp) < 4:
            # Stray / malformed input — do not advance the flow.
            await _otp_prompt(
                phone,
                "Please enter the OTP sent to the account owner's email, "
                "or use the options below.",
            )
            return
        await _authorize(phone, session, fd, coop_id, svc, otp)
        return


async def handle_disbursement_history(
    phone: str,
    coop_id: UUID,
    db: AsyncSession,
) -> None:
    """Exco-only: list the cooperative's recent disbursements with their Monnify
    references and statuses (Phase 8 signal-mover — the bot side of the transfer
    history view)."""
    svc = WithdrawalService(db)
    result = await svc.get_withdrawals(coop_id, page=1, page_size=5)
    items = result.get("items", [])

    if not items:
        await send_text_message(
            phone,
            "No disbursements yet. When you withdraw from the pool, each transfer "
            "and its reference will show up here.",
        )
        return

    status_label = {
        WithdrawalStatus.COMPLETED.value: "✅ Completed",
        WithdrawalStatus.FAILED.value: "⚠️ Failed",
        WithdrawalStatus.PROCESSING.value: "⏳ Processing",
        WithdrawalStatus.PENDING_AUTHORIZATION.value: "🔐 Awaiting OTP",
        WithdrawalStatus.INITIATED.value: "• Initiated",
    }
    lines = ["*Recent disbursements*", ""]
    for w in items:
        amount_naira = w["amount"] // 100
        label = status_label.get(w["status"], w["status"])
        lines.append(f"₦{amount_naira:,} — {w['reason']}")
        lines.append(f"{label}")
        if w.get("transfer_reference"):
            lines.append(f"Ref: {w['transfer_reference']}")
        lines.append("")
    await send_text_message(phone, "\n".join(lines).strip())


async def _search_banks(phone: str, svc: WithdrawalService, query: str) -> None:
    query = query.strip()
    if len(query) < 2:
        await send_text_message(phone, "Type at least 2 letters of your bank's name.")
        return
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
    svc: WithdrawalService,
    bank_code: str,
) -> None:
    banks = await svc.get_banks()
    bank = next((b for b in banks if b["code"] == bank_code), None)
    if not bank:
        await send_text_message(
            phone, "That bank wasn't recognised. Type your bank's name again."
        )
        return

    # Name Enquiry — verify the holder before showing the confirm beat.
    try:
        verified = await svc.verify_recipient(fd["account_number"], bank_code)
    except AppException as exc:
        await send_text_message(
            phone, f"⚠️ {exc.message}\n\nType your bank's name again to retry."
        )
        return

    # Bound precondition gate (pool + wallet) — evaluated here, before initiation.
    try:
        await svc.check_precondition_gate(coop_id, fd["amount_kobo"])
    except AppException as exc:
        await send_text_message(phone, f"⛔ {exc.message}")
        _reset(session)
        return

    fd["bank_code"] = bank_code
    fd["bank_name"] = bank["name"]
    fd["account_name"] = verified["account_name"]
    session.current_step = _CONFIRM

    amount_naira = fd["amount_kobo"] // 100
    await send_reply_buttons(
        phone,
        f"You're about to send *₦{amount_naira:,}* to:\n\n"
        f"*{verified['account_name']}*\n"
        f"{bank['name']} · {verified['account_masked']}\n\n"
        f"Reason: {fd['reason']}\n\n"
        "An OTP will be emailed to the account owner to authorize.",
        [
            {"id": "confirm_disburse", "title": "✅ Confirm"},
            {"id": "cancel", "title": "❌ Cancel"},
        ],
    )


async def _initiate(
    phone: str,
    session: ConversationSession,
    fd: dict,
    coop_id: UUID,
    member: Member,
    svc: WithdrawalService,
) -> None:
    try:
        wd = await svc.initiate_disbursement(
            coop_id=coop_id,
            amount_kobo=fd["amount_kobo"],
            reason=fd["reason"],
            account_number=fd["account_number"],
            bank_code=fd["bank_code"],
            account_name=fd["account_name"],
            authorized_by_member_id=member.id,
        )
    except AppException as exc:
        await send_text_message(phone, f"⚠️ {exc.message}")
        _reset(session)
        return

    if wd.status == WithdrawalStatus.PENDING_AUTHORIZATION.value:
        fd["withdrawal_id"] = str(wd.id)
        session.current_step = _OTP
        await _otp_prompt(
            phone,
            "📧 An OTP has been emailed to the account owner.\n\n"
            "Type it here to authorize the transfer, or use the options below.",
        )
    elif wd.status == WithdrawalStatus.FAILED.value:
        await send_text_message(
            phone,
            f"⚠️ The transfer failed: {wd.failure_reason or 'unknown'}. "
            "The pool was not debited.",
        )
        _reset(session)
    else:
        await send_text_message(
            phone, "⏳ Transfer submitted. You'll be notified when it completes."
        )
        _reset(session)


async def _authorize(
    phone: str,
    session: ConversationSession,
    fd: dict,
    coop_id: UUID,
    svc: WithdrawalService,
    otp: str,
) -> None:
    try:
        wd = await svc.get_disbursement_for_coop(coop_id, UUID(fd["withdrawal_id"]))
        await svc.authorize_disbursement(wd, otp)
    except AppException as exc:
        await _otp_prompt(
            phone,
            f"⚠️ {exc.message}\n\nRe-enter the OTP, or use the options below.",
        )
        return  # stay in the OTP step
    await send_text_message(
        phone,
        "⏳ OTP accepted — your transfer is processing. "
        "You'll get a message here when it completes.",
    )
    _reset(session)
