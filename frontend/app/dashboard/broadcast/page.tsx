"use client";

import { useState, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Radio, Users } from "lucide-react";
import { useCoop } from "@/context/CoopContext";
import { getMembers, broadcastMessage } from "@/lib/api/cooperatives";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { StepUpModal } from "@/components/modals/StepUpModal";
import type { ApiError } from "@/lib/api/client";
import type { StoredUser } from "@/lib/api/types";

const noopSubscribe = () => () => {};

export default function BroadcastPage() {
  const { activeCoop } = useCoop();
  const coopId = activeCoop?.id ?? "";

  // The exco sending a broadcast never receives their own message (the
  // backend excludes the sender's phone) — mirror that here so the panel
  // shows who will actually get it, not the whole roster.
  const storedUser = useSyncExternalStore(
    noopSubscribe,
    () => (typeof window === "undefined" ? null : localStorage.getItem("user")),
    () => null,
  );
  let currentUserId: string | null = null;
  if (storedUser) {
    try {
      currentUserId = (JSON.parse(storedUser) as StoredUser).id;
    } catch {
      currentUserId = null;
    }
  }

  const { data: members = [], isLoading: membersLoading } = useQuery({
    queryKey: ["coop", coopId, "members"],
    queryFn: () => getMembers(coopId),
    enabled: !!coopId,
  });

  const recipients = members.filter((m) => m.member_id !== currentUserId);

  const [message, setMessage] = useState("");
  const [stepUpOpen, setStepUpOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSend = () => {
    if (!message.trim()) {
      toast.error("Please enter a message");
      return;
    }
    setStepUpOpen(true);
  };

  const handleAuthorized = async (stepUpToken: string) => {
    setSubmitting(true);
    try {
      const result = await broadcastMessage(
        coopId,
        message.trim(),
        stepUpToken,
      );
      toast.success(`Message sent to ${result.sent_to} member(s)`);
      setMessage("");
    } catch (err) {
      const apiError = err as ApiError;
      toast.error(apiError.response?.data?.message ?? "Broadcast failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-3xl space-y-5 sm:space-y-6">
      <div>
        <h1 className="text-[23px] font-[620] tracking-[-0.015em] text-foreground">
          Broadcast
        </h1>
        <p className="text-[13.5px] text-muted-foreground">
          Send a WhatsApp message to every member of{" "}
          {activeCoop?.name ?? "this cooperative"}.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_240px] lg:items-start">
        <div className="space-y-4 rounded-md border border-border bg-card p-4 shadow-card sm:p-5">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-foreground">Message</label>
            <textarea
              className="w-full rounded-sm border border-border-strong bg-card px-3 py-2 text-sm
                         text-foreground placeholder:text-muted-foreground resize-none
                         transition-colors focus:border-primary"
              rows={6}
              maxLength={1000}
              placeholder="Type the message to send to all members via WhatsApp…"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
            <p className="text-xs text-muted-foreground text-right tabular">
              {message.length}/1000
            </p>
          </div>

          <div className="flex justify-end">
            <Button
              onClick={handleSend}
              loading={submitting}
              disabled={!message.trim() || recipients.length === 0}
              className="w-full sm:w-auto"
            >
              <Radio className="w-4 h-4" />
              Send Broadcast
            </Button>
          </div>
        </div>

        <div className="space-y-3 rounded-md border border-border bg-card p-4 shadow-card sm:p-5">
          <div className="flex items-center gap-1.5 text-tertiary">
            <Users className="h-3.5 w-3.5" />
            <p className="text-[11px] font-semibold uppercase tracking-[0.06em]">
              Recipients
            </p>
          </div>

          {membersLoading ? (
            <Skeleton className="h-8 w-14" />
          ) : (
            <p className="tabular text-2xl font-[560] tracking-[-0.02em] text-primary">
              {recipients.length}
            </p>
          )}

          {membersLoading ? (
            <div className="space-y-2 pt-1">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-5/6" />
            </div>
          ) : recipients.length === 0 ? (
            <p className="text-[12.5px] text-muted-foreground">
              {members.length === 0
                ? "No members yet — add someone before broadcasting."
                : "No one else to message yet — you're the only member."}
            </p>
          ) : (
            <ul className="max-h-56 space-y-2 overflow-y-auto border-t border-border pt-3">
              {recipients.map((m) => (
                <li
                  key={m.member_id}
                  className="flex items-center justify-between gap-2 text-[13px]"
                >
                  <span className="truncate text-foreground">{m.full_name}</span>
                  <span className="shrink-0 capitalize text-muted-foreground">
                    {m.role}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <StepUpModal
        open={stepUpOpen}
        onClose={() => setStepUpOpen(false)}
        action="BROADCAST"
        onAuthorized={handleAuthorized}
      />
    </div>
  );
}
