"use client";

import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useCoop } from "@/context/CoopContext";
import { getCooperative, getInsights } from "@/lib/api/cooperatives";
import { formatNaira } from "@/lib/utils";
import { Skeleton } from "@/components/ui/Skeleton";
import { RecordWithdrawalButton } from "@/components/dashboard/RecordWithdrawalButton";

function MetricCard({
  title,
  value,
  loading,
  hero = false,
}: {
  title: string;
  value: string;
  loading: boolean;
  hero?: boolean;
}) {
  return (
    <div className="space-y-2 rounded-md border border-border bg-card p-4 shadow-card sm:p-5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-tertiary">
        {title}
      </p>
      {loading ? (
        <Skeleton className="h-8 w-32" />
      ) : (
        <p
          className={
            hero
              ? "tabular text-[28px] font-[560] tracking-[-0.03em] text-primary sm:text-[31px]"
              : "tabular text-xl font-[560] tracking-[-0.02em] text-foreground sm:text-2xl"
          }
        >
          {value}
        </p>
      )}
    </div>
  );
}

export default function DashboardPage() {
  const { activeCoop } = useCoop();
  const coopId = activeCoop?.id ?? "";

  const { data: coop, isLoading: coopLoading } = useQuery({
    queryKey: ["coop", coopId, "detail"],
    queryFn: () => getCooperative(coopId),
    enabled: !!coopId,
  });

  const { data: insight, isLoading: insightLoading } = useQuery({
    queryKey: ["coop", coopId, "insights"],
    queryFn: () => getInsights(coopId),
    enabled: !!coopId,
    staleTime: 5 * 60_000,
  });

  const loading = coopLoading || !coop;

  return (
    <div className="space-y-5 sm:space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-[23px] font-[620] tracking-[-0.015em] text-balance text-foreground">Overview</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {activeCoop?.name ?? "Loading..."}
          </p>
        </div>
        {activeCoop && (
          <RecordWithdrawalButton
            coopId={coopId}
            className="w-full sm:w-auto"
          />
        )}
      </div>

      <div className="space-y-4">
        <MetricCard
          title="Pool Balance"
          value={coop ? formatNaira(coop.pool_balance) : "—"}
          loading={loading}
          hero
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <MetricCard
            title="Total Members"
            value={coop ? String(coop.member_count) : "—"}
            loading={loading}
          />
          <MetricCard
            title="Collection Rate"
            value={coop ? `${coop.collection_rate_pct}%` : "—"}
            loading={loading}
          />
          <MetricCard
            title="YTD Collected"
            value={coop ? formatNaira(coop.ytd_collected_kobo) : "—"}
            loading={loading}
          />
        </div>
      </div>

      <div className="rounded-md bg-muted p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-secondary" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-foreground mb-1">
              AI Insight
            </p>
            {insightLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                {insight?.insight ?? "No insight available."}
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
