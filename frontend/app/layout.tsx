import type { Metadata } from "next";
import { Schibsted_Grotesk } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

const schibsted = Schibsted_Grotesk({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-schibsted",
});

export const metadata: Metadata = {
  title: "Ajoda",
  description:
    "Cooperative savings on WhatsApp — collections in, verified disbursements out.",
  openGraph: {
    title: "Ajoda",
    description:
      "Cooperative savings on WhatsApp — collections in, verified disbursements out.",
    images: [
      {
        url: "https://ajoda.slethware.dev/og-image.png?v=1",
        width: 1221,
        height: 595,
      },
    ],
    type: "website",
    url: "https://ajoda.slethware.dev",
  },
  twitter: {
    card: "summary_large_image",
    title: "Ajoda",
    description:
      "Cooperative savings on WhatsApp — collections in, verified disbursements out.",
    images: ["https://ajoda.slethware.dev/og-image.png?v=1"],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={schibsted.variable}>
      <body className="antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
