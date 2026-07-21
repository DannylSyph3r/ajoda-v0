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

            {/*
             * The proof artifact. Rendered as the actual WhatsApp message a
             * member receives rather than a card labelled "WhatsApp" — the
             * medium is the argument, so the bubble carries it instead of an
             * eyebrow, and no explanatory caption is needed underneath.
             */}
            <div className="mkt-rise mx-auto w-full max-w-[400px] [--mkt-delay:290ms]">
              <div className="relative">
                {/* Incoming-bubble tail */}
                <span
                  aria-hidden
                  className="absolute -left-[9px] top-0 h-[18px] w-[10px] bg-white
                             [clip-path:polygon(100%_0,0_0,100%_60%)]"
                />

                <div className="rounded-xl rounded-tl-none bg-white px-4 pb-3 pt-3.5 shadow-overlay">
                  {/* Sender */}
                  <div className="flex items-center gap-2.5 border-b border-border pb-3">
                    <Image
                      src="/brand/logo-mark.png"
                      alt=""
                      width={160}
                      height={150}
                      sizes="28px"
                      aria-hidden
                      className="h-7 w-7 shrink-0 rounded-full bg-brand-tint object-contain p-1"
                    />
                    <span className="min-w-0 flex-1 truncate text-[14px] font-[620] tracking-[-0.01em] text-foreground">
                      Unity Thrift Coop
                    </span>
                    <span className="shrink-0 text-[11.5px] text-tertiary">
                      21 Jul, 14:32
                    </span>
                  </div>

                  {/* The money, given the weight it deserves */}
                  <p className="mt-3.5 flex items-baseline gap-1">
                    <span className="text-[20px] font-[450] text-tertiary">₦</span>
                    {/* No tabular-nums: it gives the comma a full digit
                        advance, which reads as "250 , 000". Nothing aligns
                        against this figure, so proportional is correct. */}
                    <span className="text-[31px] font-[560] leading-none tracking-[-0.03em] text-foreground">
                      250,000
                    </span>
                  </p>
                  <p className="mt-1.5 text-[14px] leading-snug text-muted-foreground">
                    Disbursed from the pool for{" "}
                    <span className="font-medium text-foreground">
                      generator repair
                    </span>
                    .
                  </p>

                  {/* Receipt detail */}
                  <dl className="mt-3.5 space-y-1.5 border-t border-border pt-3 text-[13px]">
                    <div className="flex justify-between gap-4">
                      <dt className="text-tertiary">Authorised by</dt>
                      <dd className="font-medium text-foreground">
                        Adaeze Okafor
                      </dd>
                    </div>
                    <div className="flex justify-between gap-4">
                      <dt className="text-tertiary">To account</dt>
                      <dd className="tabular font-medium text-foreground">
                        ••••6789
                      </dd>
                    </div>
                  </dl>

                  {/* Reference + state — dot + word, per the status vocabulary */}
                  <div className="mt-3 flex items-center justify-between gap-3 border-t border-border pt-3">
                    <span className="min-w-0 truncate font-mono text-[11.5px] text-tertiary">
                      AJODA-DISB-1784…C1F171
                    </span>
                    <span className="flex shrink-0 items-center gap-1.5 text-[12.5px] font-medium text-success">
                      <span
                        aria-hidden
                        className="h-[7px] w-[7px] rounded-full bg-success"
                      />
                      Completed
                    </span>
                  </div>

                  {/* Read receipt — the detail that makes it read as real */}
                  <div className="mt-2.5 flex items-center justify-end gap-1 text-[11px] text-tertiary">
                    <span>14:32</span>
                    <svg
                      viewBox="0 0 18 12"
                      className="h-3 w-[18px] text-[#53bdeb]"
                      fill="none"
                      aria-hidden
                    >
                      <path
                        d="M1 6.5 4.2 9.8 10.6 2.2M7.4 9.8 13.8 2.2"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </div>
                </div>
              </div>
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
            {`© ${new Date().getFullYear()} Ajoda. Built for the cooperative communities that keep Nigeria's informal economy running.`}
          </p>

          {/*
           * Payments partner mark. The lockup is 4.47:1, so it is sized by
           * width and never by height — at 116px wide it sits a touch below
           * the wordmark's optical weight, which is right for a trust mark.
           * The asset is already single-colour #9CA3AF (5.21:1 here).
           */}
          <div className="mt-5 flex flex-col items-center gap-2.5 border-t border-white/10 pt-6">
            <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-brand-mkt-cream/45">
              Payments secured by
            </span>
            <Image
              src="/brand/monnify-grey.svg"
              alt="Monnify"
              width={831}
              height={186}
              className="w-[116px] opacity-80 transition-opacity hover:opacity-100"
            />
            <span className="text-[11.5px] text-brand-mkt-cream/40">
              Sandbox environment
            </span>
          </div>
        </div>
      </footer>
    </div>
  )
}
