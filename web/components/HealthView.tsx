"use client";
// FR-39, the public-health view: where and when people may have been in contact with
// contaminated water, and what the clinical statistics said. Candidate sources are
// deliberately absent (GC-12): the endpoints this page reads do not carry them, so
// they cannot leak into it. Every screen carries the standing notice.
import { useMemo, useState } from "react";
import { getClinicalEpisodes, getNetwork, getPublicHealth, type ClinicalZone } from "@/lib/api";
import { ringCentroid } from "@/lib/belief";
import { NOT_A_DIAGNOSIS } from "@/lib/config";
import { full, hm, pct, PATHWAY } from "@/lib/format";
import { zoneGroupId, zoneLabel } from "@/lib/places";
import type { NetworkGeoJSON, PublicHealthEpisode, ZoneExposure } from "@/lib/types";
import { EpisodeStateBadge } from "./EpisodeStateBadge";
import { LoadError, Loading } from "./States";
import { useLoad } from "./useLoad";

const GI_TESTS = "norovirus, Campylobacter, Shiga-toxin E. coli, Cryptosporidium and Giardia";

export function Notice() {
  return (
    <div className="notice" role="note">
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" style={{ flex: "none", marginTop: 2 }}><circle cx="9" cy="9" r="7.5" fill="none" stroke="#f7bd6a" strokeWidth="1.4" /><path d="M9 5v5M9 12.5v.5" stroke="#f7bd6a" strokeWidth="1.6" strokeLinecap="round" /></svg>
      <div><b>{NOT_A_DIAGNOSIS}</b> Advisory decisions are made by public health officers. Upstream never contacts patients and never issues advisories.</div>
    </div>
  );
}

async function load() {
  const [ph, clinical, network] = await Promise.all([getPublicHealth(), getClinicalEpisodes().catch(() => ({ episodes: [] })), getNetwork()]);
  return { ph, clinical, network };
}

export function HealthView() {
  const r = useLoad(load, []);
  if (r.error) return <LoadError what="the public-health view" error={r.error} />;
  if (!r.data) return <Loading what="the public-health view" />;
  const ep = r.data.ph.episodes[0];
  const curves = r.data.clinical.episodes.find((e) => e.episode_id === ep?.episode_id)?.zones ?? {};
  return <HealthBody episode={ep ?? null} curves={curves} network={r.data.network} />;
}

