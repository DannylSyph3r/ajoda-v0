from enum import Enum


class Role(str, Enum):
    MEMBER = "member"
    EXCO = "exco"


class ContributionStatus(str, Enum):
    UNPAID = "unpaid"
    PAID = "paid"
    REFUNDED = "refunded"  # full refund only — a partial refund leaves status PAID


class TransactionStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    INVALIDATED = "invalidated"


class WithdrawalStatus(str, Enum):
    """Disbursement (money-out) state machine on the withdrawal record."""
    INITIATED = "INITIATED"
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MandateStatus(str, Enum):
    """
    Direct-debit mandate lifecycle, stored as Monnify's own raw status string.
    Monnify's docs and its own worked examples disagree on the activated spelling
    (guide prose says ACTIVATED, the Cancel Mandate response example shows ACTIVE)
    — both are accepted and treated identically until sandbox testing confirms
    which one Monnify actually emits.
    """
    INITIATED = "INITIATED"
    PENDING = "PENDING"
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    ACTIVATED = "ACTIVATED"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SUSPENDED = "SUSPENDED"


# A mandate in one of these states is already "dead" — nothing further happens to
# it on its own, and cascading a cancel onto it would be a no-op.
MANDATE_TERMINAL_STATUSES = frozenset({
    MandateStatus.AUTHORIZATION_EXPIRED.value,
    MandateStatus.EXPIRED.value,
    MandateStatus.CANCELLED.value,
})

# The two spellings Monnify's own docs use interchangeably for "usable, will debit".
MANDATE_ACTIVE_STATUSES = frozenset({
    MandateStatus.ACTIVE.value,
    MandateStatus.ACTIVATED.value,
})

# Statuses that need the member to act again (re-authorize) rather than just wait.
MANDATE_NEEDS_ATTENTION_STATUSES = frozenset({
    MandateStatus.AUTHORIZATION_EXPIRED.value,
    MandateStatus.EXPIRED.value,
    MandateStatus.SUSPENDED.value,
})


def bucket_mandate_status(raw_status: str | None) -> str | None:
    """
    Collapse a mandate's raw Monnify status into the 3 buckets the dashboard
    Members table actually needs: 'active', 'pending', 'needs_attention'. None
    means "no mandate" — a cancelled mandate is treated the same as never having
    had one, since it's not actionable info for exco going forward.
    """
    if not raw_status or raw_status == MandateStatus.CANCELLED.value:
        return None
    if raw_status in MANDATE_ACTIVE_STATUSES:
        return "active"
    if raw_status in MANDATE_NEEDS_ATTENTION_STATUSES:
        return "needs_attention"
    return "pending"


class DebitStatus(str, Enum):
    """Terminal vocabulary for a single Debit Mandate call (Get Debit Status)."""
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"


class RefundStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RefundType(str, Enum):
    PARTIAL_REFUND = "PARTIAL_REFUND"
    FULL_REFUND = "FULL_REFUND"


class ReminderStage(str, Enum):
    SEVEN_DAY = "7_day"
    THREE_DAY = "3_day"
    ONE_DAY = "1_day"
    DUE_DATE = "due_date"
    ONE_WEEK_OVERDUE = "1_week_overdue"
    TWO_WEEKS_OVERDUE = "2_weeks_overdue"


class ReminderStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    CANCELLED = "cancelled"


class Frequency(str, Enum):
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    TRIWEEKLY = "triweekly"
    MONTHLY = "monthly"
    BIMONTHLY = "bimonthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class ConversationFlow(str, Enum):
    REGISTER = "REGISTER"
    PAY_SELECTION = "PAY_SELECTION"
    BROADCAST = "BROADCAST"
    MEMBER_LOOKUP = "MEMBER_LOOKUP"
    DISBURSE = "DISBURSE"  # exco-only money-out flow (Phase 5). Value MUST equal Intent.DISBURSE.
    # Member auto-pay setup. Value MUST equal Intent.AUTOPAY_ENABLE — route_message's
    # blocking-flow redirect does Intent(session.current_flow) directly.
    AUTOPAY_ENABLE = "AUTOPAY_ENABLE"


class StepUpAction(str, Enum):
    SETTINGS = "SETTINGS"
    BROADCAST = "BROADCAST"
    WITHDRAWAL = "WITHDRAWAL"
    REFUND = "REFUND"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Intent(str, Enum):
    PAY = "PAY"
    BALANCE = "BALANCE"
    REGISTER = "REGISTER"
    HISTORY = "HISTORY"
    COOP_STATUS = "COOP_STATUS"
    SEND_REMINDERS = "SEND_REMINDERS"
    COOP_SUMMARY = "COOP_SUMMARY"
    BROADCAST = "BROADCAST"
    MEMBER_LOOKUP = "MEMBER_LOOKUP"
    VIEW_MEMBERS = "VIEW_MEMBERS"
    MEMBERS_NEXT = "MEMBERS_NEXT"
    MEMBERS_PREV = "MEMBERS_PREV"
    VIEW_UNPAID = "VIEW_UNPAID"
    ADD_PERIOD = "ADD_PERIOD"
    CONFIRM_PAY = "CONFIRM_PAY"
    CONFIRM_BROADCAST = "CONFIRM_BROADCAST"
    SHOW_MORE = "SHOW_MORE"
    SWITCH_COOP = "SWITCH_COOP"
    CANCEL = "CANCEL"
    GREETING = "GREETING"
    SHOW_SWITCHER = "SHOW_SWITCHER"
    SHOW_MENU = "SHOW_MENU"
    DISBURSE = "DISBURSE"
    CONFIRM_DISBURSE = "CONFIRM_DISBURSE"
    DISBURSE_RESEND_OTP = "DISBURSE_RESEND_OTP"
    DISBURSEMENT_HISTORY = "DISBURSEMENT_HISTORY"
    EXPIRED_SELECTION = "EXPIRED_SELECTION"
    AUTOPAY_ENABLE = "AUTOPAY_ENABLE"  # entry point — button row or free text alike
    AUTOPAY_CANCEL = "AUTOPAY_CANCEL"  # "cancel it" button, shown when a mandate exists
    AUTOPAY_CONFIRM_CANCEL = "AUTOPAY_CONFIRM_CANCEL"  # final yes on the cancel confirm
    UNKNOWN = "UNKNOWN"