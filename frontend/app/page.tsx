import Link from "next/link"
import Image from "next/image"
import { MessageCircle, ArrowRight } from "lucide-react"

/*
 * Landing page — marketing register (DESIGN.md, "Brand Assets & Illustration
 * System"). The signature patterns alternate by section, never combined in one
 * bounded area: zigzag carries the hero, chevron carries the closing band.
 */

const LOOP = [
  {
    step: "01",
    title: "Collect",
    body: "A payment link lands in the member's WhatsApp. Card, transfer, or USSD through Monnify checkout, settled to the right period every time.",
  },
  {
    step: "02",
    title: "Verify",
    body: "Before any money leaves, the recipient's account name is confirmed with their bank. The exco sees who they are actually paying.",
  },
  {
    step: "03",
    title: "Disburse",
    body: "An exco authorizes with an OTP and a real transfer moves the pool's money, from the bot or the dashboard.",
  },
  {
    step: "04",
    title: "Broadcast",
    body: "Every member gets the proof: amount, reason, who authorized it, and the transfer reference. Trust, not promises.",
  },
]

export default function LandingPage() {
  const waNumber = process.env.NEXT_PUBLIC_WHATSAPP_NUMBER ?? ""
  const waLink = `https://wa.me/${waNumber}`

  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* ---------------------------------------------------------------- Nav */}
      <nav className="flex items-center justify-between border-b border-border px-6 py-3">
        <Link href="/" className="flex items-center rounded-sm" aria-label="Ajoda home">
          {/* Full lockup — legible down to 104px, verified in browser */}
          <Image
            src="/brand/logo-lockup.png"
            alt="Ajoda"
            width={496}
            height={162}
            sizes="106px"
            priority
            className="w-[106px]"
          />
        </Link>
        <Link
          href="/login"
          className="-mr-2 flex items-center rounded-sm px-2 py-3 text-sm font-medium
                     text-brand-mkt transition-colors hover:text-brand-mkt-dark"
        >
          Sign in
        </Link>
      </nav>

      <main className="flex-1">
        {/* ------------------------------------------------------------ Hero */}
        <section className="relative isolate overflow-hidden bg-brand-mkt-dark">
          {/*
           * Signature pattern at hero weight (DESIGN.md: 25–40% over a
           * full-bleed ground). No scrim: measured against every ink in the
           * artwork, the worst-case blend (#494427, terracotta over the
           * ground) still gives the white headline 9.79:1 and the cream body
           * copy 6.31:1, so the pattern can stay legible as pattern.
           */}
          <div
            aria-hidden
            className="mkt-pattern mkt-pattern--zigzag opacity-[0.28]
                       [mask-image:linear-gradient(to_bottom,black,black_62%,transparent_100%)]"
          />

          <div className="relative mx-auto grid max-w-6xl items-center gap-x-16 gap-y-12 px-6 pt-20 pb-16 sm:pt-24 sm:pb-20 lg:grid-cols-[1.15fr_1fr]">
            <div>
              <h1
                className="mkt-rise text-balance font-[680] leading-[1.06] tracking-[-0.03em] text-white
                           [font-size:clamp(2.25rem,4.4vw,3.375rem)]"
              >
                Your cooperative&apos;s money, moving both ways on WhatsApp.
              </h1>
              <p
                className="mkt-rise mt-6 max-w-[46ch] text-[17px] leading-relaxed text-brand-mkt-cream/85
                           [--mkt-delay:110ms]"
              >
                Ajoda collects contributions and pays out verified withdrawals
                for ajo and esusu groups, and every member sees exactly where
                the pool&apos;s money went.
              </p>

              <div className="mkt-rise mt-9 flex flex-col gap-3 sm:flex-row [--mkt-delay:200ms]">
                <a
                  href={waLink}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center justify-center gap-2 rounded-sm bg-brand-mkt-cream px-6 py-3
                             text-sm font-semibold text-brand-mkt-dark transition-colors
                             hover:bg-white active:bg-brand-mkt-cream/90"
                >
                  <MessageCircle className="h-4 w-4" aria-hidden />
                  Open in WhatsApp
                </a>
                <Link
                  href="/login"
                  className="group inline-flex items-center justify-center gap-2 rounded-sm border
                             border-white/25 px-6 py-3 text-sm font-semibold text-white
                             transition-colors hover:border-white/50 hover:bg-white/10 active:bg-white/15"
                >
                  Exco dashboard
                  <ArrowRight
                    className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                    aria-hidden
                  />
                </Link>
              </div>
            </div>

            {/* The proof artifact — the transparency broadcast every member receives */}
            <div className="mkt-rise mx-auto w-full max-w-sm [--mkt-delay:290ms]">
              <div className="rounded-lg bg-white/10 p-1.5 shadow-overlay ring-1 ring-white/15">
                <div className="rounded-[10px] bg-brand-mkt-cream p-4">
                  <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.06em] text-brand-mkt-dark/60">
                    WhatsApp · to all 24 members
                  </p>
                  <div className="space-y-2 rounded-md rounded-tl-sm bg-white p-3.5 text-[13.5px] leading-relaxed text-foreground shadow-card">
                    <p className="font-semibold">
                      📢 Unity Thrift Coop — pool disbursement
                    </p>
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
              <p className="mt-3 text-center text-[12.5px] text-brand-mkt-cream/70">
                The message every member receives when pooled money moves.
              </p>
            </div>
          </div>

          {/* Full-colour signature strip closing the hero (DESIGN.md edge band) */}
          <div
            aria-hidden
            className="mkt-band mkt-band--zigzag h-16 bg-brand-mkt-cream sm:h-20"
          />
        </section>

        {/* ------------------------------------------------------- The loop */}
        <section className="mx-auto max-w-6xl px-6 py-20 sm:py-24">
          <h2 className="text-balance text-[26px] font-[620] tracking-[-0.02em] text-foreground">
            One loop, closed properly
          </h2>
          <p className="mt-2.5 max-w-[58ch] text-[15px] leading-relaxed text-muted-foreground">
            Most cooperative tools stop at collecting. Ajoda carries the money
            all the way back out again, and tells everyone about it.
          </p>

          <div className="mt-12 grid items-center gap-x-14 gap-y-12 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1fr)]">
            {/*
             * The source illustration the whole pattern system was extracted
             * from — a rotating pool passed hand to hand, which is literally
             * what this section describes. Full colour, marketing register.
             */}
            <Image
              src="/brand/illustration.png"
              alt="Six cooperative members in patterned cloth, passing contributions hand to hand around a ring."
              width={1100}
              height={898}
              sizes="(min-width: 640px) 520px, 92vw"
              className="mx-auto w-full max-w-[520px]"
            />

            {/* A real ordered sequence — the money moves through these four
                stages in this order — so the numbering carries information. */}
            <ol className="grid gap-x-8 gap-y-9 sm:grid-cols-2">
              {LOOP.map(({ step, title, body }) => (
                <li key={step} className="border-t border-border pt-4">
                  <span className="tabular block text-[13px] font-[620] tracking-[0.04em] text-brand-mkt-terracotta">
                    {step}
                  </span>
                  <h3 className="mt-2.5 text-[16px] font-[620] tracking-[-0.01em] text-foreground">
                    {title}
                  </h3>
                  <p className="mt-2 text-[14px] leading-relaxed text-muted-foreground">
                    {body}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* --------------------------------------------------- Closing band */}
        <section className="relative isolate overflow-hidden bg-brand-mkt-cream">
          <div
            aria-hidden
            className="mkt-pattern mkt-pattern--chevron opacity-[0.26]
                       [mask-image:linear-gradient(to_left,black,black_18%,transparent_66%)]"
          />
          <div className="relative mx-auto flex max-w-6xl flex-col items-start gap-7 px-6 py-16 sm:py-20 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-balance text-[26px] font-[620] leading-tight tracking-[-0.02em] text-brand-mkt-dark sm:text-[30px]">
                See the whole loop run.
              </h2>
              <p className="mt-2.5 max-w-[46ch] text-[15px] leading-relaxed text-brand-mkt-dark/75">
                Start a cooperative from WhatsApp, or sign in to the exco
                dashboard and authorize a real transfer.
              </p>
            </div>
            <a
              href={waLink}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex shrink-0 items-center justify-center gap-2 rounded-sm bg-brand-mkt-dark
                         px-6 py-3 text-sm font-semibold text-white transition-colors
                         hover:bg-brand-mkt active:bg-brand-mkt-dark/90"
            >
              <MessageCircle className="h-4 w-4" aria-hidden />
              Open in WhatsApp
            </a>
          </div>
        </section>
      </main>

      {/* ------------------------------------------------------------ Footer */}
      <footer className="bg-brand-mkt-dark px-6 py-10">
        <div className="mx-auto flex max-w-6xl flex-col items-center gap-4 text-center">
          {/*
           * DESIGN.md requires a second single-colour pass of the mark for
           * dark grounds — the brand forest green is only 1.89:1 against
           * --brand-mkt-dark. The mark is a single-colour silhouette on
           * transparency, so knocking it to white is that pass exactly
           * (13.22:1) without shipping a divergent second artwork file.
           */}
          <Image
            src="/brand/logo-mark.png"
            alt=""
            width={160}
            height={150}
            sizes="30px"
            aria-hidden
            className="h-[30px] w-auto opacity-85 [filter:brightness(0)_invert(1)]"
          />
          <p className="max-w-[62ch] text-[13px] leading-relaxed text-brand-mkt-cream/70">
            {/* One expression: JSX was swallowing the space after the year */}
            {`© ${new Date().getFullYear()} Ajoda. Built for the cooperative communities that keep Nigeria's informal economy running. Powered by Monnify (sandbox).`}
          </p>
        </div>
      </footer>
    </div>
  )
}
