"use client";
// The evidence behind the belief on screen, newest first. Three rules:
//  * a negative ("checked, looked normal") is evidence, drawn distinctly, never dropped;
//  * a retracted report stays, struck through, with the reason (GC-5);
//  * each row says whether the explanation used it for or against the top candidate.
import { useEffect, useId, useRef, useState } from "react";
import type { EvidenceRow } from "@/lib/belief";
import { hm, METHOD } from "@/lib/format";
import type { Explanation } from "@/lib/types";

type Filter = "all" | "positive" | "negative";

export function EvidenceList({ rows, explanation, topName }: { rows: EvidenceRow[]; explanation: Explanation; topName: string }) {
  const [filter, setFilter] = useState<Filter>("all");
  const ex = explanation?.candidates?.[0];
  const sup = new Set(ex?.supported_by.map((e) => e.event_id));
  const rul = new Set(ex?.eliminated_rivals_by.map((e) => e.event_id));
  const idp = useId();
  const shown = [...rows].reverse().filter((r) => filter === "all" || r.payload.result === filter
    || (filter === "positive" && r.payload.result === "quantitative"));

  return (
    <>
      <div className="drawer-filter" role="radiogroup" aria-label="Show">
        {([["all", "All"], ["positive", "Contamination seen"], ["negative", "Looked normal"]] as const).map(([k, label]) => (
          <button key={k} type="button" role="radio" aria-checked={filter === k} onClick={() => setFilter(k)}>{label}</button>
        ))}
      </div>
      <div className="drawer-body">
        <p className="drawer-note">Newest first. Nothing is ever deleted: a withdrawn report stays here, struck through.</p>
        <div className="evidence">
          {shown.length === 0 && <p className="note">No evidence of this kind in the belief shown.</p>}
          {shown.map((r) => {
            const pos = r.payload.result !== "negative";
            const kind = r.payload.mission_id ? "Test strip, mission" : METHOD[r.payload.method] ?? r.payload.method;
            const what = pos ? "Contamination seen" : "Checked, looked normal";
            const descId = `${idp}-${r.event_id}`;
            const testid = r.retracted ? "evidence-retracted" : pos ? "evidence-positive" : "evidence-negative";
            return (
              <div className="ev" key={r.event_id} data-testid={testid} aria-describedby={descId}>
                <div aria-hidden="true">
                  {r.retracted ? (
                    <svg width="18" height="18" viewBox="0 0 18 18"><circle cx="9" cy="9" r="6" fill="none" stroke="#9a9ca0" strokeWidth="1.6" /><path d="M4 14L14 4" stroke="#9a9ca0" strokeWidth="1.4" /></svg>
                  ) : r.payload.mission_id ? (
                    <svg width="18" height="18" viewBox="0 0 18 18"><rect x="4" y="4" width="10" height="10" rx="2" transform="rotate(45 9 9)" fill={pos ? "#e5533d" : "none"} stroke={pos ? "#f59a88" : "#7fa37a"} strokeWidth="1.8" /></svg>
                  ) : (
                    <svg width="18" height="18" viewBox="0 0 18 18"><circle cx="9" cy="9" r="6" fill={pos ? "#e5533d" : "none"} stroke={pos ? "#f59a88" : "#7fa37a"} strokeWidth="1.8" /></svg>
                  )}
                </div>
                <div>
                  <div className={`what ${r.retracted ? "line-through" : ""}`}><b>{what}</b> · {kind}</div>
                  <div className="sub" id={descId}>
                    {r.retracted ? `Withdrawn: ${r.retraction_reason ?? "retracted"}. ` : ""}
                    {what} at {r.payload.node_id} · {r.payload.observer_type}
                    {!pos && !r.retracted ? " · a negative is evidence too" : ""}
                    {r.payload.value != null ? ` · ${r.payload.value} ${r.payload.unit ?? ""}` : ""}
                  </div>
                  {!r.retracted && sup.has(r.event_id) && <span className="tag tag-sup">supports {topName}</span>}
                  {!r.retracted && rul.has(r.event_id) && <span className="tag tag-rule">rules out a rival</span>}
                </div>
                <div className="t" title={`recorded ${hm(r.recorded_at)}`}>{hm(r.event_time)}</div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

/** A modal drawer (WAI-ARIA dialog): focus moves in, Tab is trapped, Escape closes. */
export function Drawer({ open, onClose, title, eyebrow, sub, children }: {
  open: boolean; onClose: () => void; title: string; eyebrow: string; sub: string; children: React.ReactNode;
}) {
  const ref = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [closing, setClosing] = useState(false);
  const [mounted, setMounted] = useState(open);
  const titleId = useId();

  useEffect(() => {
    if (open) { setMounted(true); setClosing(false); return; }
    if (!mounted) return;
    setClosing(true);
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const t = setTimeout(() => { setMounted(false); setClosing(false); }, reduced ? 0 : 200);
    return () => clearTimeout(t);
  }, [open, mounted]);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
      if (e.key !== "Tab" || !ref.current) return;
      const f = [...ref.current.querySelectorAll<HTMLElement>("button, [href], [tabindex]:not([tabindex='-1'])")];
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [open, onClose]);

  if (!mounted) return null;
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside ref={ref} className={`drawer ${closing ? "closing" : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header className="drawer-head">
          <div>
            <div className="eyebrow">{eyebrow}</div>
            <h2 id={titleId}>{title}</h2>
            <p className="drawer-sub">{sub}</p>
          </div>
          <button ref={closeRef} type="button" className="drawer-close" aria-label={`Close the ${title.toLowerCase()}`} onClick={onClose}>
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
          </button>
        </header>
        {children}
      </aside>
    </>
  );
}
