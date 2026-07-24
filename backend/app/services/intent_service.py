import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ConversationFlow, Intent
from app.models.conversation_session import ConversationSession
from app.models.member import Member
from app.prompts.intent_classification import INTENT_CLASSIFICATION_PROMPT
from app.services.gemini_service import GeminiFlashClient
from app.services.whatsapp_service import send_reply_buttons, send_text_message

logger = logging.getLogger("akoweai")

BUTTON_INTENT_MAP: dict[str, Intent] = {
    "pay_now": Intent.PAY,
    "my_balance": Intent.BALANCE,
    "get_started": Intent.REGISTER,
    "full_history": Intent.HISTORY,
    "show_more_history": Intent.SHOW_MORE,
    "coop_status": Intent.COOP_STATUS,
    "send_reminders": Intent.SEND_REMINDERS,
    "ai_summary": Intent.COOP_SUMMARY,
    "broadcast": Intent.BROADCAST,
    "member_lookup": Intent.MEMBER_LOOKUP,
    "view_members": Intent.VIEW_MEMBERS,
    "members_next": Intent.MEMBERS_NEXT,
    "members_prev": Intent.MEMBERS_PREV,
    "show_menu": Intent.SHOW_MENU,
    "view_unpaid": Intent.VIEW_UNPAID,
    "add_period": Intent.ADD_PERIOD,
    "confirm_pay": Intent.CONFIRM_PAY,
    "confirm_broadcast": Intent.CONFIRM_BROADCAST,
    "cancel": Intent.CANCEL,
    "show_switcher": Intent.SHOW_SWITCHER,
    "disburse": Intent.DISBURSE,
    "confirm_disburse": Intent.CONFIRM_DISBURSE,
    "disburse_resend_otp": Intent.DISBURSE_RESEND_OTP,
    "disbursement_history": Intent.DISBURSEMENT_HISTORY,
    "autopay": Intent.AUTOPAY_ENABLE,
    "autopay_enable": Intent.AUTOPAY_ENABLE,
    "autopay_cancel": Intent.AUTOPAY_CANCEL,
    "autopay_confirm_cancel": Intent.AUTOPAY_CONFIRM_CANCEL,
}

_BLOCKING_FLOWS = {
    ConversationFlow.REGISTER.value,
    ConversationFlow.BROADCAST.value,
    ConversationFlow.MEMBER_LOOKUP.value,
    ConversationFlow.DISBURSE.value,
    ConversationFlow.AUTOPAY_ENABLE.value,
}

# Free text that always breaks out of a blocking flow, regardless of which step
# it's on — typing one of these is unambiguously an attempt to leave, not an
# answer to whatever the flow just asked. Exact match only (after trim/lowercase)
# so it can never misfire on real flow input (an OTP, an account number, a name
# that happens to contain one of these words). Deliberately not run through
# Gemini — same reasoning as the blocking-flow redirect itself.
_ESCAPE_KEYWORDS = {"cancel", "stop", "restart", "reset", "menu", "hi", "hello", "hey"}

_gemini_flash: GeminiFlashClient | None = None


def _get_flash_client() -> GeminiFlashClient:
    """Return the shared GeminiFlashClient, creating it on first call."""
    global _gemini_flash
    if _gemini_flash is None:
        _gemini_flash = GeminiFlashClient()
    return _gemini_flash


def classify_button_intent(button_payload: str) -> Intent:
    return BUTTON_INTENT_MAP.get(button_payload, Intent.UNKNOWN)


async def classify_text_intent(
    text: str, member_role: str
) -> tuple[Intent, dict]:
    """Classify free text intent using Gemini Flash."""
    prompt = f"User role: {member_role}\nUser message: {text}"
    try:
        result = await _get_flash_client().classify_intent(
            prompt, INTENT_CLASSIFICATION_PROMPT
        )
        intent_str = result.get("intent", "UNKNOWN")
        entities = result.get("entities", {})
        try:
            return Intent(intent_str), entities
        except ValueError:
            return Intent.UNKNOWN, {}
    except Exception as exc:
        logger.warning("Intent classification failed: %s", exc)
        return Intent.UNKNOWN, {}


async def route_message(
    session: ConversationSession,
    message_data: dict,
    member: Member | None,
) -> tuple[Intent, dict]:
    """Determine intent from incoming message (button, list, or text)."""
    message_type = message_data.get("message_type")
    member_role = "exco" if member else "member"

    if message_type == "button":
        button_payload = message_data.get("button_payload", "")
        return classify_button_intent(button_payload), {}

    if message_type == "list":
        row_id = message_data.get("list_payload", "")

        if row_id.startswith("switch_coop_"):
            coop_id_str = row_id.removeprefix("switch_coop_")
            return Intent.SWITCH_COOP, {"coop_id": coop_id_str}

        # Flow-aware list routing — period selection
        if session.current_flow == ConversationFlow.PAY_SELECTION.value and (
            row_id.startswith("period_") or row_id.startswith("future_")
        ):
            return Intent.PAY, {"row_id": row_id}

        # A period_/future_ row id outside an active PAY_SELECTION flow means the
        # member tapped a stale list message (already completed or expired) —
        # give a specific reply instead of falling through to classify_button_intent,
        # which would return UNKNOWN and send the generic fallback.
        if row_id.startswith("period_") or row_id.startswith("future_"):
            return Intent.EXPIRED_SELECTION, {}

        # Flow-aware list routing — member lookup result selection
        if (
            session.current_flow == ConversationFlow.MEMBER_LOOKUP.value
            and row_id.startswith("lookup_")
        ):
            return Intent.MEMBER_LOOKUP, {"row_id": row_id}

        # Flow-aware list routing — disbursement bank selection
        if (
            session.current_flow == ConversationFlow.DISBURSE.value
            and row_id.startswith("bank_")
        ):
            return Intent.DISBURSE, {"row_id": row_id}

        # Standard menu list items (same IDs as buttons)
        return classify_button_intent(row_id), {}

    if message_type == "text":
        text = message_data.get("text", "")

        # Active blocking flow: redirect text back into the flow without LLM —
        # except a small set of universal escape words, which always break out
        # regardless of what the flow is waiting on (see _ESCAPE_KEYWORDS).
        if session.current_flow in _BLOCKING_FLOWS:
            if text.strip().lower() in _ESCAPE_KEYWORDS:
                return Intent.CANCEL, {}
            try:
                return Intent(session.current_flow), {}
            except ValueError:
                pass

        # Free text with no active blocking flow → Gemini Flash
        return await classify_text_intent(text, member_role)

    return Intent.UNKNOWN, {}


async def send_fallback_menu(
    phone: str,
    role: str,
    db: AsyncSession,
    member_id: UUID,
    coop_id: UUID | None,
) -> None:
    """Send fallback message when intent is UNKNOWN."""
    await send_text_message(
        phone,
        "I didn't quite catch that. Here's what I can help with 👇",
    )
    if role == "exco":
        from app.flows.dispatch import send_exco_main_menu
        await send_exco_main_menu(phone, "", db, member_id, coop_id)
    else:
        await send_reply_buttons(
            phone,
            "What would you like to do?",
            [
                {"id": "pay_now", "title": "💰 Pay"},
                {"id": "my_balance", "title": "📊 My Balance"},
            ],
        )