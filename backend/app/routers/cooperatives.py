import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    get_coop_membership,
    get_current_member,
    require_coop_exco,
    require_step_up,
)
from app.core.enums import RiskLevel, StepUpAction, bucket_mandate_status
from app.core.exceptions import NotFoundException
from app.core.responses import ApiResponse
from app.models.member import Member
from app.repositories.contribution_refund_repository import ContributionRefundRepository
from app.repositories.cooperative_repository import CooperativeRepository
from app.prompts.financial_summary import COOP_STATUS_INSIGHT_PROMPT
from app.repositories.period_repository import PeriodRepository
from app.schemas.cooperative import (
    ActiveJoinCodeItem,
    ActiveJoinCodesResponse,
    CooperativeDetailResponse,
    CooperativeListItem,
    CreateCooperativeRequest,
    CreateCooperativeResponse,
    ExcoInviteRequest,
    ExcoInviteResponse,
    GenerateJoinCodesRequest,
    InsightResponse,
    JoinCodeItem,
    JoinCodesResponse,
    AuthorizeDisbursementRequest,
    BankItem,
    DirectDebitMandateResponse,
    DisbursementResponse,
    InitiateDisbursementRequest,
    InitiateRefundRequest,
    MemberListItem,
    PaginatedWithdrawals,
    PayablePeriodItem,
    PayablePeriodsResponse,
    RefundResponse,
    SetupDirectDebitRequest,
    UpdateSettingsRequest,
    VerifyRecipientRequest,
    VerifyRecipientResponse,
    WalletBalanceResponse,
    WithdrawalListItem,
    BroadcastRequest,
    BroadcastResponse,
    ContributionSummaryItem,
    PeriodListItem,
    PeriodStatusItem,
)
from app.services.cooperative_service import CooperativeService
from app.services.gemini_service import GeminiProClient
from app.services.join_code_service import JoinCodeService
from app.services.mandate_service import MandateService
from app.services.payment_service import PaymentService
from app.services.period_service import PeriodService
from app.services.withdrawal_service import WithdrawalService, _mask_account

logger = logging.getLogger("akoweai")

router = APIRouter(prefix="/cooperatives", tags=["cooperatives"])


