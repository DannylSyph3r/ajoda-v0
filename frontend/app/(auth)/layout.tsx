import Image from "next/image";
import Link from "next/link";

/*
 * Auth chrome — marketing register (DESIGN.md, "Brand Assets & Illustration
 * System"). Chevron is this surface's signature pattern, the landing page runs
 * zigzag; the two never share a surface.
 *
 * The pattern is a bounded decorative panel, never tiled behind the form: the
 * form column stays on plain --surface per the accessibility floor, since it
 * carries credential fields.
 */
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="grid min-h-dvh grid-cols-1 bg-card lg:grid-cols-[1fr_minmax(0,44%)]">
      {/* ------------------------------------------------------ Form column */}
      <div className="flex flex-col">
        {/*
         * Mobile keeps the identity as a bounded strip above the form rather
         * than dropping the pattern entirely; the panel itself needs width to
         * read as textile, so it only appears from lg up.
         */}
        <div
          aria-hidden
          className="mkt-band mkt-band--chevron h-14 bg-brand-mkt-cream lg:hidden"
        />

        <div className="flex flex-1 flex-col justify-center px-6 py-12 sm:px-10 lg:px-14">
          <div className="mkt-rise mx-auto w-full max-w-sm">
            <Link
              href="/"
              className="-my-1 mb-9 inline-flex rounded-sm py-1"
              aria-label="Ajoda home"
            >
              <Image
                src="/brand/logo-lockup.png"
                alt="Ajoda"
                width={496}
                height={162}
                sizes="118px"
                priority
                className="w-[118px]"
              />
            </Link>

            {children}
          </div>
        </div>
      </div>

      {/* ------------------------------------------- Decorative panel (lg+) */}
      <aside
        aria-hidden
        className="relative hidden overflow-hidden bg-brand-mkt-cream lg:block"
      >
        {/* Full colour, per DESIGN.md's auth treatment */}
        <div className="mkt-pattern mkt-panel--chevron" />

        {/*
         * The line sits on a solid full-bleed plate, not on the pattern —
         * text over the weave would fail contrast at any opacity.
         */}
        <div className="absolute inset-x-0 bottom-0 bg-brand-mkt-dark px-10 py-9">
          <Image
            src="/brand/logo-mark.png"
            alt=""
            width={160}
            height={150}
            sizes="28px"
            className="h-7 w-auto opacity-85 [filter:brightness(0)_invert(1)]"
          />
          <p className="mt-4 max-w-[24ch] text-balance text-[19px] font-[560] leading-snug tracking-[-0.015em] text-brand-mkt-cream">
            Every naira in and out of the pool, on the record.
          </p>
        </div>
      </aside>
    </div>
  );
}
