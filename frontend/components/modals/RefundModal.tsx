"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Info } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Status, type StatusKind } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { refundContribution, getRefundStatus } from "@/lib/api/cooperatives";
import type { RefundItem } from "@/lib/api/types";
import type { ApiError } from "@/lib/api/client";
import { formatNaira } from "@/lib/utils";

type Step = "form" | "confirm" | "status";

interface RefundModalProps {
  open: boolean;
  onClose: () => void;
  coopId: string;
  stepUpToken?: string;
  contributionId: string;
  memberName: string;
  maxAmountKobo: number;
  onSuccess: () => void;
}

const TERMINAL = ["COMPLETED", "FAILED"];

function errText(err: unknown, fallback: string): string {
  return (err as ApiError).response?.data?.message ?? fallback;
}

export function RefundModal({
  open,
  onClose,
  coopId,
  stepUpToken,
  contributionId,
  memberName,
  maxAmountKobo,
  onSuccess,
}: RefundModalProps) {
  const [step, setStep] = useState<Step>("form");
  const [amountNaira, setAmountNaira] = useState("");
  const [reason, setReason] = useState("");
  const [refund, setRefund] = useState<RefundItem | null>(null);
  const [loading, setLoading] = useState(false);

  // Pre-fill the amount to the full contribution whenever a new row opens.
  useEffect(() => {
    if (open) setAmountNaira((maxAmountKobo / 100).toString());
  }, [open, maxAmountKobo]);

  const reset = () => {
    setStep("form");
    setAmountNaira("");
    setReason("");
    setRefund(null);
    setLoading(false);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  // Poll for terminal status while PENDING (no webhook wired for refunds yet —
  // reconciliation-on-read is the only path to a resolved status here).
  useEffect(() => {
    if (step !== "status" || !refund) return;
    if (TERMINAL.includes(refund.status)) {
      onSuccess();
      return;
    }
    const timer = setInterval(async () => {
      try {
        const next = await getRefundStatus(coopId, refund.refund_id);
        setRefund(next);
      } catch {
        /* keep polling; transient */
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [step, refund, coopId, onSuccess]);

  const amountKobo = Math.round((parseFloat(amountNaira) || 0) * 100);
  const canContinue =
    amountKobo > 0 && amountKobo <= maxAmountKobo && reason.trim().length >= 3;

  const handleContinue = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canContinue) return;
    setStep("confirm");
  };

  const handleRefund = async () => {
    if (!stepUpToken) return;
    setLoading(true);
    try {
      const r = await refundContribution(
        coopId,
        contributionId,
        { amount_kobo: amountKobo, reason: reason.trim() },
        stepUpToken,
      );
      setRefund(r);
      setStep("status");
    } catch (err) {
      toast.error(errText(err, "Could not initiate the refund."));
      setStep("form");
    } finally {
      setLoading(false);
    }
  };

  const isPartial = amountKobo < maxAmountKobo;
  const title =
    step === "confirm"
      ? "Confirm refund"
      : step === "status"
        ? "Refund status"
        : "Refund contribution";

  return (
    <Modal open={open} onClose={handleClose} title={title}>
      {step === "form" && (
        <form onSubmit={handleContinue} className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Refunding <span className="font-medium text-foreground">{memberName}</span>
            &rsquo;s contribution. This comes out of the pool.
          </p>
          <Input
            label="Amount (₦)"
            type="number"
            min="1"
            max={maxAmountKobo / 100}
            step="1"
            className="tabular text-lg font-medium placeholder:[font-variant-numeric:normal]"
            value={amountNaira}
            onChange={(e) => setAmountNaira(e.target.value)}
            required
          />
          <p className="text-xs text-muted-foreground">
            Up to {formatNaira(maxAmountKobo)}. A partial refund leaves the
            contribution marked Paid; a full refund marks it Refunded.
          </p>
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-foreground">Reason</label>
            <textarea
              className="w-full rounded-sm border border-border-strong bg-card px-3 py-2 text-sm
                         text-foreground placeholder:text-muted-foreground resize-none
                         transition-colors focus:border-primary"
              rows={2}
              maxLength={500}
              placeholder="Why is this being refunded?"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
            />
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

      {step === "confirm" && (
        <div className="space-y-5">
          <div className="space-y-1 text-center">
            <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-tertiary">
              {isPartial ? "Refunding" : "Fully refunding"}
            </p>
            <p className="tabular text-[28px] font-[560] tracking-[-0.03em] text-primary">
              {formatNaira(amountKobo)}
            </p>
          </div>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">Member </span>
            {memberName}
          </p>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">Reason </span>
            {reason}
          </p>
          <div className="flex items-start gap-2 rounded-sm border border-border bg-muted px-3.5 py-3 text-xs text-muted-foreground">
            <Info className="h-4 w-4 shrink-0 mt-0.5" />
            {isPartial
              ? "This is a partial refund — the contribution stays marked Paid."
              : "This is a full refund — the contribution will be marked Refunded."}
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
            <Button type="button" onClick={handleRefund} loading={loading}>
              Confirm &amp; refund
            </Button>
          </div>
        </div>
      )}

      {step === "status" && refund && (
        <div className="space-y-5 text-sm">
          <div className="space-y-1 pb-1 text-center">
            {TERMINAL.includes(refund.status) ? (
              <span
                className={`mx-auto grid h-12 w-12 place-items-center rounded-full ${
                  refund.status === "COMPLETED"
                    ? "bg-primary-tint text-primary-ink"
                    : "bg-destructive/10 text-destructive"
                }`}
              >
                {refund.status === "COMPLETED" ? (
                  <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
                ) : (
                  <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
                )}
              </span>
            ) : (
              <Status kind={REFUND_STATUS_META[refund.status]?.kind ?? "neutral"}>
                {REFUND_STATUS_META[refund.status]?.label ?? refund.status}
              </Status>
            )}
            <p className="pt-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-tertiary">
              {refund.status === "COMPLETED"
                ? "Refund completed"
                : refund.status === "FAILED"
                  ? "Refund failed"
                  : "Refund processing"}
            </p>
            <p className="tabular text-[28px] font-[560] tracking-[-0.03em] text-primary">
              {formatNaira(refund.amount)}
            </p>
          </div>
          {!TERMINAL.includes(refund.status) && (
            <p className="text-center text-xs text-muted-foreground">
              Processing… this updates automatically.
            </p>
          )}
          <div className="flex justify-end">
            <Button
              type="button"
              variant={refund.status === "COMPLETED" ? "primary" : "ghost"}
              onClick={handleClose}
            >
              {refund.status === "COMPLETED" ? "Done" : "Close"}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

const REFUND_STATUS_META: Record<string, { kind: StatusKind; label: string }> = {
  PENDING: { kind: "warning", label: "Processing" },
  COMPLETED: { kind: "success", label: "Completed" },
  FAILED: { kind: "danger", label: "Failed" },
};