export function HealthBody({ episode, curves, network }: { episode: PublicHealthEpisode | null; curves: Record<string, ClinicalZone>; network: NetworkGeoJSON }) {
  const names = useMemo(() => new Map(network.zones.features.map((f) => [f.properties.zone_id, {
    name: zoneLabel(f.properties.name, ringCentroid(f.geometry.coordinates)), population: f.properties.population_upper_bound }])), [network]);
  const zones = useMemo(() => Object.values(episode?.zone_windows ?? {})
    .filter((w) => w.window_lo != null && w.p_peak >= 0.05)
    .sort((a, b) => (a.window_lo ?? 0) - (b.window_lo ?? 0)), [episode]);
  const [picked, setPicked] = useState<string | null>(null);
  const sel = zones.find((z) => z.zone_id === picked) ?? zones[0];

  return (
    <section className="page" aria-labelledby="healthTitle">
      <div className="page-head"><div>
        <div className="eyebrow">Public-health view</div>
        <h1 id="healthTitle">{episode ? <>Exposure context for {episode.episode_id} <EpisodeStateBadge state={episode.state} /></> : "Exposure context"}</h1>
        <p className="desc">Where and when people may have been in contact with contaminated water. Candidate sources are deliberately left out of this view.</p>
      </div></div>
      <Notice />
      {!episode ? (
        <div className="empty"><b>No probable or confirmed episode.</b><span>Suspected episodes are not shown here: one unconfirmed report is not a reason to spend a clinician&apos;s attention.</span></div>
      ) : (
        <>
          <div className="hgrid">
            <div className="card">
              <div className="card-head"><h2>Zones along the drains</h2><span className="aside">{zones.length} expect exposure</span></div>
              <div className="zpick" role="radiogroup" aria-label="Choose a zone">
                {zones.map((z) => {
                  const n = names.get(z.zone_id);
                  return (
                    <button key={z.zone_id} type="button" role="radio" className="zbtn" aria-checked={sel?.zone_id === z.zone_id} onClick={() => setPicked(z.zone_id)}>
                      <span className="n">{n?.name ?? z.zone_id}</span>
                      <span className="w">{hm(z.window_lo!)}–{hm(z.window_hi!)}<small>{pct(z.p_peak)} chance</small></span>
                      <span className="d">{z.pathways.map((p) => PATHWAY[p] ?? p).join(", ")} · up to {n?.population ?? "?"}</span>
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="card zdetail" aria-live="polite">
              {sel ? <ZoneDetail z={sel} name={names.get(sel.zone_id)?.name ?? sel.zone_id} population={names.get(sel.zone_id)?.population}
                                 curve={curves[sel.zone_id]} windowEnd={episode.clinical_window_end} />
                : <p className="note">No zone expects exposure in the current belief.</p>}
            </div>
          </div>
          <div className="hgrid">
            <ClinicalResults episode={episode} names={names} />
            <CdsPreview episodeId={episode.episode_id} />
          </div>
        </>
      )}
    </section>
  );
}

function ZoneDetail({ z, name, population, curve, windowEnd }: { z: ZoneExposure; name: string; population?: number; curve?: ClinicalZone; windowEnd: string | null }) {
  const daysLeft = windowEnd ? Math.max(0, Math.round((Date.parse(windowEnd) - Date.now()) / 86400000)) : 0;
  return (
    <>
      <div><div className="eyebrow">Selected zone</div><h3>{name}</h3></div>
      <div className="chips">
        {z.pathways.map((p) => <span key={p} className="chip2">{PATHWAY[p] ?? p}</span>)}
        {population != null && <span className="chip2">up to {population} people</span>}
      </div>
      <div className="facts">
        <div className="fact2"><div className="k">80% window</div><div className="v mono">{hm(z.window_lo!)}–{hm(z.window_hi!)}</div></div>
        <div className="fact2"><div className="k">Chance of exposure</div><div className="v num">{pct(z.p_peak)}</div><div className="meter"><i style={{ width: `${(z.p_peak * 100).toFixed(0)}%` }} /></div></div>
        <div className="fact2"><div className="k">Clinically relevant</div><div className="v num">{daysLeft} days left</div><div className="meter"><i style={{ width: `${Math.min(100, (100 * daysLeft) / 16).toFixed(0)}%` }} /></div></div>
      </div>
      {curve?.t_grid?.length ? <ZoneCurve curve={curve} lo={z.window_lo!} hi={z.window_hi!} /> : null}
      <p className="consider">If someone who uses this spot presents with <b>acute gastroenteritis</b> in the next {daysLeft} days, the incubation periods
        involved point to testing for <b>{GI_TESTS}</b>. Routine panels often miss these.</p>
    </>
  );
}

function ZoneCurve({ curve, lo, hi }: { curve: ClinicalZone; lo: number; hi: number }) {
  const W = 560, H = 120, L = 6, R = 6, T = 8, B = 22;
  const t0 = curve.t_grid[0], t1 = curve.t_grid[curve.t_grid.length - 1];
  const X = (t: number) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
  const Y = (p: number) => T + (1 - p) * (H - T - B);
  const area = `M${X(t0)},${Y(0)} ` + curve.t_grid.map((t, k) => `L${X(t).toFixed(1)},${Y(curve.p_exposed[k]).toFixed(1)}`).join(" ") + ` L${X(t1)},${Y(0)} Z`;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => t0 + f * (t1 - t0));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Chance of exposure over time, 80% window ${hm(lo)} to ${hm(hi)}`} style={{ width: "100%", height: "auto", display: "block" }}>
      <rect x={X(lo)} y={T} width={Math.max(1, X(hi) - X(lo))} height={H - T - B} fill="rgba(242,163,58,.13)" />
      <path d={area} fill="rgba(242,163,58,.28)" stroke="#f2a33a" strokeWidth="1.6" />
      {ticks.map((t) => <text key={t} x={X(t)} y={H - 6} textAnchor="middle" fill="#9a9ca0" fontFamily="var(--mono)" fontSize="10">{hm(t)}</text>)}
    </svg>
  );
}

function ClinicalResults({ episode, names }: { episode: PublicHealthEpisode; names: Map<string, { name: string }> }) {
  const results = episode.clinical_results;
  const byArea = new Map([...names].map(([zoneId, z]) => [zoneGroupId(zoneId), z.name]));
  const areaName = (code: string) => byArea.get(code) ?? code;
  return (
    <div className="card">
      <div className="card-head"><h2>Clinical test results</h2><span className="aside">from the health zone</span></div>
      {results.length === 0 ? (
        <p className="note" style={{ margin: 0 }}>No result yet. The health zone tests its daily counts against the curve this episode predicts, and sends back only the answer.</p>
      ) : (
        <div className="results">
          {results.map((r, i) => (
            <div key={i} className="result-row">
              <span>{areaName(r.area_code)} · {r.syndrome === "ag" ? "acute gastroenteritis" : r.syndrome}</span>
              <span className={`p ${r.p_value < 0.01 ? "near" : ""}`}>p = {r.p_value.toFixed(3)}</span>
              <small>{r.method.replace(/_/g, " ")} over {r.n_days} days{r.effect_size != null ? ` · effect ${r.effect_size.toFixed(2)}` : ""} · {full(r.computed_at)}.
                {r.p_value < 0.01 ? " A reason to investigate, not a conclusion." : ""}</small>
            </div>
          ))}
        </div>
      )}
      <div className="boundary" aria-label="What crosses the health boundary">
        <div className="side"><b>Health zone</b>Daily counts per area. They stay there and are never sent anywhere.</div>
        <div className="arrow">{results.length ? <>only this<br />crosses →</> : <>nothing<br />yet</>}</div>
        <div className="side"><b>Environmental system</b><span className={`wire ${results.length ? "sent" : ""}`}>
          {results.length ? "{episode_id, area_code, syndrome, method, p_value, effect_size, n_days, computed_at}" : "Nothing is sent until the test finds a matching excess."}
        </span></div>
      </div>
    </div>
  );
}

const CDS_CONDITIONS = [
  ["area", "Patient's coarse area overlaps an exposed zone", "Only the area is read, never the street address"],
  ["window", "Visit falls inside the clinical relevance window", "About 16 days from exposure"],
  ["reason", "Reason for visit is a matching syndrome", "Acute gastroenteritis, or fever after floodwater contact"],
] as const;

/** An explainer of the CDS Hooks rule (FR-31): the card appears only when all three hold. */
function CdsPreview({ episodeId }: { episodeId: string }) {
  const [on, setOn] = useState<Record<string, boolean>>({ area: true, window: true, reason: true });
  const failing = CDS_CONDITIONS.filter(([k]) => !on[k]);
  return (
    <div className="card">
      <div className="card-head"><h2>What a clinician would see</h2><span className="aside">CDS Hooks card, shown only when all three hold</span></div>
      <div className="cds">
        <div>
          {CDS_CONDITIONS.map(([k, label, hint]) => (
            <label key={k} className="switch">
              <input type="checkbox" checked={on[k]} onChange={(e) => setOn((s) => ({ ...s, [k]: e.target.checked }))} />
              <span><b>{label}</b><small>{hint}</small></span>
            </label>
          ))}
        </div>
        <div className="ehr" aria-live="polite">
          <div className="bar2"><span>EHR · patient-view</span><span>example</span></div>
          <div className="body">
            {failing.length === 0 ? (
              <div className="card-cds"><b>Recent drain contamination near this patient&apos;s area</b>
                <p>A probable sewage contamination episode affected zones near this patient&apos;s area in the last few days. For acute gastroenteritis, consider stool testing for {GI_TESTS}.</p>
                <small>{NOT_A_DIAGNOSIS} Source: Upstream episode {episodeId} (FHIR RiskAssessment).</small></div>
            ) : (
              <>
                <p className="none">No card. {failing.map(([, l]) => l.toLowerCase()).join("; ")}: not met.</p>
                <p className="none">The card only appears when all three hold, so clinicians are not interrupted by context that does not apply.</p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
