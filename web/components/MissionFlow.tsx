"use client";
// One task, one place, one result (FR-38). The volunteer sees what their check is
// expected to change before they go, and what it measurably changed afterwards (G7).
// The time of the reading is taken from this phone at the moment they save it, and is
// never rewritten on sync (GC-4, NFR-9).
import { useEffect, useState } from "react";
import { acceptMission, getMissionFeedback } from "@/lib/api";
import { hm } from "@/lib/format";
import { submitMission, type Reading, type SubmitOutcome } from "@/lib/offline";
import type { Mission, MissionFeedback } from "@/lib/types";

export type MissionActions = {
  accept: (id: string, volunteerId: string) => Promise<unknown>;
  submit: (id: string, reading: Reading) => Promise<SubmitOutcome>;
  feedback: (id: string) => Promise<MissionFeedback>;
};
const DEFAULT_ACTIONS: MissionActions = { accept: acceptMission, submit: submitMission, feedback: getMissionFeedback };

type Step = "offer" | "record" | "queued" | "done" | "closed" | "other";

function initialStep(m: Mission, volunteerId: string): Step {
  if (m.status === "completed") return "done";
  if (m.assignee_id && m.assignee_id !== volunteerId) return "other";
  if (m.status === "expired" || m.status === "declined" || Date.parse(m.window_end) <= Date.now()) return "closed";
  return m.status === "accepted" ? "record" : "offer";
}

