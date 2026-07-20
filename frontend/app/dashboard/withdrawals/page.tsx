"use client";

import { useQuery } from "@tanstack/react-query";
import { useCoop } from "@/context/CoopContext";
import { getWithdrawals } from "@/lib/api/cooperatives";
import { formatNaira, formatDateTime } from "@/lib/utils";
import { Skeleton } from "@/components/ui/Skeleton";
import { RecordWithdrawalButton } from "@/components/dashboard/RecordWithdrawalButton";
import type { WithdrawalItem } from "@/lib/api/types";

const STATUS_STYLES: Record<string, string> = {
  COMPLETED: "bg-green-100 text-green-800",
  FAILED: "bg-red-100 text-red-800",
  PROCESSING: "bg-blue-100 text-blue-800",
  PENDING_AUTHORIZATION: "bg-amber-100 text-amber-800",
  INITIATED: "bg-gray-100 text-gray-800",
};

function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${
        STATUS_STYLES[status] ?? "bg-gray-100 text-gray-800"
      }`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function WithdrawalCard({ withdrawal }: { withdrawal: WithdrawalItem }) {
  return (
    <article className="space-y-3 rounded-xl border border-border bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">
            {formatNaira(withdrawal.amount)}
          </h2>
          <p className="text-sm text-muted-foreground">
            {formatDateTime(withdrawal.created_at)}
          </p>
        </div>
        <StatusPill status={withdrawal.status} />
      </div>
      <dl className="space-y-3 text-sm">
        <div className="space-y-1">
          <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Reason
          </dt>
          <dd className="text-foreground">{withdrawal.reason}</dd>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Authorized By
            </dt>
            <dd className="text-foreground">{withdrawal.authorized_by_name}</dd>
          </div>
          <div className="space-y-1">
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Pool After
            </dt>
            <dd className="font-medium text-foreground">
              {withdrawal.pool_balance_after != null
                ? formatNaira(withdrawal.pool_balance_after)
                : "—"}
            </dd>
          </div>
        </div>
        {withdrawal.transfer_reference && (
          <div className="space-y-1">
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Reference
            </dt>
            <dd className="break-all font-mono text-xs text-foreground">
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

  const items = data?.items ?? [];

  return (
    <div className="space-y-5 sm:space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <h1 className="text-xl font-semibold text-foreground">Withdrawals</h1>
        {activeCoop && (
          <RecordWithdrawalButton
            coopId={coopId}
            className="w-full sm:w-auto"
          />
        )}
      </div>

      <div className="bg-white rounded-xl border border-border overflow-hidden">
        <div className="space-y-3 p-4 md:hidden">
          {isLoading
            ? Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="space-y-3 rounded-xl border border-border bg-white p-4"
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
            <div className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
              No withdrawals recorded.
            </div>
          )}
        </div>

        <div className="hidden overflow-x-auto md:block">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/50">
                {[
                  "Date",
                  "Amount (₦)",
                  "Reason",
                  "Authorized By",
                  "Status",
                  "Pool After",
                ].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider"
                  >
                    {h}
                  </th>
                ))}
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
                    <tr
                      key={w.id}
                      className="hover:bg-muted/30 transition-colors"
                    >
                      <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">
                        {formatDateTime(w.created_at)}
                      </td>
                      <td className="px-4 py-3 font-medium text-foreground">
                        {formatNaira(w.amount)}
                      </td>
                      <td
                        className="px-4 py-3 text-foreground max-w-xs truncate"
                        title={w.reason}
                      >
                        {w.reason}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {w.authorized_by_name}
                      </td>
                      <td className="px-4 py-3">
                        <StatusPill status={w.status} />
                      </td>
                      <td className="px-4 py-3 text-foreground">
                        {w.pool_balance_after != null
                          ? formatNaira(w.pool_balance_after)
                          : "—"}
                      </td>
                    </tr>
                  ))}
              {!isLoading && items.length === 0 && (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-8 text-center text-muted-foreground text-sm"
                  >
                    No withdrawals recorded.
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
