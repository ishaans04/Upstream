// TRACE (FR-13): the likely outfalls, and why. "Why" is the kernel's own computed
// explanation -- the observations whose likelihood moved this candidate -- not text
// written afterwards to sound plausible.
import { givenEvent, rankedSources, type EvidenceRow } from "@/lib/belief";
import { hm, pct, SOURCE_TYPE } from "@/lib/format";
import type { NetworkGeoJSON, Snapshot } from "@/lib/types";
import { SyntheticBadge } from "./SyntheticBadge";

type Props = { network: NetworkGeoJSON; snapshot: Snapshot; evidence: EvidenceRow[] };

export function outfallName(network: NetworkGeoJSON, nodeId: string) {
  return network.outfalls.features.find((f) => f.properties.node_id === nodeId)?.properties;
}

export function SourceRanking({ network, snapshot, evidence }: Props) {
  const top = rankedSources(snapshot, network).slice(0, 5);
  const ex = snapshot.explanation?.candidates?.[0];
  const byId = new Map(evidence.map((e) => [e.event_id, e]));
  const describe = (ids: { event_id: string }[]) => ids
    .map((l) => byId.get(l.event_id)).filter((e): e is EvidenceRow => !!e).slice(0, 2)
    .map((e) => `${e.payload.mission_id ? "test strip" : "report"} at ${hm(e.event_time)} (${e.payload.result === "positive" ? "seen" : "normal"})`);
  const sup = ex ? describe(ex.supported_by) : [];
  const rul = ex ? describe(ex.eliminated_rivals_by) : [];
  return (
    <>
      <div className="sources">
        {top.map((node, n) => {
          const o = outfallName(network, node);
          const p = givenEvent(snapshot, node);
          return (
            <div key={node} className={`src ${n === 0 ? "top" : ""}`}>
              <div>
                <div className="name">{o?.outfall_id ?? node} {o?.is_synthetic && n === 0 && <SyntheticBadge />}</div>
                <div className="type">{SOURCE_TYPE[o?.source_type ?? ""] ?? o?.source_type}</div>
              </div>
              <div className="bar" role="img" aria-label={`${o?.outfall_id ?? node}: ${pct(p)} given an event`}><i style={{ width: `${(p * 100).toFixed(1)}%` }} /></div>
              <div className="pct" aria-hidden="true">{pct(p)}</div>
            </div>
          );
        })}
      </div>
      <div className="why">
        <div><b>Supported by</b> {sup.length ? sup.join("; ") : "the prior for this weather only"}</div>
        <div><b>Eliminated rivals</b> {rul.length ? rul.join("; ") : "nothing yet"}</div>
        <div className="mono" style={{ fontSize: 11, color: "var(--faint)" }}>computed from the model&apos;s own likelihoods, not written afterwards</div>
      </div>
    </>
  );
}