@router.post("", status_code=201)
async def create_cooperative(
    body: CreateCooperativeRequest,
    current_member: Member = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    result = await CooperativeService(db).create_cooperative(
        member_id=current_member.id,
        name=body.name,
        contribution_amount_kobo=body.contribution_amount_kobo,
        frequency=body.frequency,
        anchor_date=body.anchor_date,
        due_day_offset=body.due_day_offset,
    )
    return ApiResponse.success(
        data=CreateCooperativeResponse(**result),
        message="Cooperative created",
        status_code=201,
    )


@router.get("")
async def list_cooperatives(
    current_member: Member = Depends(get_current_member),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    items = await CooperativeService(db).get_member_cooperatives(current_member.id)
    return ApiResponse.success(
        data=[CooperativeListItem(**item) for item in items],
        message="OK",
    )


@router.get("/{coop_id}")
async def get_cooperative(
    coop_id: UUID,
    _membership=Depends(get_coop_membership),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    result = await CooperativeService(db).get_cooperative(coop_id)
    return ApiResponse.success(data=CooperativeDetailResponse(**result), message="OK")


@router.patch("/{coop_id}/settings")
async def update_settings(
    coop_id: UUID,
    body: UpdateSettingsRequest,
    _exco=Depends(require_coop_exco),
    _step_up=Depends(require_step_up(StepUpAction.SETTINGS)),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    result = await CooperativeService(db).update_settings(
        coop_id=coop_id,
        contribution_amount_kobo=body.contribution_amount_kobo,
        frequency=body.frequency,
        due_day_offset=body.due_day_offset,
    )
    return ApiResponse.success(
        data=CooperativeDetailResponse(**result), message="Settings updated"
    )


@router.get("/{coop_id}/members")
async def get_members(
    coop_id: UUID,
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    rows = await CooperativeRepository(db).get_members_with_stats(coop_id)

    members = []
    for row in rows:
        late_count: int = row["late_count"]
        risk_level = (
            RiskLevel.HIGH if late_count >= 2
            else RiskLevel.MEDIUM if late_count == 1
            else RiskLevel.LOW
        )
        members.append(
            MemberListItem(
                member_id=row["member_id"],
                full_name=row["full_name"],
                role=row["role"],
                joined_at=row["joined_at"],
                risk_level=risk_level,
                total_contributed=row["total_contributed"],
                periods_paid=row["periods_paid"],
                last_paid_at=row["last_paid_at"],
                autopay_status=bucket_mandate_status(row.get("mandate_status")),
            )
        )

    return ApiResponse.success(data=members, message="OK")


@router.post("/{coop_id}/join-codes", status_code=201)
async def generate_join_codes(
    coop_id: UUID,
    body: GenerateJoinCodesRequest,
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    codes = await JoinCodeService(db).generate_bulk(
        coop_id, body.count, body.expires_in_days
    )
    return ApiResponse.success(
        data=JoinCodesResponse(
            codes=[JoinCodeItem(code=jc.code, expires_at=jc.expires_at) for jc in codes]
        ),
        message="Join codes generated",
        status_code=201,
    )


@router.post("/{coop_id}/exco-invites", status_code=201)
async def generate_exco_invite(
    coop_id: UUID,
    body: ExcoInviteRequest,
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    invite = await JoinCodeService(db).generate_exco_invite(
        coop_id, body.expires_in_days
    )
    return ApiResponse.success(
        data=ExcoInviteResponse(code=invite.code, expires_at=invite.expires_at),
        message="Exco invite generated",
        status_code=201,
    )
    

@router.get("/{coop_id}/join-codes")
async def list_join_codes(
    coop_id: UUID,
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    codes = await JoinCodeService(db).list_active(coop_id)
    return ApiResponse.success(
        data=ActiveJoinCodesResponse(
            codes=[
                ActiveJoinCodeItem(
                    code=jc.code,
                    role=jc.role,
                    expires_at=jc.expires_at,
                    created_at=jc.created_at,
                )
                for jc in codes
            ]
        ),
        message="OK",
    )


@router.delete("/{coop_id}/join-codes/{code}", status_code=204)
async def revoke_join_code(
    coop_id: UUID,
    code: str,
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> None:
    await JoinCodeService(db).revoke(coop_id, code)


@router.get("/{coop_id}/periods/payable")
async def get_payable_periods(
    coop_id: UUID,
    current_member: Member = Depends(get_current_member),
    _membership=Depends(get_coop_membership),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    periods = await PeriodService(db).get_payable_periods(coop_id, current_member.id)
    return ApiResponse.success(
        data=PayablePeriodsResponse(
            periods=[PayablePeriodItem(**p) for p in periods]
        ),
        message="OK",
    )


def _disbursement_response(w) -> DisbursementResponse:
    return DisbursementResponse(
        withdrawal_id=w.id,
        status=w.status,
        transfer_reference=w.transfer_reference,
        amount=w.amount,
        reason=w.reason,
        destination_account_masked=_mask_account(w.destination_account_number),
        destination_bank_code=w.destination_bank_code,
        destination_account_name=w.destination_account_name,
        failure_reason=w.failure_reason,
        pool_balance_after=w.pool_balance_after,
        created_at=w.created_at,
    )


@router.get("/{coop_id}/disbursements/banks")
async def list_disbursement_banks(
    coop_id: UUID,
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    banks = await WithdrawalService(db).get_banks()
    return ApiResponse.success(
        data=[BankItem(**b) for b in banks], message="OK"
    )


@router.get("/{coop_id}/disbursements/wallet-balance")
async def get_disbursement_wallet_balance(
    coop_id: UUID,
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """The Monnify disbursement wallet's available balance (the money-out source,
    distinct from the cooperative pool). Exco-only."""
    wallet = await WithdrawalService(db).get_wallet_balance()
    return ApiResponse.success(
        data=WalletBalanceResponse(available_kobo=wallet["available_kobo"]),
        message="OK",
    )


@router.post("/{coop_id}/disbursements/verify-recipient")
async def verify_disbursement_recipient(
    coop_id: UUID,
    body: VerifyRecipientRequest,
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    result = await WithdrawalService(db).verify_recipient(
        body.account_number, body.bank_code
    )
    return ApiResponse.success(
        data=VerifyRecipientResponse(
            account_name=result["account_name"],
            account_masked=_mask_account(body.account_number),
            bank_code=body.bank_code,
        ),
        message="Recipient verified",
    )


@router.post("/{coop_id}/disbursements", status_code=201)
async def initiate_disbursement(
    coop_id: UUID,
    body: InitiateDisbursementRequest,
    current_member: Member = Depends(get_current_member),
    _exco=Depends(require_coop_exco),
    _step_up=Depends(require_step_up(StepUpAction.WITHDRAWAL)),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    withdrawal = await WithdrawalService(db).initiate_disbursement(
        coop_id=coop_id,
        amount_kobo=body.amount_kobo,
        reason=body.reason,
        account_number=body.account_number,
        bank_code=body.bank_code,
        account_name=body.account_name,
        authorized_by_member_id=current_member.id,
    )
    return ApiResponse.success(
        data=_disbursement_response(withdrawal),
        message="Disbursement initiated",
        status_code=201,
    )


@router.post("/{coop_id}/disbursements/{withdrawal_id}/authorize")
async def authorize_disbursement(
    coop_id: UUID,
    withdrawal_id: UUID,
    body: AuthorizeDisbursementRequest,
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    service = WithdrawalService(db)
    withdrawal = await service.get_disbursement_for_coop(coop_id, withdrawal_id)
    withdrawal = await service.authorize_disbursement(withdrawal, body.otp)
    return ApiResponse.success(
        data=_disbursement_response(withdrawal), message="OTP submitted"
    )


@router.get("/{coop_id}/disbursements/{withdrawal_id}")
async def get_disbursement(
    coop_id: UUID,
    withdrawal_id: UUID,
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    withdrawal = await WithdrawalService(db).get_disbursement_status(
        coop_id, withdrawal_id
    )
    return ApiResponse.success(
        data=_disbursement_response(withdrawal), message="OK"
    )


@router.get("/{coop_id}/withdrawals")
async def list_withdrawals(
    coop_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _membership=Depends(get_coop_membership),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    result = await WithdrawalService(db).get_withdrawals(coop_id, page, page_size)
    return ApiResponse.success(
        data=PaginatedWithdrawals(
            items=[WithdrawalListItem(**item) for item in result["items"]],
            total=result["total"],
            page=result["page"],
            has_more=result["has_more"],
        ),
        message="OK",
    )


def _mandate_response(m) -> DirectDebitMandateResponse:
    return DirectDebitMandateResponse(
        mandate_id=m.id,
        status=m.status,
        authorization_link=m.authorization_link,
        mandate_amount_kobo=m.mandate_amount_kobo,
        created_at=m.created_at,
    )


@router.post("/{coop_id}/direct-debit/setup", status_code=201)
async def setup_direct_debit(
    coop_id: UUID,
    body: SetupDirectDebitRequest,
    current_member: Member = Depends(get_current_member),
    _membership=Depends(get_coop_membership),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """Member-initiated — any member of the cooperative, not exco-only. An exco
    can never set up auto-pay on another member's behalf; final consent happens
    on the member's own bank authorization link regardless, but initiation is
    scoped to the member's own session."""
    mandate = await MandateService(db).setup(
        member=current_member,
        coop_id=coop_id,
        account_number=body.account_number,
        bank_code=body.bank_code,
    )
    return ApiResponse.success(
        data=_mandate_response(mandate), message="Mandate created", status_code=201
    )


@router.get("/{coop_id}/direct-debit/status")
async def get_direct_debit_status(
    coop_id: UUID,
    current_member: Member = Depends(get_current_member),
    _membership=Depends(get_coop_membership),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    mandate = await MandateService(db).get_active_mandate(current_member.id, coop_id)
    return ApiResponse.success(
        data=_mandate_response(mandate) if mandate else None, message="OK"
    )


@router.post("/{coop_id}/direct-debit/cancel")
async def cancel_direct_debit(
    coop_id: UUID,
    current_member: Member = Depends(get_current_member),
    _membership=Depends(get_coop_membership),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    service = MandateService(db)
    mandate = await service.get_active_mandate(current_member.id, coop_id)
    if not mandate:
        raise NotFoundException(
            "No active auto-pay mandate found for this cooperative."
        )
    await service.cancel(mandate, "Cancelled by member")
    return ApiResponse.success(data=None, message="Auto-pay cancelled")


def _refund_response(r) -> RefundResponse:
    return RefundResponse(
        refund_id=r.id,
        contribution_id=r.contribution_id,
        status=r.status,
        refund_type=r.refund_type,
        amount=r.amount,
        created_at=r.created_at,
    )


@router.post("/{coop_id}/contributions/{contribution_id}/refund", status_code=201)
async def refund_contribution(
    coop_id: UUID,
    contribution_id: UUID,
    body: InitiateRefundRequest,
    current_member: Member = Depends(get_current_member),
    _exco=Depends(require_coop_exco),
    _step_up=Depends(require_step_up(StepUpAction.REFUND)),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    """Exco-only, step-up gated — same risk class as a withdrawal: real money
    leaves the pool to a bank account. Never self-serve by the paying member."""
    refund = await PaymentService(db).refund_contribution(
        coop_id=coop_id,
        contribution_id=contribution_id,
        amount_kobo=body.amount_kobo,
        reason=body.reason,
        requested_by_member_id=current_member.id,
    )
    return ApiResponse.success(
        data=_refund_response(refund), message="Refund initiated", status_code=201
    )


@router.get("/{coop_id}/contributions/refunds/{refund_id}")
async def get_refund_status(
    coop_id: UUID,
    refund_id: UUID,
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    refund = await PaymentService(db).get_refund_status(coop_id, refund_id)
    return ApiResponse.success(data=_refund_response(refund), message="OK")


@router.get("/{coop_id}/insights")
async def get_insights(
    coop_id: UUID,
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    rows = await CooperativeRepository(db).get_members_with_stats(coop_id)

    at_risk = [
        row for row in rows if row["late_count"] >= 1
    ]

    if not at_risk:
        return ApiResponse.success(
            data=InsightResponse(insight="All members are up to date with contributions."),
            message="OK",
        )

    coop_result = await CooperativeRepository(db).get_by_id(coop_id)
    coop_name = coop_result.name if coop_result else "this cooperative"
    member_count = len(rows)
    high_risk_names = [
        row["full_name"] for row in at_risk if row["late_count"] >= 2
    ][:5]
    medium_risk_names = [
        row["full_name"] for row in at_risk if row["late_count"] == 1
    ][:5]

    context = (
        f"Cooperative: {coop_name}\n"
        f"Total members: {member_count}\n"
        f"Members at risk: {len(at_risk)}\n"
        f"High risk (2+ late payments): {len(high_risk_names)} — "
        f"{', '.join(high_risk_names) if high_risk_names else 'none'}\n"
        f"Medium risk (1 late payment): {len(medium_risk_names)} — "
        f"{', '.join(medium_risk_names) if medium_risk_names else 'none'}"
    )

    try:
        insight = await GeminiProClient().generate_summary(
            context, COOP_STATUS_INSIGHT_PROMPT
        )
    except Exception as exc:
        logger.warning("Gemini insight generation failed: %s", exc)
        insight = (
            f"{len(at_risk)} member(s) have late or missed contributions "
            f"and may need follow-up."
        )

    return ApiResponse.success(
        data=InsightResponse(insight=insight),
        message="OK",
    )


@router.get("/{coop_id}/periods")
async def list_periods(
    coop_id: UUID,
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    items = await PeriodService(db).get_all_periods(coop_id)
    return ApiResponse.success(
        data=[PeriodListItem(**item) for item in items],
        message="OK",
    )


@router.get("/{coop_id}/contributions/summary")
async def get_contributions_summary(
    coop_id: UUID,
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    rows = await CooperativeRepository(db).get_contributions_summary(coop_id)
    items = [
        ContributionSummaryItem(
            member_id=row["member_id"],
            full_name=row["full_name"],
            total_contributed=row["total_contributed"],
            periods_paid=row["periods_paid"],
            periods_missed=row["periods_missed"],
            last_payment_date=row["last_payment_date"],
            risk_level=(
                RiskLevel.HIGH if row["late_count"] >= 2
                else RiskLevel.MEDIUM if row["late_count"] == 1
                else RiskLevel.LOW
            ),
        )
        for row in rows
    ]
    return ApiResponse.success(data=items, message="OK")


@router.get("/{coop_id}/contributions/period-status")
async def get_period_status(
    coop_id: UUID,
    period_id: UUID = Query(...),
    _exco=Depends(require_coop_exco),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    rows = await CooperativeRepository(db).get_period_contributions_status(
        coop_id, period_id
    )
    return ApiResponse.success(
        data=[PeriodStatusItem(**row) for row in rows],
        message="OK",
    )


@router.post("/{coop_id}/broadcast")
async def broadcast_message(
    coop_id: UUID,
    body: BroadcastRequest,
    current_member: Member = Depends(get_current_member),
    _exco=Depends(require_coop_exco),
    _step_up=Depends(require_step_up(StepUpAction.BROADCAST)),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    sent_count = await CooperativeService(db).broadcast_to_members(
        coop_id, body.message, exclude_phone=current_member.phone_number
    )
    return ApiResponse.success(
        data=BroadcastResponse(sent_to=sent_count),
        message="Broadcast sent",
    )