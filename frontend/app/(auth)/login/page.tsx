"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Phone, Lock } from "lucide-react";
import { toast } from "sonner";
import { login } from "@/lib/api/auth";
import type { ApiError } from "@/lib/api/client";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

export default function LoginPage() {
  const router = useRouter();
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(phone, pin);
      router.push("/dashboard");
    } catch (err) {
      const apiError = err as ApiError;
      toast.error(apiError.response?.data?.message ?? "Invalid credentials");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <h1 className="text-[27px] font-[620] tracking-[-0.02em] text-foreground">
        Welcome back
      </h1>
      <p className="mt-1.5 text-[15px] text-muted-foreground">
        Sign in to your exco dashboard.
      </p>

      <form onSubmit={handleSubmit} className="mt-8 space-y-4">
        <Input
          className="min-h-11"
          label="Phone number"
          type="tel"
          icon={<Phone className="w-4 h-4" />}
          placeholder="08012345678"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          required
          autoComplete="tel"
        />
        <Input
          className="min-h-11"
          label="PIN"
          type="password"
          inputMode="numeric"
          maxLength={6}
          icon={<Lock className="w-4 h-4" />}
          placeholder="Enter your PIN"
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
          required
          autoComplete="current-password"
        />
        <Button type="submit" loading={loading} size="lg" className="w-full">
          {loading ? "Signing in…" : "Sign in"}
        </Button>
      </form>

      <p className="mt-7 text-sm text-muted-foreground">
        Not registered?{" "}
        <Link
          href="/register"
          className="inline-flex min-h-11 items-center rounded-sm font-medium text-brand-mkt hover:underline"
        >
          Create an account
        </Link>
      </p>
    </>
  );
}
