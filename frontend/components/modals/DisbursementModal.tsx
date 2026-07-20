"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Modal } from "@/components/ui/Modal";
import { Status, type StatusKind } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
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
  stepUpToken: string;
  onSuccess: () => void;
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
}: DisbursementModalProps) {
  const [step, setStep] = useState<Step>("form");
  const [amountNaira, setAmountNaira] = useState("");
  const [reason, setReason] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [bankCode, setBankCode] = useState("");
  const [verified, setVerified] = useState<VerifyRecipientResponse | null>(null);
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
    setDisbursement(null);
    setOtp("");
    setLoading(false);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

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

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    const amount = parseFloat(amountNaira);
    if (!amount || amount <= 0 || reason.trim().length < 3) return;
    if (!/^\d{10}$/.test(accountNumber) || !bankCode) {
      toast.error("Enter a 10-digit account number and select a bank.");
      return;
    }
    setLoading(true);
    try {
      const v = await verifyRecipient(coopId, accountNumber, bankCode);
      setVerified(v);
      setStep("confirm");
    } catch (err) {
      toast.error(errText(err, "Could not verify that account."));
    } finally {
      setLoading(false);
    }
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
        stepUpToken,
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

  const title =
    step === "confirm"
      ? "Confirm recipient"
      : step === "otp"
        ? "Enter OTP"
        : step === "status"
          ? "Transfer status"
          : "New disbursement";

  return (
    <Modal open={open} onClose={handleClose} title={title}>
      {step === "form" && (
        <form onSubmit={handleVerify} className="space-y-4">
          <Input
            label="Amount (₦)"
            type="number"
            min="1"
            step="1"
            placeholder="e.g. 50000"
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
          <Input
            label="Destination account number"
            inputMode="numeric"
            maxLength={10}
            placeholder="10-digit NUBAN"
            value={accountNumber}
            onChange={(e) =>
              setAccountNumber(e.target.value.replace(/\D/g, "").slice(0, 10))
            }
            required
          />
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-foreground">Bank</label>
            <select
              className="w-full rounded-sm border border-border-strong bg-card px-3 py-2 text-sm
                         text-foreground transition-colors focus:border-primary"
              value={bankCode}
              onChange={(e) => setBankCode(e.target.value)}
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
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="ghost" type="button" onClick={handleClose}>
              Cancel
            </Button>
            <Button type="submit" loading={loading}>
              Verify recipient
            </Button>
          </div>
        </form>
      )}

      {step === "confirm" && verified && (
        <div className="space-y-4">
          <div className="flex items-center gap-3 rounded-sm border border-border-strong bg-muted p-3.5">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary-tint text-primary-ink">
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-foreground">
                {verified.account_name}
              </p>
              <p className="text-[12.5px] text-muted-foreground">
                {bankName} · {verified.account_masked} — verified by Monnify
              </p>
            </div>
          </div>
          <dl className="space-y-2 text-sm">
            <Row
              label="Amount"
              value={formatNaira(Math.round(parseFloat(amountNaira) * 100))}
            />
            <Row label="Reason" value={reason} />
          </dl>
          <p className="text-xs text-muted-foreground">
            An OTP will be emailed to the account owner to authorize the transfer.
          </p>
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
        <div className="space-y-4 text-sm">
          <TransferProgress status={disbursement.status} />
          <dl className="space-y-2">
            <Row label="Amount" value={formatNaira(disbursement.amount)} />
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
            <Button type="button" variant="ghost" onClick={handleClose}>
              Close
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
  if (status === "FAILED") {
    return <Status kind="danger">Failed</Status>;
  }
  const currentIx = PROGRESS_STEPS.findIndex((st) => st.key === status);
  return (
    <div className="space-y-2.5">
      <Status kind={meta.kind}>{meta.label}</Status>
      <ol className="space-y-0.5">
        {PROGRESS_STEPS.map((st, ix) => {
          const done = currentIx > ix || status === "COMPLETED";
          const now = st.key === status && status !== "COMPLETED";
          return (
            <li key={st.key} className="flex items-center gap-2.5 py-1">
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
              <span
                className={`text-[13px] ${
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
