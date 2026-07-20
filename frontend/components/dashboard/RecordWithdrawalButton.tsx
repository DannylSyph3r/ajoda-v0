"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { StepUpModal } from "@/components/modals/StepUpModal";
import { DisbursementModal } from "@/components/modals/DisbursementModal";
import { cn } from "@/lib/utils";

interface RecordWithdrawalButtonProps {
  coopId: string;
  className?: string;
}

export function RecordWithdrawalButton({
  coopId,
  className,
}: RecordWithdrawalButtonProps) {
  const queryClient = useQueryClient();
  const [stepUpOpen, setStepUpOpen] = useState(false);
  const [disbursementOpen, setDisbursementOpen] = useState(false);
  const [stepUpToken, setStepUpToken] = useState("");

  const handleAuthorized = (token: string) => {
    setStepUpToken(token);
    setDisbursementOpen(true);
  };

  const handleSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ["coop", coopId, "detail"] });
    queryClient.invalidateQueries({
      queryKey: ["coop", coopId, "withdrawals"],
    });
  };

  return (
    <>
      <Button onClick={() => setStepUpOpen(true)} className={cn(className)}>
        <Plus className="w-4 h-4" />
        New withdrawal
      </Button>

      <StepUpModal
        open={stepUpOpen}
        onClose={() => setStepUpOpen(false)}
        action="WITHDRAWAL"
        onAuthorized={handleAuthorized}
      />

      <DisbursementModal
        open={disbursementOpen}
        onClose={() => setDisbursementOpen(false)}
        coopId={coopId}
        stepUpToken={stepUpToken}
        onSuccess={handleSuccess}
      />
    </>
  );
}
