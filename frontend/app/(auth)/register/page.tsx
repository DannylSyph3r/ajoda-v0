"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { User, Phone, Lock } from "lucide-react";
import { toast } from "sonner";
import { register } from "@/lib/api/auth";
import type { ApiError } from "@/lib/api/client";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    fullName: "",
    phone: "",
    pin: "",
    confirmPin: "",
  });
  const [loading, setLoading] = useState(false);

  // Surfaced inline rather than only on submit — a mismatch the user can
  // already see shouldn't wait for a round trip to become a toast.
  const pinMismatch =
    form.confirmPin.length > 0 && form.pin !== form.confirmPin;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (form.pin !== form.confirmPin) {
      toast.error("PINs do not match");
      return;
    }
    if (form.pin.length < 4) {
      toast.error("PIN must be at least 4 digits");
      return;
    }
    setLoading(true);
    try {
      await register(form.fullName.trim(), form.phone, form.pin);
      router.push("/dashboard/setup");
    } catch (err) {
      const apiError = err as ApiError;
      toast.error(apiError.response?.data?.message ?? "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <h1 className="text-[27px] font-[620] tracking-[-0.02em] text-foreground">
        Create your account
      </h1>
      <p className="mt-1.5 text-[15px] text-muted-foreground">
        Set up exco access for your cooperative.
      </p>

      <form onSubmit={handleSubmit} className="mt-8 space-y-4">
        <Input
          className="min-h-11"
          label="Full name"
          icon={<User className="w-4 h-4" />}
          placeholder="Adaeze Okonkwo"
          autoComplete="name"
          required
          value={form.fullName}
          onChange={(e) =>
            setForm((p) => ({ ...p, fullName: e.target.value }))
          }
        />
        <Input
          className="min-h-11"
          label="Phone number"
          type="tel"
          icon={<Phone className="w-4 h-4" />}
          placeholder="08012345678"
          autoComplete="tel"
          required
          value={form.phone}
          onChange={(e) => setForm((p) => ({ ...p, phone: e.target.value }))}
        />
        <Input
          className="min-h-11"
          label="PIN"
          type="password"
          inputMode="numeric"
          maxLength={6}
          icon={<Lock className="w-4 h-4" />}
          placeholder="4–6 digit PIN"
          autoComplete="new-password"
          required
          value={form.pin}
          onChange={(e) =>
            setForm((p) => ({ ...p, pin: e.target.value.replace(/\D/g, "") }))
          }
        />
        <Input
          className="min-h-11"
          label="Confirm PIN"
          type="password"
          inputMode="numeric"
          maxLength={6}
          icon={<Lock className="w-4 h-4" />}
          placeholder="Repeat your PIN"
          autoComplete="new-password"
          required
          value={form.confirmPin}
          error={pinMismatch ? "PINs do not match" : undefined}
          onChange={(e) =>
            setForm((p) => ({
              ...p,
              confirmPin: e.target.value.replace(/\D/g, ""),
            }))
          }
        />
        <Button type="submit" loading={loading} size="lg" className="w-full">
          {loading ? "Creating account…" : "Create account"}
        </Button>
      </form>

      <p className="mt-7 text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link
          href="/login"
          className="inline-flex min-h-11 items-center rounded-sm font-medium text-brand-mkt hover:underline"
        >
          Sign in
        </Link>
      </p>
    </>
  );
}
