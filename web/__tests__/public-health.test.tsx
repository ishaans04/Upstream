import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HealthBody } from "@/components/HealthView";
import type { PublicHealthEpisode } from "@/lib/types";
import { axe } from "./axe";
import { net, snapAt } from "./fixtures";

const ph: PublicHealthEpisode = {
  episode_id: "EE-7C31", state: "PROBABLE", opened_at: "2026-09-30T04:58:00Z",
  clinical_window_end: new Date(Date.now() + 9 * 86400000).toISOString(),
  zone_windows: snapAt(1).zone_windows, pathways: ["recreation"], notice: "Environmental context, not a diagnosis.",
  clinical_results: [{ area_code: "zone-a-population", syndrome: "ag", method: "matched_filter", p_value: 0.004,
    effect_size: 1.8, n_days: 9, computed_at: "2026-10-08T06:00:00Z" }],
};

describe("public-health view (FR-39, GC-12)", () => {
  it("carries the standing notice verbatim", () => {
    render(<HealthBody episode={ph} curves={{}} network={net} />);
    expect(screen.getByText("Environmental context, not a diagnosis.")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(/advisory decisions are made by public health officers/i);
  });

  it("never names a candidate source", () => {
    const { container } = render(<HealthBody episode={ph} curves={{}} network={net} />);
    for (const o of net.outfalls.features) {
      expect(container.textContent).not.toContain(o.properties.outfall_id + " ");
      expect(container.textContent).not.toContain(o.properties.node_id);
    }
    expect(container.textContent).not.toMatch(/outfall/i);
  });

  it("shows the exposure window and the clinical result that crossed the boundary", () => {
    render(<HealthBody episode={ph} curves={{}} network={net} />);
    expect(screen.getByRole("radio", { name: /park near/i })).toBeInTheDocument();
    expect(screen.getByText(/p = 0\.004/)).toBeInTheDocument();
    expect(screen.getByText(/a reason to investigate, not a conclusion/i)).toBeInTheDocument();
  });

  it("meets the automated accessibility rules", async () => {
    const { container } = render(<HealthBody episode={ph} curves={{}} network={net} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
