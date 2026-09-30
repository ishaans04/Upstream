import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, Schibsted_Grotesk } from "next/font/google";
import { OfflineSync } from "@/components/OfflineSync";
import "./globals.css";

// Downloaded at build time and served from this origin: no request to Google from a
// viewer's browser (GC-15), and the mission app keeps its type offline.
const grotesk = Schibsted_Grotesk({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-grotesk" });
const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono" });

export const metadata: Metadata = {
  title: { default: "Upstream", template: "%s · Upstream" },
  description: "Upstream: contamination tracing for the Barapullah drain system, South Delhi.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.svg" },
  applicationName: "Upstream",
};

export const viewport: Viewport = { themeColor: "#0f1012", colorScheme: "dark", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN" className={`${grotesk.variable} ${plexMono.variable}`}>
      <body>
        <a className="skip-link" href="#main">Skip to main content</a>
        <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true" focusable="false">
          <defs>
            <pattern id="hatch" width="1" height="1" patternUnits="objectBoundingBox" patternContentUnits="objectBoundingBox">
              <rect width="1" height="1" fill="#151619" />
              <path d="M0 .25L.25 0M0 .5L.5 0M0 .75L.75 0M0 1L1 0M.25 1L1 .25M.5 1L1 .5M.75 1L1 .75" stroke="#9a9ca0" strokeWidth=".07" />
            </pattern>
            <symbol id="mark" viewBox="0 0 24 24">
              <path d="M5 3c0 5 5 5 5 10s-4 5-4 8" fill="none" stroke="#4f8fb5" strokeWidth="1.8" strokeLinecap="round" />
              <path d="M13 3c0 4 4 4 4 8s-3 4-3 6" fill="none" stroke="#4f8fb5" strokeWidth="1.8" strokeLinecap="round" />
              <circle cx="14" cy="18.5" r="2.6" fill="#f2a33a" />
            </symbol>
          </defs>
        </svg>
        {children}
        <OfflineSync />
      </body>
    </html>
  );
}
