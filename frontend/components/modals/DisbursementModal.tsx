"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, Info, Loader2 } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Status, type StatusKind } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  authorizeDisbursement,
  getDisbursementBanks,
  getDisbursementStatus,
  initiateDisbursement,
  verifyRecipient,
} from "@/lib/api/cooperatives";
import type {
  DisbursementResponse,
  VerifyRecipientResponse,
} from "@/lib/api/types";
import type { ApiError } from "@/lib/api/client";
import { formatNaira } from "@/lib/utils";

type Step = "form" | "confirm" | "otp" | "status";

interface DisbursementModalProps {
  open: boolean;
  onClose: () => void;
  coopId: string;
  stepUpToken?: string;
  onSuccess: () => void;
  /** When set, skip straight to the otp/status step for this existing
   * withdrawal instead of starting a new disbursement — authorize doesn't
   * require a fresh step-up PIN, only initiate does. */
  resumeWithdrawalId?: string;
}

const TERMINAL = ["COMPLETED", "FAILED"];

function errText(err: unknown, fallback: string): string {
  return (err as ApiError).response?.data?.message ?? fallback;
}

export function DisbursementModal({
  open,
  onClose,
  coopId,
  stepUpToken,
  onSuccess,
  resumeWithdrawalId,
}: DisbursementModalProps) {
  const [step, setStep] = useState<Step>("form");
  const [amountNaira, setAmountNaira] = useState("");
  const [reason, setReason] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [bankCode, setBankCode] = useState("");
  const [verified, setVerified] = useState<VerifyRecipientResponse | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const lastAttemptRef = useRef<string | null>(null);
  const [disbursement, setDisbursement] = useState<DisbursementResponse | null>(
    null,
  );
  const [otp, setOtp] = useState("");
  const [loading, setLoading] = useState(false);

  const { data: banks = [] } = useQuery({
    queryKey: ["coop", coopId, "disbursement-banks"],
    queryFn: () => getDisbursementBanks(coopId),
    enabled: open && !!coopId,
    staleTime: Infinity,
  });

  const bankName = useMemo(
    () => banks.find((b) => b.code === bankCode)?.name ?? bankCode,
    [banks, bankCode],
  );

  const reset = () => {
    setStep("form");
    setAmountNaira("");
    setReason("");
    setAccountNumber("");
    setBankCode("");
    setVerified(null);
    setVerifying(false);
    setVerifyError(null);
    lastAttemptRef.current = null;
    setDisbursement(null);
    setOtp("");
    setLoading(false);
  };

  const handleClose = () => {
    if (step === "otp" && disbursement) {
      toast.message("Transfer still pending", {
        description:
          "This transfer needs its OTP entered to complete. Resume it anytime from Withdrawals.",
      });
    }
    reset();
    onClose();
  };

  // Resume mode: fetch fresh status for an existing withdrawal and jump
  // straight to otp/status instead of starting a new disbursement. Always
  // re-fetches rather than trusting list data, since the row may have
  // resolved since it was last listed.
  useEffect(() => {
    if (!open || !resumeWithdrawalId) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const d = await getDisbursementStatus(coopId, resumeWithdrawalId);
        if (cancelled) return;
        setDisbursement(d);
        setStep(d.status === "PENDING_AUTHORIZATION" ? "otp" : "status");
      } catch (err) {
        if (cancelled) return;
        toast.error(errText(err, "Could not load this transfer."));
        onClose();
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, resumeWithdrawalId, coopId]);

  // Poll for terminal status while PROCESSING (reconciliation-on-read backstop).
  useEffect(() => {
    if (step !== "status" || !disbursement) return;
    if (TERMINAL.includes(disbursement.status)) {
      onSuccess();
      return;
    }
    const timer = setInterval(async () => {
      try {
        const next = await getDisbursementStatus(
          coopId,
          disbursement.withdrawal_id,
        );
        setDisbursement(next);
      } catch {
        /* keep polling; transient */
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [step, disbursement, coopId, onSuccess]);

  // Auto-verify the recipient the instant a 10-digit account number is paired
  // with a selected bank. Fires immediately the first time; if the user
  // edits the number after that (a correction), debounce ~1s so we don't
  // fire a lookup per keystroke.
  useEffect(() => {
    if (accountNumber.length !== 10 || !bankCode) {
      setVerified(null);
      setVerifyError(null);
      lastAttemptRef.current = null;
      return;
    }
    const key = `${bankCode}:${accountNumber}`;
    if (key === lastAttemptRef.current) return;

    const delay = lastAttemptRef.current === null ? 0 : 1000;
    const timer = setTimeout(async () => {
      lastAttemptRef.current = key;
      setVerified(null);
      setVerifyError(null);
      setVerifying(true);
      try {
        const v = await verifyRecipient(coopId, accountNumber, bankCode);
        setVerified(v);
      } catch (err) {
        setVerifyError(
          errText(err, "Could not verify this account — check the number and bank."),
        );
      } finally {
        setVerifying(false);
      }
    }, delay);
    return () => clearTimeout(timer);
  }, [accountNumber, bankCode, coopId]);

  const canContinue =
    !!parseFloat(amountNaira) &&
    parseFloat(amountNaira) > 0 &&
    reason.trim().length >= 3 &&
    !!verified &&
    !verifying;

  const handleContinue = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canContinue) return;
    setStep("confirm");
  };

  const handleInitiate = async () => {
    setLoading(true);
    try {
      const d = await initiateDisbursement(
        coopId,
        {
          amount_kobo: Math.round(parseFloat(amountNaira) * 100),
          reason: reason.trim(),
          account_number: accountNumber,
          bank_code: bankCode,
          account_name: verified!.account_name,
        },
        // Only reachable via the fresh-creation flow (form → confirm), which
        // RecordWithdrawalButton always gates behind a real step-up token;
        // resume mode never reaches this step.
        stepUpToken!,
      );
      setDisbursement(d);
      setStep(d.status === "PENDING_AUTHORIZATION" ? "otp" : "status");
    } catch (err) {
      // Gate failures (pool/wallet) and expired step-up surface here.
      toast.error(errText(err, "Could not initiate the transfer."));
      setStep("form");
    } finally {
      setLoading(false);
    }
  };

  const handleAuthorize = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!disbursement || otp.trim().length < 3) return;
    setLoading(true);
    try {
      const d = await authorizeDisbursement(
        coopId,
        disbursement.withdrawal_id,
        otp.trim(),
      );
      setDisbursement(d);
      setStep("status");
    } catch (err) {
      toast.error(errText(err, "The OTP could not be validated."));
    } finally {
      setLoading(false);
    }
  };

  const resuming = !!resumeWithdrawalId && !disbursement;

  const title = resuming
    ? "Loading transfer…"
    : step === "confirm"
      ? "Confirm recipient"
      : step === "otp"
        ? "Enter OTP"
        : step === "status"
          ? "Transfer status"
          : "New disbursement";

  return (
    <Modal open={open} onClose={handleClose} title={title}>
      {resuming && (
        <div className="space-y-3 py-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      )}
      {!resuming && step === "form" && (
        <form onSubmit={handleContinue} className="space-y-4">
          <Input
            label="Amount (₦)"
            type="number"
            min="1"
            step="1"
            placeholder="e.g. 50000"
            className="tabular text-lg font-medium placeholder:[font-variant-numeric:normal]"
            value={amountNaira}
            onChange={(e) => setAmountNaira(e.target.value)}
            required
          />
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-foreground">Reason</label>
            <textarea
              className="w-full rounded-sm border border-border-strong bg-card px-3 py-2 text-sm
                         text-foreground placeholder:text-muted-foreground resize-none
                         transition-colors focus:border-primary"
              rows={2}
              maxLength={500}
              placeholder="Describe the reason for this withdrawal"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-foreground">Bank</label>
            <select
              className="w-full rounded-sm border border-border-strong bg-card px-3 py-2 text-sm
                         text-foreground transition-colors focus:border-primary"
              value={bankCode}
              onChange={(e) => {
                const next = e.target.value;
                setBankCode(next);
                // Only wipe a typed account number if the bank was cleared
                // back to "unselected" — switching bank-to-bank should
                // re-verify the existing digits, not force a retype.
                if (!next) setAccountNumber("");
              }}
              required
            >
              <option value="">Select a bank…</option>
              {banks.map((b) => (
                <option key={b.code} value={b.code}>
                  {b.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Input
              label="Destination account number"
              inputMode="numeric"
              maxLength={10}
              placeholder={bankCode ? "10-digit NUBAN" : "Select a bank first"}
              disabled={!bankCode}
              value={accountNumber}
              onChange={(e) =>
                setAccountNumber(e.target.value.replace(/\D/g, "").slice(0, 10))
              }
              required
            />
            {accountNumber.length === 10 && bankCode && (
              <div className="mt-1.5 flex items-center gap-1.5 text-[12.5px]">
                {verifying && (
                  <>
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
                    <span className="text-muted-foreground">
                      Verifying account…
                    </span>
                  </>
                )}
                {!verifying && verified && (
                  <>
                    <Check className="h-3.5 w-3.5 shrink-0 text-success" />
                    <span className="text-foreground">
                      {verified.account_name}
                    </span>
                  </>
                )}
                {!verifying && verifyError && (
                  <span className="text-destructive">{verifyError}</span>
                )}
              </div>
            )}
          </div>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="ghost" type="button" onClick={handleClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canContinue}>
              Continue
            </Button>
          </div>
        </form>
      )}

      {step === "confirm" && verified && (
        <div className="space-y-5">
          <div className="space-y-1 text-center">
            <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-tertiary">
              You&apos;re sending
            </p>
            <p className="tabular text-[28px] font-[560] tracking-[-0.03em] text-primary">
              {formatNaira(Math.round(parseFloat(amountNaira) * 100))}
            </p>
          </div>
          <div className="flex items-center gap-3 rounded-sm border border-border-strong bg-muted p-3.5">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary-tint text-primary-ink">
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-foreground">
                {verified.account_name}
              </p>
              <p className="text-[12.5px] text-muted-foreground">
                {bankName} · {verified.account_masked}
              </p>
            </div>
          </div>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">Reason </span>
            {reason}
          </p>
          <div className="flex items-start gap-2 rounded-sm border border-border bg-muted px-3.5 py-3 text-xs text-muted-foreground">
            <Info className="h-4 w-4 shrink-0 mt-0.5" />
            An OTP will be emailed to the account owner to authorize the transfer.
          </div>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              variant="ghost"
              type="button"
              onClick={() => setStep("form")}
              disabled={loading}
            >
              Back
            </Button>
            <Button type="button" onClick={handleInitiate} loading={loading}>
              Confirm &amp; send
            </Button>
          </div>
        </div>
      )}

      {step === "otp" && (
        <form onSubmit={handleAuthorize} className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Enter the OTP emailed to the Monnify account owner to authorize this
            transfer.
          </p>
          <Input
            label="OTP"
            inputMode="numeric"
            placeholder="••••••"
            className="text-center font-mono text-base tracking-[0.3em]"
            value={otp}
            onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
            required
          />
          <div className="flex justify-end">
            <Button type="submit" loading={loading}>
              Authorize transfer
            </Button>
          </div>
        </form>
      )}

      {step === "status" && disbursement && (
        <div className="space-y-5 text-sm">
          {TERMINAL.includes(disbursement.status) ? (
            <div className="space-y-1 pb-1 text-center">
              <span
                className={`mx-auto grid h-12 w-12 place-items-center rounded-full ${
                  disbursement.status === "COMPLETED"
                    ? "bg-primary-tint text-primary-ink"
                    : "bg-destructive/10 text-destructive"
                }`}
              >
                {disbursement.status === "COMPLETED" ? (
                  <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
                ) : (
                  <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
                )}
              </span>
              <p className="pt-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-tertiary">
                {disbursement.status === "COMPLETED"
                  ? "Transfer completed"
                  : "Transfer failed"}
              </p>
              <p className="tabular text-[28px] font-[560] tracking-[-0.03em] text-primary">
                {formatNaira(disbursement.amount)}
              </p>
            </div>
          ) : (
            <TransferProgress status={disbursement.status} />
          )}
          <dl className="space-y-2">
            {!TERMINAL.includes(disbursement.status) && (
              <Row label="Amount" value={formatNaira(disbursement.amount)} />
            )}
            <Row
              label="Recipient"
              value={`${disbursement.destination_account_name ?? "—"} (${
                disbursement.destination_account_masked ?? "—"
              })`}
            />
            {disbursement.transfer_reference && (
              <Row label="Reference" value={disbursement.transfer_reference} mono />
            )}
            {disbursement.status === "FAILED" && disbursement.failure_reason && (
              <Row label="Reason" value={disbursement.failure_reason} />
            )}
          </dl>
          {!TERMINAL.includes(disbursement.status) && (
            <p className="text-xs text-muted-foreground">
              Processing… this updates automatically.
            </p>
          )}
          <div className="flex justify-end">
            <Button
              type="button"
              variant={disbursement.status === "COMPLETED" ? "primary" : "ghost"}
              onClick={handleClose}
            >
              {disbursement.status === "COMPLETED" ? "Done" : "Close"}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={mono ? "font-mono text-xs text-foreground text-right break-all" : "text-foreground text-right"}>
        {value}
      </dd>
    </div>
  );
}

const STATUS_META: Record<string, { kind: StatusKind; label: string }> = {
  COMPLETED: { kind: "success", label: "Completed" },
  FAILED: { kind: "danger", label: "Failed" },
  PROCESSING: { kind: "warning", label: "Processing" },
  PENDING_AUTHORIZATION: { kind: "info", label: "Awaiting OTP" },
  INITIATED: { kind: "neutral", label: "Initiated" },
};

const PROGRESS_STEPS = [
  { key: "INITIATED", label: "Transfer initiated" },
  { key: "PENDING_AUTHORIZATION", label: "Awaiting OTP" },
  { key: "PROCESSING", label: "Processing" },
  { key: "COMPLETED", label: "Completed" },
];

function TransferProgress({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? {
    kind: "neutral" as StatusKind,
    label: status,
  };
  const currentIx = PROGRESS_STEPS.findIndex((st) => st.key === status);
  return (
    <div className="space-y-3">
      <Status kind={meta.kind}>{meta.label}</Status>
      <ol>
        {PROGRESS_STEPS.map((st, ix) => {
          const done = currentIx > ix;
          const now = st.key === status;
          const isLast = ix === PROGRESS_STEPS.length - 1;
          return (
            <li key={st.key} className="flex gap-2.5">
              <div className="flex flex-col items-center">
                <span
                  className={`grid h-5 w-5 shrink-0 place-items-center rounded-full border text-[11px] font-semibold ${
                    done
                      ? "border-primary bg-primary text-white"
                      : now
                        ? "border-primary bg-card text-primary"
                        : "border-border-strong bg-card text-tertiary"
                  }`}
                >
                  {done ? (
                    <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
                  ) : (
                    ix + 1
                  )}
                </span>
                {!isLast && (
                  <span
                    className={`my-0.5 w-px flex-1 ${done ? "bg-primary" : "bg-border-strong"}`}
                  />
                )}
              </div>
              <span
                className={`pb-4 text-[13px] ${
                  now
                    ? "font-semibold text-foreground"
                    : done
                      ? "text-muted-foreground"
                      : "text-tertiary"
                }`}
              >
                {st.label}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
