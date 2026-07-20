"use client";

import { useQuery } from "@tanstack/react-query";
import { useCoop } from "@/context/CoopContext";
import { getWithdrawals, getWalletBalance } from "@/lib/api/cooperatives";
import { formatNaira, formatDateTime } from "@/lib/utils";
import { Skeleton } from "@/components/ui/Skeleton";
import { Status, type StatusKind } from "@/components/ui/Badge";
import { RecordWithdrawalButton } from "@/components/dashboard/RecordWithdrawalButton";
import type { WithdrawalItem } from "@/lib/api/types";

const STATUS_MAP: Record<string, { kind: StatusKind; label: string }> = {
  COMPLETED: { kind: "success", label: "Completed" },
  FAILED: { kind: "danger", label: "Failed" },
  PROCESSING: { kind: "warning", label: "Processing" },
  PENDING_AUTHORIZATION: { kind: "info", label: "Awaiting OTP" },
  INITIATED: { kind: "neutral", label: "Initiated" },
};

function WithdrawalStatus({ status }: { status: string }) {
  const s = STATUS_MAP[status] ?? { kind: "neutral" as StatusKind, label: status };
  return <Status kind={s.kind}>{s.label}</Status>;
}

function truncateRef(ref: string) {
  return ref.length > 22 ? `${ref.slice(0, 14)}…${ref.slice(-6)}` : ref;
}

function WithdrawalCard({ withdrawal }: { withdrawal: WithdrawalItem }) {
  return (
    <article className="space-y-3 rounded-md border border-border bg-card p-4 shadow-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="tabular text-[15px] font-[560] tracking-[-0.015em] text-foreground">
            {formatNaira(withdrawal.amount)}
          </h2>
          <p className="text-[13px] text-muted-foreground">
            {formatDateTime(withdrawal.created_at)}
          </p>
        </div>
        <WithdrawalStatus status={withdrawal.status} />
      </div>
      <dl className="space-y-3 text-sm">
        <div className="space-y-1">
          <dt className="text-[11px] font-semibold uppercase tracking-[0.06em] text-tertiary">
            Reason
          </dt>
          <dd className="text-foreground">{withdrawal.reason}</dd>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <dt className="text-[11px] font-semibold uppercase tracking-[0.06em] text-tertiary">
              Authorized by
            </dt>
            <dd className="text-foreground">{withdrawal.authorized_by_name}</dd>
          </div>
          <div className="space-y-1">
            <dt className="text-[11px] font-semibold uppercase tracking-[0.06em] text-tertiary">
              Pool after
            </dt>
            <dd className="tabular font-medium text-foreground">
              {withdrawal.pool_balance_after != null
                ? formatNaira(withdrawal.pool_balance_after)
                : "—"}
            </dd>
          </div>
        </div>
        {withdrawal.transfer_reference && (
          <div className="space-y-1">
            <dt className="text-[11px] font-semibold uppercase tracking-[0.06em] text-tertiary">
              Reference
            </dt>
            <dd className="break-all font-mono text-xs text-muted-foreground">
              {withdrawal.transfer_reference}
            </dd>
          </div>
        )}
      </dl>
    </article>
  );
}

export default function WithdrawalsPage() {
  const { activeCoop } = useCoop();
  const coopId = activeCoop?.id ?? "";

  const { data, isLoading } = useQuery({
    queryKey: ["coop", coopId, "withdrawals"],
    queryFn: () => getWithdrawals(coopId),
    enabled: !!coopId,
  });

  const { data: wallet, isLoading: walletLoading } = useQuery({
    queryKey: ["coop", coopId, "wallet-balance"],
    queryFn: () => getWalletBalance(coopId),
    enabled: !!coopId,
    staleTime: 30_000,
  });

  const items = data?.items ?? [];

  return (
    <div className="space-y-5 sm:space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-[23px] font-[620] tracking-[-0.015em] text-balance text-foreground">
            Withdrawals
          </h1>
          <p className="text-[13.5px] text-muted-foreground">
            Move pooled funds out to a verified bank account.
          </p>
        </div>
        {activeCoop && (
          <RecordWithdrawalButton coopId={coopId} className="w-full sm:w-auto" />
        )}
      </div>

      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 rounded-md border border-border bg-card p-4 shadow-card sm:p-5">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-tertiary">
            Disbursement wallet
          </p>
          {walletLoading ? (
            <Skeleton className="mt-1 h-7 w-32" />
          ) : (
            <p className="tabular text-2xl font-[560] tracking-[-0.02em] text-foreground">
              {wallet ? formatNaira(wallet.available_kobo) : "—"}
            </p>
          )}
        </div>
        <p className="max-w-[34ch] text-[12.5px] text-muted-foreground">
          The Monnify money-out source, separate from the cooperative pool. A
          transfer needs funds in both.
        </p>
      </div>

      <div className="overflow-hidden rounded-md border border-border bg-card shadow-card">
        <div className="space-y-3 p-4 md:hidden">
          {isLoading
            ? Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="space-y-3 rounded-md border border-border bg-card p-4"
                >
                  <Skeleton className="h-5 w-28" />
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="h-16 w-full" />
                </div>
              ))
            : items.map((withdrawal) => (
                <WithdrawalCard key={withdrawal.id} withdrawal={withdrawal} />
              ))}
          {!isLoading && items.length === 0 && (
            <div className="rounded-md border border-dashed border-border-strong px-4 py-10 text-center">
              <p className="text-sm font-medium text-foreground">
                No withdrawals yet
              </p>
              <p className="mt-1 text-[13px] text-muted-foreground">
                When you disburse from the pool, every transfer and its Monnify
                reference will be recorded here.
              </p>
            </div>
          )}
        </div>

        <div className="hidden overflow-x-auto md:block">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted">
                {["Date", "Amount", "Reason", "Authorized by", "Status", "Reference"].map(
                  (h) => (
                    <th
                      key={h}
                      className="px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-[0.05em] text-tertiary"
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {isLoading
                ? Array.from({ length: 5 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 6 }).map((_, j) => (
                        <td key={j} className="px-4 py-3">
                          <Skeleton className="h-4 w-24" />
                        </td>
                      ))}
                    </tr>
                  ))
                : items.map((w) => (
                    <tr key={w.id} className="transition-colors hover:bg-muted">
                      <td className="tabular whitespace-nowrap px-4 py-3 text-muted-foreground">
                        {formatDateTime(w.created_at)}
                      </td>
                      <td className="tabular px-4 py-3 font-[560] tracking-[-0.015em] text-foreground">
                        {formatNaira(w.amount)}
                      </td>
                      <td
                        className="max-w-xs truncate px-4 py-3 text-foreground"
                        title={w.reason}
                      >
                        {w.reason}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {w.authorized_by_name}
                      </td>
                      <td className="px-4 py-3">
                        <WithdrawalStatus status={w.status} />
                      </td>
                      <td className="px-4 py-3">
                        {w.transfer_reference ? (
                          <span
                            className="font-mono text-xs text-muted-foreground"
                            title={w.transfer_reference}
                          >
                            {truncateRef(w.transfer_reference)}
                          </span>
                        ) : (
                          <span className="text-tertiary">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
              {!isLoading && items.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center">
                    <p className="text-sm font-medium text-foreground">
                      No withdrawals yet
                    </p>
                    <p className="mt-1 text-[13px] text-muted-foreground">
                      When you disburse from the pool, every transfer and its
                      Monnify reference will be recorded here.
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
