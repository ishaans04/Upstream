"use client";
// The app shell from the mockup: a narrow rail of sections (a bottom bar on phones)
// and a sticky bar naming the catchment and whether what you see is simulated.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CATCHMENT, STREAM } from "@/lib/config";

const NAV: { href: string; label: string; icon: React.ReactNode }[] = [
  { href: "/console", label: "Console", icon: <><path d="M3 5l4.5-2 5 2L17 3v12l-4.5 2-5-2L3 17z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /><path d="M7.5 3v12M12.5 5v12" fill="none" stroke="currentColor" strokeWidth="1.5" /></> },
  { href: "/replay", label: "Replay", icon: <><circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M10 6v4l3 2" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></> },
  { href: "/missions", label: "Missions", icon: <><path d="M10 17s5-5 5-9a5 5 0 10-10 0c0 4 5 9 5 9z" fill="none" stroke="currentColor" strokeWidth="1.5" /><circle cx="10" cy="8" r="1.8" fill="currentColor" /></> },
  { href: "/public-health", label: "Health", icon: <><path d="M10 3v14M3 10h14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /><rect x="2.5" y="2.5" width="15" height="15" rx="3" fill="none" stroke="currentColor" strokeWidth="1.3" /></> },
  { href: "/benchmarks", label: "Bench", icon: <path d="M4 16V9M10 16V4M16 16v-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /> },
];

export function Mark({ size = 24 }: { size?: number }) {
  return <svg width={size} height={size} aria-hidden="true"><use href="#mark" /></svg>;
}

export function StreamChip() {
  return STREAM === "sim"
    ? <span className="chip"><i aria-hidden="true" />Simulated incident · the network, physics and kernel are real</span>
    : <span className="chip"><i aria-hidden="true" />Live stream · {CATCHMENT.place}</span>;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname() || "";
  return (
    <div className="app">
      <nav className="rail" aria-label="Sections">
        <Link className="logo" href="/" aria-label="Upstream home"><Mark /></Link>
        {NAV.map((n) => (
          <Link key={n.href} className="nav-item" href={n.href}
                aria-current={path === n.href || path.startsWith(n.href + "/") ? "page" : undefined}>
            <svg viewBox="0 0 20 20" aria-hidden="true">{n.icon}</svg>{n.label}
          </Link>
        ))}
        <div className="bottom">
          <Link className="nav-item" href="/">
            <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M12 4l-6 6 6 6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg>Exit
          </Link>
        </div>
      </nav>
      <div className="main">
        <header className="appbar">
          <span className="title">UPSTREAM</span>
          <span className="crumb">{CATCHMENT.name} · {CATCHMENT.place}</span>
          <div className="spacer" />
          <StreamChip />
        </header>
        <main id="main" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
}
