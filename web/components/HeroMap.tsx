"use client";
// The landing page's map: the real network with the latest stored belief, if any.
import { getNetwork, getReplay } from "@/lib/api";
import { NetworkMap } from "./NetworkMap";
import { useLoad } from "./useLoad";

export function HeroMap() {
  const r = useLoad(async () => {
    const network = await getNetwork();
    const snapshot = await getReplay(new Date()).catch(() => null);      // 404 until something is believed
    return { network, snapshot };
  }, []);
  const n = r.data?.network;
  return (
    <figure className="hero-map" style={{ margin: 0 }}>
      {n ? <NetworkMap network={n} snapshot={r.data!.snapshot} evidence={[]} mode="hero" />
        : <div className="deck-box deck-hero" role="img" aria-label="The drain network is loading" />}
      <figcaption className="cap">
        <span className="mono">{n ? `${n.edges.features.length} drain reaches · ${n.outfalls.features.length} outfalls · ${n.zones.features.length} zones` : r.error ? "network unavailable" : "loading the network…"}</span>
        <span className="mono">© OpenStreetMap contributors</span>
      </figcaption>
    </figure>
  );
}