export function MissionFlow({ mission, volunteerId, actions = DEFAULT_ACTIONS, pollMs = 4000 }: {
  mission: Mission; volunteerId: string; actions?: MissionActions; pollMs?: number;
}) {
  const [step, setStep] = useState<Step>(() => initialStep(mission, volunteerId));
  const [result, setResult] = useState<"positive" | "negative" | null>(null);
  const [feedback, setFeedback] = useState<MissionFeedback | null>(null);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const method = mission.methods.includes("test_strip") ? "test_strip" : mission.methods[0];

  // The effect is measured once the kernel has recomputed with the reading, usually a
  // few seconds after completion; until then the answer is "recorded", so ask again.
  const measured = feedback != null && feedback.realised_gain != null;
  useEffect(() => {
    if (step !== "done" || measured) return;
    let live = true;
    const ask = () => actions.feedback(mission.mission_id).then((f) => { if (live) setFeedback(f); }).catch(() => {});
    if (!feedback) ask();
    const timer = setInterval(ask, pollMs);
    return () => { live = false; clearInterval(timer); };
  }, [step, measured, feedback, actions, mission.mission_id, pollMs]);

  // A queued reading is sent by the page's outbox or the service worker, neither of
  // which talks to this screen; ask the API whether the mission has completed.
  useEffect(() => {
    if (step !== "queued") return;
    let live = true;
    const check = () => actions.feedback(mission.mission_id).then((f) => {
      if (live && f.status === "completed") { setFeedback(f); setStep("done"); }
    }).catch(() => { /* still offline */ });
    const timer = setInterval(check, pollMs);
    window.addEventListener("online", check);
    return () => { live = false; clearInterval(timer); window.removeEventListener("online", check); };
  }, [step, actions, mission.mission_id, pollMs]);

  const accept = async () => {
    setBusy(true); setError(null);
    try { await actions.accept(mission.mission_id, volunteerId); setStep("record"); }
    catch (e) { setError(`Could not accept: ${(e as Error).message}`); }
    finally { setBusy(false); }
  };

  const save = async () => {
    if (!result) return;
    const observedAt = new Date();                      // the moment of the reading, on this phone
    setBusy(true); setError(null); setSavedAt(observedAt);
    try {
      const out = await actions.submit(mission.mission_id, {
        missionId: mission.mission_id, nodeId: mission.node_id, method, result, observerId: volunteerId, observedAt });
      if (out.queued) setStep("queued");
      else { setFeedback(out.feedback ?? null); setStep("done"); }
    } catch (e) {
      setError(`The reading was refused: ${(e as Error).message}`);
    } finally { setBusy(false); }
  };

  const where = (
    <div className="box"><div className="k">Where</div>
      <div>Drain point {mission.node_id}{mission.walk_cost_s ? `, about ${Math.round(mission.walk_cost_s / 60)} min walk` : ""}</div>
      {mission.lat != null && mission.lon != null && (
        <div className="mono" style={{ fontSize: 12, color: "var(--faint)" }}>{mission.lat.toFixed(5)}, {mission.lon.toFixed(5)}</div>
      )}
    </div>
  );

  return (
    <div className="mission-shell">
      <div className="screen" aria-live="polite">
        {step === "offer" && <>
          <div className="step">New mission · near you</div>
          <h2>Read a test strip at {mission.node_id}</h2>
          {where}
          <div className="box"><div className="k">When</div><div className="mono">{hm(mission.window_start)}–{hm(mission.window_end)}</div></div>
          <div className="box"><div className="k">Why it matters</div><div>{mission.expected_effect || "This check separates the remaining suspects."}</div></div>
          <p className="probe"><span className="safe" style={{ color: "var(--sage-text)", fontSize: 12 }}>Daylight · normal flow · public path. Do not step into the drain.</span></p>
          <button className="btn btn-primary big" type="button" onClick={accept} disabled={busy}>Accept mission</button>
        </>}

        {step === "record" && <>
          <div className="step">Record the result</div>
          <h2>What did the strip show?</h2>
          <div className="choice-btns" role="radiogroup" aria-label="Test strip result">
            <button type="button" role="radio" data-v="positive" aria-checked={result === "positive"} onClick={() => setResult("positive")}>Contamination</button>
            <button type="button" role="radio" data-v="negative" aria-checked={result === "negative"} onClick={() => setResult("negative")}>Looked normal</button>
          </div>
          <p className="note" style={{ margin: 0 }}>&quot;Looked normal&quot; is just as useful: it rules places out.</p>
          <div className="box"><div className="k">Checked at</div><div className="mono">the moment you tap Save, kept exactly as recorded</div></div>
          <button className="btn btn-primary big" type="button" onClick={save} disabled={!result || busy}>Save reading</button>
        </>}

        {step === "queued" && <>
          <div className="step">Saved</div>
          <h2>Waiting for signal</h2>
          <div className="offline" role="status">
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M1 5a9 9 0 0112 0M3.5 7.5a5.5 5.5 0 017 0M6 10a2 2 0 012 0" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /><path d="M2 2l10 10" stroke="currentColor" strokeWidth="1.4" /></svg>
            No signal. Saved on this phone; it will send when you are back online.
          </div>
          {savedAt && <div className="box"><div className="k">Checked at</div><div className="mono">{hm(savedAt)}, kept exactly as recorded</div></div>}
        </>}

        {step === "done" && <>
          <div className="step">Mission complete</div>
          <h2>Your check changed the picture</h2>
          <div className="box"><div className="k">What it did</div><div style={{ fontWeight: 600 }}>{feedback?.effect ?? "Recorded. The effect will show once the belief is recomputed."}</div></div>
          {feedback?.sources_before != null && feedback.sources_after != null && (
            <div className="box"><div className="k">Possible sources</div><div className="result-big num">{feedback.sources_before} → {feedback.sources_after}</div></div>
          )}
          <p className="note" style={{ margin: 0 }}>An officer confirms before anything is acted on.</p>
        </>}

        {step === "closed" && <>
          <div className="step">Mission closed</div>
          <h2>This mission&apos;s safe window has closed</h2>
          <p>Please do not go. After {hm(mission.window_end)} the reading no longer separates the suspects, and the planner only sends
            people in daylight and normal flow. A new mission will appear here if one is needed.</p>
        </>}

        {step === "other" && <>
          <div className="step">Not yours</div>
          <h2>This mission was offered to another volunteer</h2>
          <p>Missions go to the nearest available person. Yours appear on the missions list.</p>
        </>}

        {error && <p className="error-note" role="alert">{error}</p>}
      </div>
    </div>
  );
}
