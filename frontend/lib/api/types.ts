// Auth

export interface AuthTokens {
  member_id: string;
  full_name: string;
  phone_number: string;
  access_token: string;
  refresh_token: string;
}

export interface StoredUser {
  id: string;
  full_name: string;
  phone_number: string;
}

export interface StepUpResponse {
  step_up_token: string;
  expires_in: number;
}

export type StepUpAction = "WITHDRAWAL" | "BROADCAST" | "SETTINGS";

// Cooperatives

export interface CooperativeSchedule {
  version: number;
  frequency: string;
  anchor_date: string;
  due_day_offset: number;
}

export interface CooperativeListItem {
  id: string;
  name: string;
  role: "member" | "exco";
  contribution_amount_kobo: number;
  pool_balance: number;
}

export interface CooperativeDetail {
  id: string;
  name: string;
  contribution_amount_kobo: number;
  pool_balance: number;
  member_count: number;
  collection_rate_pct: number;
  ytd_collected_kobo: number;
  current_schedule: CooperativeSchedule;
}

export interface CreateCoopRequest {
  name: string;
  contribution_amount_kobo: number;
  frequency: string;
  anchor_date: string;
  due_day_offset: number;
}

export interface CreateCoopResponse {
  cooperative_id: string;
  join_code: string;
  exco_invite_code: string | null;
}

export interface UpdateSettingsRequest {
  contribution_amount_kobo?: number;
  frequency?: string;
  due_day_offset?: number;
}

// Members

export type RiskLevel = "LOW" | "MEDIUM" | "HIGH";

export interface MemberListItem {
  member_id: string;
  full_name: string;
  role: string;
  joined_at: string;
  risk_level: RiskLevel;
  total_contributed: number;
  periods_paid: number;
  last_paid_at: string | null;
}

export interface JoinCodeItem {
  code: string;
  expires_at: string;
}

export interface GenerateJoinCodesResponse {
  codes: JoinCodeItem[];
}

export interface ExcoInviteResponse {
  code: string;
  expires_at: string;
}

export interface ActiveJoinCodeItem {
  code: string;
  role: string;
  expires_at: string;
  created_at: string;
}

export interface ActiveJoinCodesResponse {
  codes: ActiveJoinCodeItem[];
}

// Contributions

export interface ContributionSummaryItem {
  member_id: string;
  full_name: string;
  total_contributed: number;
  periods_paid: number;
  periods_missed: number;
  last_payment_date: string | null;
  risk_level: RiskLevel;
}

export interface PeriodStatusItem {
  member_id: string;
  full_name: string;
  amount: number;
  status: "paid" | "unpaid";
}

// Periods

export interface PeriodListItem {
  id: string;
  period_number: number;
  label: string;
  start_date: string;
  due_date: string;
  is_open: boolean;
}

// Withdrawals & disbursements

export type DisbursementStatus =
  | "INITIATED"
  | "PENDING_AUTHORIZATION"
  | "PROCESSING"
  | "COMPLETED"
  | "FAILED";

export interface WithdrawalItem {
  id: string;
  amount: number;
  reason: string;
  authorized_by_name: string;
  pool_balance_after: number | null;
  status: DisbursementStatus;
  transfer_reference: string | null;
  created_at: string;
}

export interface PaginatedWithdrawals {
  items: WithdrawalItem[];
  total: number;
  page: number;
  has_more: boolean;
}

export interface WalletBalanceResponse {
  available_kobo: number;
}

export interface BankItem {
  code: string;
  name: string;
}

export interface VerifyRecipientResponse {
  account_name: string;
  account_masked: string;
  bank_code: string;
}

export interface InitiateDisbursementRequest {
  amount_kobo: number;
  reason: string;
  account_number: string;
  bank_code: string;
  account_name: string;
}

export interface DisbursementResponse {
  withdrawal_id: string;
  status: DisbursementStatus;
  transfer_reference: string | null;
  amount: number;
  reason: string;
  destination_account_masked: string | null;
  destination_bank_code: string | null;
  destination_account_name: string | null;
  failure_reason: string | null;
  pool_balance_after: number | null;
  created_at: string;
}

// Misc

export interface InsightResponse {
  insight: string;
}

export interface BroadcastResponse {
  sent_to: number;
}

export interface ChatResponse {
  answer: string;
}
