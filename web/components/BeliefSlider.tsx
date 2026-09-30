"use client";
// FR-37: scrub through every stored belief. The slider's accessible name carries the
// moment it is showing, and the fingerprint beneath it is the one of the snapshot on
// screen, so what a judge verifies is what they are looking at.
import { useEffect, useRef, useState } from "react";
import { full, hm } from "@/lib/format";
import type { TimelinePoint } from "@/lib/types";

type Props = {
  timeline: TimelinePoint[];
  index: number;
  fingerprint: string | null;
  onChange: (i: number) => void;
};

const MAX_TICKS = 8;

export function BeliefSlider({ timeline, index, fingerprint, onChange }: Props) {
  const [playing, setPlaying] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const last = timeline.length - 1;
  const at = timeline[index];

  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  const stop = () => { if (timer.current) clearInterval(timer.current); timer.current = null; setPlaying(false); };
  const play = () => {
    if (playing) return stop();
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let k = 0;
    onChange(0);
    setPlaying(true);
    timer.current = setInterval(() => {
      k += 1;
      if (k > last) return stop();
      onChange(k);
    }, reduced ? 2200 : 1300);
  };

  const step = Math.max(1, Math.ceil(timeline.length / MAX_TICKS));
  const ticks = timeline.map((p, i) => (i % step === 0 || i === last ? hm(p.ts) : ""));

  return (
    <div className="slider">
      <div className="slider-row">
        {index !== last && (
          <span className="past">
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="5" fill="none" stroke="currentColor" strokeWidth="1.4" /><path d="M6 3.5V6l1.8 1.2" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>
            Viewing a past belief
          </span>
        )}
        <span className="now">{at ? `${full(at.ts)} · ${index + 1} of ${timeline.length}` : "No belief yet"}</span>
        <div className="spacer" />
        <button className="btn btn-quiet btn-sm" type="button" onClick={play} disabled={timeline.length < 2}>{playing ? "Pause" : "Play"}</button>
        <button className="btn btn-quiet btn-sm" type="button" onClick={() => { stop(); onChange(last); }} disabled={index === last}>Latest</button>
      </div>
      <span className="eyebrow" aria-hidden="true">Belief over time</span>
      <input type="range" min={0} max={Math.max(0, last)} step={1} value={index}
             aria-label={at ? `Showing belief at ${full(at.ts)}` : "Showing belief: none recorded yet"}
             aria-valuetext={at ? `${hm(at.ts)}, belief ${index + 1} of ${timeline.length}` : undefined}
             onChange={(e) => { stop(); onChange(Number(e.target.value)); }} disabled={timeline.length < 2} />
      <div className="ticks" style={{ gridTemplateColumns: `repeat(${timeline.length}, minmax(0,1fr))` }} aria-hidden="true">
        {ticks.map((t, i) => <span key={i}>{t}</span>)}
      </div>
      <div className="fp">
        Fingerprint <b>{fingerprint ?? "—"}</b><br />
        Recomputing from this fingerprint reproduces this belief bit for bit.
      </div>
    </div>
  );
}
