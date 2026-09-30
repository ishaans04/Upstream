import { STREAM } from "@/lib/config";

export function Loading({ what }: { what: string }) {
  return <p className="note" role="status" aria-live="polite" style={{ padding: "22px 24px" }}>Loading {what}…</p>;
}

export function LoadError({ what, error }: { what: string; error: string }) {
  return (
    <div className="page">
      <p className="error-note" role="alert">
        Could not load {what}: {error}. The Core API may be down; ingestion keeps working without it (NFR-8), and this page will
        show the belief once the API answers.
      </p>
    </div>
  );
}

/** Nothing has happened yet: say how to make something happen, honestly. */
export function NoEpisodes() {
  return (
    <div className="empty">
      <b>No episode on the {STREAM} stream yet.</b>
      <span>An episode opens when the kernel&apos;s belief that something is happening passes the suspicion threshold.</span>
      {STREAM === "sim" ? (
        <span>Start the simulated incident: <code>make demo</code> (or <code>uv run python -m upstream_sim.demo</code>).</span>
      ) : (
        <span>Citizen reports, lab results and sensor feeds arrive through <code>/ingest</code>. To watch a simulated incident instead, build
          the web app with <code>NEXT_PUBLIC_STREAM=sim</code> and run <code>make demo</code>.</span>
      )}
    </div>
  );
}
