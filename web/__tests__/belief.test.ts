import { describe, expect, it } from "vitest";
import {
  corridor, evidenceAsOf, exposureColour, givenEvent, rankedSources, zoneStatus,
} from "@/lib/belief";
import { net, snapAt, evidence } from "./fixtures";

describe("source ranking", () => {
  it("ranks outfalls by probability given that something is happening", () => {
    const s = snapAt(1);
    expect(rankedSources(s, net)[0]).toBe("N2");
    // 0.54 of a 0.9 event is 60% given the event, not 54%.
    expect(givenEvent(s, "N2")).toBeCloseTo(0.6, 6);
  });

  it("never ranks the pseudo-sources as outfalls", () => {
    expect(rankedSources(snapAt(1), net)).not.toContain("__none__");
    expect(rankedSources(snapAt(1), net)).not.toContain("__diffuse__");
  });
});

describe("corridor", () => {
  it("carries each outfall's probability down its path to the outlet", () => {
    const w = corridor(snapAt(1), net);
    // N2 -> J1 -> OUT: both edges on N2's path carry its share, the N1 edge does not.
    expect(w.get("e2")).toBeCloseTo(0.6, 6);
    expect(w.get("e3")).toBeCloseTo(1.0, 6);
    expect(w.get("e1")).toBeCloseTo(0.4, 6);
  });

  it("colours a more probable reach more strongly", () => {
    const [, , , faint] = exposureColour(0.05);
    const [, , , strong] = exposureColour(0.9);
    expect(strong).toBeGreaterThan(faint);
  });
});

describe("zones (PRD 14.4 equity safeguard)", () => {
  it("marks a zone with an exposure window as exposed", () => {
    expect(zoneStatus(net.zones.features[0].properties, snapAt(1), [], net)).toBe("exposed");
  });

  it("calls a zone with no nearby evidence 'no data', never clean", () => {
    const far = net.zones.features[1].properties;
    expect(zoneStatus(far, snapAt(1), [], net)).toBe("no-data");
  });

  it("calls it clear only when evidence near it says so", () => {
    const far = net.zones.features[1].properties;
    const checked = [{ node_id: "Z2N", result: "negative" as const }];
    expect(zoneStatus(far, snapAt(1), checked, net)).toBe("clear");
  });
});

describe("evidence as of a past belief (FR-37)", () => {
  it("shows only what the belief was built from", () => {
    const rows = evidenceAsOf(evidence, 11);
    expect(rows.map((r) => r.event_id)).toEqual(["ev-1", "ev-2"]);
  });

  it("keeps a retracted report, marked, once the retraction is in the log", () => {
    expect(evidenceAsOf(evidence, 11).find((r) => r.event_id === "ev-1")?.retracted).toBe(false);
    const later = evidenceAsOf(evidence, 14);
    expect(later.find((r) => r.event_id === "ev-1")?.retracted).toBe(true);
    expect(later).toHaveLength(3);
  });
});

describe("area codes", () => {
  it("match upstream_shared.ids.zone_group_id", async () => {
    const { zoneGroupId } = await import("@/lib/places");
    expect(zoneGroupId("ZONE_000")).toBe("zone-000-population");
    expect(zoneGroupId("ZONE_OVR_001")).toBe("zone-ovr-001-population");
    expect(zoneGroupId("A")).toBe("zone-a-population");
  });
});
