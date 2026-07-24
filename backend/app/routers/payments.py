import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionFactory, get_db
from app.core.dependencies import get_current_member
from app.core.exceptions import AppException, BadRequestException, NotFoundException
from app.core.responses import ApiResponse
from app.models.member import Member
from app.repositories.cooperative_repository import CooperativeRepository
from app.repositories.member_repository import MemberRepository
from app.repositories.payment_repository import PaymentRepository
from app.services.mandate_service import MandateService
from app.services.monnify_provider import verify_monnify_webhook_signature
from app.services.payment_provider import get_payment_provider
from app.services.payment_service import PaymentService
from app.services.withdrawal_service import WithdrawalService

router = APIRouter(prefix="/payments", tags=["payments"])
settings = get_settings()
logger = logging.getLogger("akoweai")

# HTML pages
_COMPLETION_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Ajoda &mdash; Payment Received</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:wght@400;500;620;700&display=swap" rel="stylesheet">
    <style>
        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Schibsted Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background-color: #F2E7D3;
            background-image: url('/static/ajodazigzag.png');
            background-repeat: repeat;
            background-size: 240px;
            padding: 24px;
            position: relative;
        }}
        body::before {{
            content: '';
            position: absolute;
            inset: 0;
            background: rgba(242, 231, 211, 0.92);
        }}
        .card {{
            position: relative;
            background: #ffffff;
            border: 1px solid #e9ecea;
            border-radius: 14px;
            padding: 40px 32px;
            max-width: 420px;
            width: 100%;
            box-shadow: 0 4px 24px rgba(20, 40, 30, 0.08);
            text-align: center;
        }}
        /*
         * Cropped lockup (496x162). The original ajodalogotextbanner.png is
         * 1536x1024 with ~85% transparent padding, which opened a crater
         * between the mark and the heading and shipped 2MB to do it.
         */
        .logo-banner {{
            width: 132px;
            height: auto;
            margin: 0 auto 24px;
            display: block;
        }}
        h1 {{
            font-size: 22px;
            font-weight: 620;
            color: #171a19;
            margin-bottom: 10px;
        }}
        .subtitle {{
            font-size: 15px;
            color: #565e5a;
            line-height: 1.6;
            margin-bottom: 28px;
        }}
        .ref-box {{
            background: #f6f8f7;
            border: 1px solid #e9ecea;
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 28px;
            text-align: left;
        }}
        .ref-label {{
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: #6a726d;
            margin-bottom: 4px;
        }}
        .ref-value {{
            font-size: 12px;
            font-weight: 500;
            color: #565e5a;
            font-family: 'Courier New', monospace;
            word-break: break-all;
        }}
        .action-btn {{
            display: block;
            width: 100%;
            background: #245537;
            color: #ffffff;
            text-decoration: none;
            padding: 14px 24px;
            border-radius: 10px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            border: none;
            transition: background 0.15s ease;
        }}
        .action-btn:hover {{ background: #1A352B; }}
        .action-btn:focus-visible {{ outline: 2px solid #245537; outline-offset: 2px; }}
        .close-msg {{
            display: none;
            margin-top: 16px;
            font-size: 14px;
            color: #6b7280;
        }}
        .footer {{
            margin-top: 26px;
            padding-top: 20px;
            border-top: 1px solid #e9ecea;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 8px;
        }}
        .footer-label {{
            font-size: 10.5px;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #9ca3af;
        }}
        /* The lockup is 4.47:1 — size it by width only, never by height. */
        .monnify-mark {{
            width: 104px;
            height: auto;
            display: block;
            opacity: 0.9;
        }}
    </style>
</head>
<body>
    <div class="card">
        <img class="logo-banner" src="/static/ajodalogolockup.png" alt="Ajoda" width="496" height="162">
        <h1>Payment Received</h1>
        <p class="subtitle">
            Your receipt is being prepared.<br>
            Check WhatsApp for confirmation.
        </p>
        <div class="ref-box">
            <div class="ref-label">Transaction Reference</div>
            <div class="ref-value">{txnref}</div>
        </div>
        <a id="action-btn" class="action-btn" href="#">Loading&hellip;</a>
        <p id="close-msg" class="close-msg">You may now close this tab.</p>
        <div class="footer">
            <span class="footer-label">Payments secured by</span>
            <img class="monnify-mark" src="/static/monnifylogogrey.svg" alt="Monnify" width="831" height="186">
        </div>
    </div>
    <script>
        (function () {{
            var isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(
                navigator.userAgent
            );
            var btn = document.getElementById('action-btn');
            var closeMsg = document.getElementById('close-msg');

            if (isMobile) {{
                btn.href = '{wa_link}';
                btn.textContent = '\u2190 Back to WhatsApp';
            }} else {{
                // Browsers block window.close() on tabs they didn't open via
                // script, so a "Close this tab" button here would almost always
                // silently fail. Skip straight to the plain-text fallback.
                btn.style.display = 'none';
                closeMsg.style.display = 'block';
            }}
        }})();
    </script>
</body>
</html>"""

# Shared card chrome for terminal payment-bridge dead ends (expired link,
# provider init failure) — same visual language as the completion page above,
# just without the txn-ref box or the mobile/desktop close-button branching
# (there's nothing async left to wait on, so "Back to WhatsApp" is always the
# right action).
_STATUS_PAGE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Ajoda</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:wght@400;500;620;700&display=swap" rel="stylesheet">
    <style>
        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Schibsted Grotesk', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background-color: #F2E7D3;
            background-image: url('/static/ajodazigzag.png');
            background-repeat: repeat;
            background-size: 240px;
            padding: 24px;
            position: relative;
        }}
        body::before {{
            content: '';
            position: absolute;
            inset: 0;
            background: rgba(242, 231, 211, 0.92);
        }}
        .card {{
            position: relative;
            background: #ffffff;
            border: 1px solid #e9ecea;
            border-radius: 14px;
            padding: 40px 32px;
            max-width: 420px;
            width: 100%;
            box-shadow: 0 4px 24px rgba(20, 40, 30, 0.08);
            text-align: center;
        }}
        .logo-banner {{
            width: 132px;
            height: auto;
            margin: 0 auto 20px;
            display: block;
        }}
        .icon-badge {{
            width: 48px;
            height: 48px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 20px;
            background: {icon_bg};
            color: {icon_fg};
        }}
        h1 {{
            font-size: 20px;
            font-weight: 620;
            color: #171a19;
            margin-bottom: 10px;
        }}
        .subtitle {{
            font-size: 15px;
            color: #565e5a;
            line-height: 1.6;
            margin-bottom: 28px;
        }}
        .action-btn {{
            display: block;
            width: 100%;
            background: #245537;
            color: #ffffff;
            text-decoration: none;
            padding: 14px 24px;
            border-radius: 10px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            border: none;
            transition: background 0.15s ease;
        }}
        .action-btn:hover {{ background: #1A352B; }}
        .action-btn:focus-visible {{ outline: 2px solid #245537; outline-offset: 2px; }}
        .footer {{
            margin-top: 26px;
            padding-top: 20px;
            border-top: 1px solid #e9ecea;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 8px;
        }}
        .footer-label {{
            font-size: 10.5px;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #9ca3af;
        }}
        .monnify-mark {{
            width: 104px;
            height: auto;
            display: block;
            opacity: 0.9;
        }}
    </style>
</head>
<body>
    <div class="card">
        <img class="logo-banner" src="/static/ajodalogolockup.png" alt="Ajoda" width="496" height="162">
        <div class="icon-badge">{icon_svg}</div>
        <h1>{heading}</h1>
        <p class="subtitle">{subtitle}</p>
        <a class="action-btn" href="{wa_link}">&larr; Back to WhatsApp</a>
        <div class="footer">
            <span class="footer-label">Payments secured by</span>
            <img class="monnify-mark" src="/static/monnifylogogrey.svg" alt="Monnify" width="831" height="186">
        </div>
    </div>
</body>
</html>"""

_STATUS_ICONS = {
    # (background tint, icon color, glyph) — tints are the semantic warning/
    # destructive colors at ~10% alpha, matching the dashboard's own
    # warning/destructive tokens (frontend/app/globals.css).
    "warning": (
        "#93601a1a",
        "#93601a",
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M10.29 3.86 1.82 18a1 1 0 0 0 .86 1.5h18.64a1 1 0 0 0 .86-1.5L13.71 '
        '3.86a1.5 1.5 0 0 0-2.62 0Z"/><path d="M12 9v4M12 17h.01"/></svg>',
    ),
    "error": (
        "#b0271c1a",
        "#b0271c",
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" '
        'stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M18 6 6 18M6 6l12 12"/></svg>',
    ),
}


def _status_page_html(*, heading: str, subtitle: str, icon: str, wa_link: str) -> str:
    icon_bg, icon_fg, icon_svg = _STATUS_ICONS[icon]
    return _STATUS_PAGE_TEMPLATE.format(
        heading=heading,
        subtitle=subtitle,
        icon_bg=icon_bg,
        icon_fg=icon_fg,
        icon_svg=icon_svg,
        wa_link=wa_link,
    )


# Background task — runs after response is sent, owns its own DB session
async def _verify_and_process_payment(txnref: str) -> None:
    """
    Verify a transaction with Monnify (source of truth) and settle it idempotently.
    Runs as a BackgroundTask — creates its own DB session. Value is never delivered
    on a browser callback; the provider is always requeried first, and settlement
    is gated on an atomic pending->paid transition so duplicate webhook/poll
    deliveries cannot double-credit.
    """
    async with AsyncSessionFactory() as db:
        try:
            payment_repo = PaymentRepository(db)
            payment_svc = PaymentService(db)

            # Cheap early-out for an already-settled duplicate. The authoritative
            # idempotency guard is settle_if_pending() below.
            if await payment_repo.is_already_paid(txnref):
                return

            transaction = await payment_repo.get_by_reference(txnref)
            if not transaction:
                logger.error("Payment callback received for unknown reference: %s", txnref)
                return

            # Mandatory server-side verify with Monnify for authoritative status
            try:
                result = await payment_svc.poll_transaction_status(txnref)
            except Exception:
                logger.exception("Monnify verify failed for ref=%s", txnref)
                return

            status = result.get("status", "")
            returned_kobo = int(result.get("amount_kobo", 0))

            if status == "PAID":
                # Amount must match what was on the original payment request
                if returned_kobo != int(transaction.amount):
                    logger.error(
                        "Amount mismatch for %s: expected %d kobo, Monnify returned %d",
                        txnref, transaction.amount, returned_kobo,
                    )
                    if await payment_repo.fail_if_pending(txnref):
                        await db.commit()
                        await _send_payment_failure_message(transaction)
                    return

                # Atomic settle — only the caller that flips pending->paid runs the
                # money side-effects; a duplicate delivery is a no-op.
                if await payment_repo.settle_if_pending(txnref):
                    await payment_svc.process_successful_payment(
                        transaction, result.get("transaction_reference", "")
                    )
                    await db.commit()
                    await _send_payment_receipt(transaction)
                return

            if status in ("PENDING", "AWAITING_PAYMENT", ""):
                # Not resolved yet — leave pending; a later webhook/poll settles it.
                return

            # FAILED / EXPIRED / REVERSED / PARTIALLY_PAID / OVERPAID -> not settled
            if await payment_repo.fail_if_pending(txnref):
                await db.commit()
                await _send_payment_failure_message(transaction)

        except Exception:
            await db.rollback()
            logger.exception("Unhandled error in payment background task for ref=%s", txnref)


async def _send_payment_receipt(transaction) -> None:
    """Send WhatsApp receipt template to the member after successful payment."""
    from app.services.whatsapp_service import dispatch_payment_receipt
    async with AsyncSessionFactory() as db:
        member_repo = MemberRepository(db)
        member = await member_repo.get_by_id(transaction.member_id)
        if not member:
            return

        from app.repositories.period_repository import PeriodRepository

        coop = await CooperativeRepository(db).get_by_id(transaction.cooperative_id)
        coop_name = coop.name if coop else "your cooperative"

        if len(transaction.period_ids) > 1:
            period_label = "Multiple Periods"
        elif len(transaction.period_ids) == 1:
            period = await PeriodRepository(db).get_by_id(transaction.period_ids[0])
            period_label = (
                period.start_date.strftime("%B %Y") if period else "Current Period"
            )
        else:
            period_label = "Current Period"

        await dispatch_payment_receipt(
            phone=member.phone_number,
            transaction=transaction,
            coop_name=coop_name,
            member_name=member.full_name,
            period_label=period_label,
        )


async def _send_payment_failure_message(transaction) -> None:
    """Notify the member that their payment could not be verified."""
    from app.services.whatsapp_service import send_text_message
    async with AsyncSessionFactory() as db:
        member_repo = MemberRepository(db)
        member = await member_repo.get_by_id(transaction.member_id)
        if member:
            await send_text_message(
                member.phone_number,
                f"⚠️ We could not confirm your payment (ref: {transaction.reference}).\n\n"
                "Please try again or contact your cooperative admin if the issue persists.",
            )


async def _resolve_disbursement(
    reference: str, monnify_status: str, monnify_reference: str, description: str
) -> None:
    """
    Resolve a disbursement's terminal status from the webhook. Runs as a
    BackgroundTask with its own session; idempotent via the atomic state transition.
    """
    async with AsyncSessionFactory() as db:
        try:
            await WithdrawalService(db).resolve_transfer_status(
                reference, monnify_status, monnify_reference, description
            )
        except Exception:
            await db.rollback()
            logger.exception("Disbursement resolution failed for ref=%s", reference)


async def _resolve_mandate_status_update(
    mandate_code: str, mandate_reference: str, status: str
) -> None:
    """Resolve a MANDATE_UPDATE webhook delivery. Runs as a BackgroundTask with
    its own session; best-effort — a failure here just means the mandate's
    local status lags until the next scheduled debit attempt surfaces it."""
    async with AsyncSessionFactory() as db:
        try:
            await MandateService(db).resolve_status_update(
                mandate_code, mandate_reference, status
            )
        except Exception:
            await db.rollback()
            logger.exception(
                "Mandate status webhook resolution failed (code=%s ref=%s)",
                mandate_code, mandate_reference,
            )


# Routes
@router.get("/initiate/{reference}", include_in_schema=False)
async def payment_initiate(
    reference: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Bridge endpoint: opens in the WhatsApp in-app browser and 302-redirects to the
    Monnify hosted checkout. Kept on our own (Meta-whitelisted) domain rather than
    linking to Monnify directly. Unauthenticated — the reference is an opaque token.
    A fresh checkoutUrl is minted on each tap, so Monnify's 40-minute link expiry
    is a non-issue.
    """
    payment_repo = PaymentRepository(db)
    transaction = await payment_repo.get_by_reference(reference)
    if not transaction or transaction.status not in ("pending",):
        return HTMLResponse(
            content=_status_page_html(
                heading="This link is no longer valid",
                subtitle="This can happen if the payment already went through, "
                "or a newer link replaced this one. If you already paid, check "
                "WhatsApp for your receipt — otherwise head back and ask for a "
                "fresh link.",
                icon="warning",
                wa_link=f"https://wa.me/{settings.whatsapp_contact_number}",
            ),
            status_code=410,
        )

    member = await MemberRepository(db).get_by_id(transaction.member_id)
    coop = await CooperativeRepository(db).get_by_id(transaction.cooperative_id)

    member_name = member.full_name if member else "Member"
    coop_name = coop.name if coop else "Cooperative"

    # Members have no email on file; synthesize a deterministic, non-PII address so
    # Monnify has a required value. Digits-only phone keeps the local part valid.
    phone_digits = "".join(
        ch for ch in (member.phone_number if member else "") if ch.isdigit()
    )
    customer_email = f"{phone_digits or 'member'}@ajoda.app"

    try:
        init = await get_payment_provider().initialize_transaction(
            reference=reference,
            amount_kobo=transaction.amount,
            customer_name=f"{member_name} - {coop_name}",
            customer_email=customer_email,
            redirect_url=f"{settings.prod_url}/api/payments/redirect/{reference}",
        )
    except AppException:
        logger.exception("Monnify initialize failed for ref=%s", reference)
        return HTMLResponse(
            content=_status_page_html(
                heading="We couldn't start your payment",
                subtitle="Something went wrong on our end and no money has "
                "moved. Please return to WhatsApp and try again in a moment.",
                icon="error",
                wa_link=f"https://wa.me/{settings.whatsapp_contact_number}",
            ),
            status_code=502,
        )

    return RedirectResponse(url=init["checkout_url"], status_code=302)


@router.get("/redirect/{ref}", include_in_schema=False)
async def payment_redirect(
    ref: str,
    background_tasks: BackgroundTasks,
) -> HTMLResponse:
    """
    Browser return from Monnify checkout (a GET with result query params). We never
    settle on these params \u2014 we schedule a server-side verify keyed on our own `ref`,
    which we embedded in the redirectUrl at initialization. Always returns the HTML
    completion page.
    """
    txnref = ref.strip()
    if txnref:
        background_tasks.add_task(_verify_and_process_payment, txnref)

    return HTMLResponse(
        content=_COMPLETION_HTML_TEMPLATE.format(
            txnref=txnref or "\u2014",
            wa_link=f"https://wa.me/{settings.whatsapp_contact_number}",
        )
    )


@router.post("/webhook")
async def payment_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """
    Monnify collection webhook. Verifies the `monnify-signature` header
    (HMAC-SHA512 of the raw body, keyed with the Secret Key — there is no separate
    webhook-signing secret). Settlement runs through a server-side verify + atomic
    transition, so a duplicate delivery is a no-op. Always returns bare 200.

    [!] The signature scheme is confirmed by recomputing the hash against a captured
    sandbox webhook (see verify_monnify_webhook_signature) before it is trusted.
    """
    raw_body = await request.body()
    signature = request.headers.get("monnify-signature", "")

    if not verify_monnify_webhook_signature(raw_body, signature):
        logger.warning("Monnify webhook signature verification failed")
        return Response(status_code=200)

    try:
        payload = json.loads(raw_body)
    except Exception:
        return Response(status_code=200)

    event_type = payload.get("eventType", "")
    if event_type == "SUCCESSFUL_TRANSACTION":
        event_data = payload.get("eventData", {})
        txnref = str(event_data.get("paymentReference", "")).strip()
        if txnref:
            background_tasks.add_task(_verify_and_process_payment, txnref)

    return Response(status_code=200)


@router.post("/disbursement/webhook")
async def disbursement_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """
    Monnify disbursement (transfer-status) webhook — source of truth for terminal
    status. Same `monnify-signature` (HMAC-SHA512) scheme as collections. Resolution
    is idempotent (atomic state transition + reused reference), so retries are safe.
    Always returns bare 200.
    """
    raw_body = await request.body()
    signature = request.headers.get("monnify-signature", "")

    if not verify_monnify_webhook_signature(raw_body, signature):
        logger.warning("Monnify disbursement webhook signature verification failed")
        return Response(status_code=200)

    try:
        payload = json.loads(raw_body)
    except Exception:
        return Response(status_code=200)

    event_type = payload.get("eventType", "")
    if event_type in (
        "SUCCESSFUL_DISBURSEMENT",
        "FAILED_DISBURSEMENT",
        "REVERSED_DISBURSEMENT",
    ):
        event_data = payload.get("eventData", {})
        reference = str(event_data.get("reference", "")).strip()  # our AJODA-DISB ref
        status = str(event_data.get("status", "")).strip()
        monnify_reference = str(event_data.get("transactionReference", "")).strip()
        description = str(event_data.get("transactionDescription", "")).strip()
        if reference:
            background_tasks.add_task(
                _resolve_disbursement, reference, status, monnify_reference, description
            )

    return Response(status_code=200)


@router.post("/direct-debit/webhook")
async def direct_debit_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """
    Monnify mandate-status webhook (MANDATE_UPDATE) — fires when a mandate's
    status changes on the bank/NIBSS side outside our own cancel() calls (e.g.
    the customer revokes it directly with their bank, or the bank suspends it).
    Same `monnify-signature` (HMAC-SHA512) scheme as the other webhooks.

    [!] Monnify's docs describe this event ("Monnify sends a MANDATE_UPDATE
    webhook whenever the mandate's status changes") but the example eventData
    payload is rendered client-side on their docs site and wasn't recoverable —
    the exact field names are unconfirmed. This reads every plausible key
    defensively and logs the raw payload when nothing matches, so it can be
    corrected against a real captured sandbox delivery.
    """
    raw_body = await request.body()
    signature = request.headers.get("monnify-signature", "")

    if not verify_monnify_webhook_signature(raw_body, signature):
        logger.warning("Monnify mandate webhook signature verification failed")
        return Response(status_code=200)

    try:
        payload = json.loads(raw_body)
    except Exception:
        return Response(status_code=200)

    event_type = payload.get("eventType", "")
    if event_type == "MANDATE_UPDATE":
        event_data = payload.get("eventData", {})
        mandate_code = str(event_data.get("mandateCode", "")).strip()
        mandate_reference = str(event_data.get("mandateReference", "")).strip()
        status = str(
            event_data.get("status") or event_data.get("mandateStatus", "")
        ).strip().upper()

        if not (mandate_code or mandate_reference):
            logger.warning("Mandate webhook missing both identifiers: %s", payload)
        elif not status:
            logger.warning("Mandate webhook missing a status field: %s", payload)
        else:
            background_tasks.add_task(
                _resolve_mandate_status_update, mandate_code, mandate_reference, status
            )

    return Response(status_code=200)


@router.post("/retry")
async def retry_payment(
    request: Request,
    current_member: Member = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """
    Retry a failed payment with a fresh transaction reference.
    Invalidates the old reference and returns a new payment URL.
    """
    body = await request.json()
    old_reference = body.get("old_reference", "").strip()
    if not old_reference:
        raise BadRequestException("old_reference is required")

    payment_repo = PaymentRepository(db)
    old_tx = await payment_repo.get_by_reference(old_reference)

    if not old_tx:
        raise NotFoundException("Transaction not found")
    if old_tx.status != "failed":
        raise BadRequestException("Transaction is not in a failed state")
    if old_tx.member_id != current_member.id:
        raise BadRequestException("Transaction does not belong to you")

    await payment_repo.mark_invalidated(old_reference)

    # Rebuild period data (all periods already exist at this point)
    period_data = [{"id": pid} for pid in old_tx.period_ids]
    payment_svc = PaymentService(db)
    new_tx = await payment_svc.create_pending_transaction(
        member_id=old_tx.member_id,
        coop_id=old_tx.cooperative_id,
        period_data=period_data,
        amount_kobo=old_tx.amount,
    )

    payment_url = payment_svc.build_payment_initiation_url(new_tx.reference)
    return ApiResponse.success(
        data={"payment_url": payment_url, "new_reference": new_tx.reference},
        message="Retry payment link generated",
    )