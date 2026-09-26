import type { Metadata } from "next";
import { Space_Grotesk, Plus_Jakarta_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";

import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/components/auth-provider";

const spaceGrotesk  = Space_Grotesk({ subsets: ["latin"], variable: "--font-space-grotesk", display: "swap", weight: ["400","500","600","700"] });
const plusJakarta   = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-plus-jakarta", display: "swap" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

const brandName = process.env.NEXT_PUBLIC_BRAND_NAME || "MidVox";

export const metadata: Metadata = {
  title: `${brandName} — Discord Bot`,
  description: "Security, leveling, tickets, and more. One dashboard — no commands required.",
  openGraph: {
    title: `${brandName} — Discord Bot`,
    description: "Security, leveling, tickets, and more. One dashboard — no commands required.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${spaceGrotesk.variable} ${plusJakarta.variable} ${jetbrainsMono.variable}`}>
      <body className="bg-[var(--bg)] font-sans text-[var(--ink)] antialiased">
        {/* Subtle grid background */}
        <div
          aria-hidden
          className="pointer-events-none fixed inset-0 -z-20 opacity-40"
          style={{
            backgroundImage:
              "linear-gradient(rgba(138,154,91,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(138,154,91,0.05) 1px, transparent 1px)",
            backgroundSize: "40px 40px",
            maskImage: "radial-gradient(ellipse 90% 70% at 50% 0%, black 20%, transparent 80%)",
          }}
        />
        {/* Soft dashboard accent glow */}
        <div
          aria-hidden
          className="pointer-events-none fixed top-0 left-1/2 -translate-x-1/2 -z-10"
          style={{
            width: "900px",
            height: "500px",
            background: "radial-gradient(ellipse 80% 60% at 50% 0%, rgba(168,189,109,0.10) 0%, transparent 70%)",
          }}
        />
        <AuthProvider>
          {children}
          <Toaster />
        </AuthProvider>
      </body>
    </html>
  );
}
