"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  LayoutDashboard,
  Users,
  ScrollText,
  ArrowDownCircle,
  Settings,
  Radio,
  MessageSquare,
  Plus,
  ChevronRight,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useCoop } from "@/context/CoopContext";
import type { CooperativeListItem } from "@/lib/api/types";

const NAV_ITEMS = [
  { label: "Overview", href: "/dashboard", icon: LayoutDashboard, exact: true },
  { label: "Members", href: "/dashboard/members", icon: Users, exact: false },
  {
    label: "History",
    href: "/dashboard/history",
    icon: ScrollText,
    exact: false,
  },
  {
    label: "Withdrawals",
    href: "/dashboard/withdrawals",
    icon: ArrowDownCircle,
    exact: false,
  },
  {
    label: "Broadcast",
    href: "/dashboard/broadcast",
    icon: Radio,
    exact: false,
  },
  {
    label: "AI Advisor",
    href: "/dashboard/chat",
    icon: MessageSquare,
    exact: false,
  },
  {
    label: "Settings",
    href: "/dashboard/settings",
    icon: Settings,
    exact: false,
  },
];

function CoopCard({
  coop,
  active,
  onClick,
}: {
  coop: CooperativeListItem;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left px-3 py-2.5 rounded-sm transition-colors border",
        active
          ? "bg-primary-tint border-transparent"
          : "border-transparent hover:bg-muted",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p
            className={cn(
              "text-sm font-medium truncate",
              active ? "text-primary-ink" : "text-foreground",
            )}
          >
            {coop.name}
          </p>
          <p className="text-xs text-muted-foreground capitalize">
            {coop.role}
          </p>
        </div>
        {active && (
          <ChevronRight className="w-3.5 h-3.5 text-primary-ink shrink-0" />
        )}
      </div>
    </button>
  );
}

function DashboardNavContent({
  onNavigate,
  showCloseButton = false,
}: {
  onNavigate?: () => void;
  showCloseButton?: boolean;
}) {
  const pathname = usePathname();
  const { activeCoop, setActiveCoop, allCoops } = useCoop();

  const isActive = (href: string, exact: boolean) =>
    exact ? pathname === href : pathname.startsWith(href);

  return (
    <div className="flex h-full flex-col bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-4 sm:px-6 sm:py-5">
        <div className="flex items-center gap-2">
          <Image
            src="/brand/logo-mark.png"
            alt=""
            width={160}
            height={150}
            sizes="28px"
            className="h-7 w-7 object-contain"
          />
          <span className="font-semibold text-foreground">Ajoda</span>
        </div>
        {showCloseButton && (
          <button
            type="button"
            onClick={onNavigate}
            className="inline-flex h-11 w-11 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:hidden"
            aria-label="Close navigation"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      <div className="border-b border-border px-3 py-4">
        <p className="text-[11px] font-semibold text-tertiary uppercase tracking-wider px-3 mb-2">
          Cooperatives
        </p>
        <div className="space-y-1">
          {allCoops.map((coop) => (
            <CoopCard
              key={coop.id}
              coop={coop}
              active={activeCoop?.id === coop.id}
              onClick={() => {
                setActiveCoop(coop);
                onNavigate?.();
              }}
            />
          ))}
        </div>
        <Link
          href="/dashboard/setup"
          onClick={onNavigate}
          className="mt-2 flex items-center gap-2 w-full px-3 py-2 text-sm text-muted-foreground
                     hover:text-primary-ink hover:bg-primary-tint rounded-sm transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Cooperative
        </Link>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto scrollbar-thin">
        {NAV_ITEMS.map(({ label, href, icon: Icon, exact }) => {
          const active = isActive(href, exact);
          return (
            <Link
              key={href}
              href={href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-sm text-sm font-medium transition-colors",
                active
                  ? "bg-primary-tint text-primary-ink"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted",
              )}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden h-[100dvh] w-[232px] shrink-0 border-r border-border bg-card lg:flex lg:flex-col">
      <DashboardNavContent />
    </aside>
  );
}

export function MobileNavDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.button
            type="button"
            aria-label="Close navigation"
            className="fixed inset-0 z-30 bg-black/40 lg:hidden"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={onClose}
          />
          <motion.aside
            className="fixed inset-y-0 left-0 z-40 w-[min(20rem,calc(100vw-1rem))] max-w-full border-r border-border bg-card shadow-overlay lg:hidden"
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ duration: 0.2, ease: "easeOut" }}
          >
            <DashboardNavContent onNavigate={onClose} showCloseButton />
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
