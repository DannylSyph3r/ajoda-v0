import Link from "next/link"
import { MessageCircle, ArrowRight, ArrowDownLeft, ShieldCheck, ArrowUpRight, Radio } from "lucide-react"

const LOOP = [
  {
    icon: ArrowDownLeft,
    title: "Collect",
    body: "A payment link lands in the member's WhatsApp. Card, transfer, or USSD — Monnify checkout, settled to the right period every time.",
  },
  {
    icon: ShieldCheck,
    title: "Verify",
    body: "Before any money leaves, the recipient's account name is confirmed with their bank. No wrong-account disasters.",
  },
  {
    icon: ArrowUpRight,
    title: "Disburse",
    body: "An exco authorizes with an OTP, and a real transfer moves the pool's money — from the bot or the dashboard.",
  },
  {
    icon: Radio,
    title: "Broadcast",
    body: "Every member gets the proof: amount, reason, who authorized it, and the transfer reference. Trust, not promises.",
  },
]

export default function LandingPage() {
  const waNumber = process.env.NEXT_PUBLIC_WHATSAPP_NUMBER ?? ""
  const waLink = `https://wa.me/${waNumber}`

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Nav */}
      <nav className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-[8px] bg-primary flex items-center justify-center">
            <span className="text-white font-bold text-xs">A</span>
          </div>
          <span className="font-semibold text-foreground">Ajoda</span>
        </div>
        <Link
          href="/login"
          className="text-sm font-medium text-primary-ink hover:underline"
        >
          Exco login
        </Link>
      </nav>

      {/* Hero */}
      <main className="flex-1 px-6 py-16 sm:py-24">
        <div className="mx-auto grid max-w-5xl items-center gap-12 lg:grid-cols-[1.1fr_1fr]">
          <div className="space-y-6">
            <h1 className="text-balance text-4xl font-[680] leading-[1.08] tracking-[-0.025em] text-foreground sm:text-5xl">
              Your cooperative&apos;s money, moving both ways on WhatsApp.
            </h1>
            <p className="max-w-[46ch] text-lg leading-relaxed text-muted-foreground">
              Ajoda collects contributions and pays out verified withdrawals for
              ajo and esusu groups — and every member sees exactly where the
              pool&apos;s money went.
            </p>
            <div className="flex flex-col gap-3 sm:flex-row">
              <a
                href={waLink}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center justify-center gap-2 rounded-sm bg-primary px-6 py-3
                           text-sm font-semibold text-white transition-colors hover:bg-primary-dark"
              >
                <MessageCircle className="h-4 w-4" />
                Open in WhatsApp
              </a>
              <Link
                href="/login"
                className="inline-flex items-center justify-center gap-2 rounded-sm border border-border-strong
                           px-6 py-3 text-sm font-semibold text-foreground transition-colors hover:bg-muted"
              >
                Exco dashboard
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          </div>

          {/* The proof artifact — the transparency broadcast every member receives */}
          <div className="mx-auto w-full max-w-sm">
            <div className="rounded-lg border border-border bg-card p-1.5 shadow-overlay">
              <div className="rounded-[10px] bg-muted p-4">
                <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.06em] text-tertiary">
                  WhatsApp · to all 24 members
                </p>
                <div className="space-y-2 rounded-md rounded-tl-sm bg-card p-3.5 text-[13.5px] leading-relaxed text-foreground shadow-card">
                  <p className="font-semibold">📢 Unity Thrift Coop — pool disbursement</p>
                  <p>
                    ₦250,000 was disbursed from the pool on 21 Jul for:{" "}
                    <span className="font-medium">Generator repair</span>.
                  </p>
                  <p className="text-muted-foreground">
                    Authorised by: Adaeze Okafor
                    <br />
                    To account: ••••6789
                  </p>
                  <p className="font-mono text-xs text-muted-foreground">
                    Ref: AJODA-DISB-1784…C1F171{" "}
                    <span className="font-sans font-medium text-success">
                      (completed)
                    </span>
                  </p>
                </div>
              </div>
            </div>
            <p className="mt-3 text-center text-[12.5px] text-tertiary">
              The message every member receives when pooled money moves.
            </p>
          </div>
        </div>

        {/* The loop */}
        <div className="mx-auto mt-20 max-w-5xl sm:mt-28">
          <h2 className="text-balance text-[22px] font-[620] tracking-[-0.015em] text-foreground">
            One loop, closed properly
          </h2>
          <div className="mt-8 grid gap-x-10 gap-y-8 sm:grid-cols-2">
            {LOOP.map(({ icon: Icon, title, body }) => (
              <div key={title} className="flex gap-4">
                <Icon className="mt-1 h-5 w-5 shrink-0 text-primary" aria-hidden />
                <div>
                  <h3 className="text-[15px] font-semibold text-foreground">{title}</h3>
                  <p className="mt-1 max-w-[52ch] text-sm leading-relaxed text-muted-foreground">
                    {body}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-border px-6 py-4 text-center">
        <p className="text-xs text-tertiary">
          © {new Date().getFullYear()} Ajoda. Built for the cooperative
          communities that keep Nigeria&apos;s informal economy running. Powered
          by Monnify (sandbox).
        </p>
      </footer>
    </div>
  )
}
