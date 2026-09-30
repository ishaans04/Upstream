import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NetworkMap, reachData } from "@/components/NetworkMap";
import { evidenceAsOf } from "@/lib/belief";
import { evidence, net, snapAt } from "./fixtures";

const netWithSynthetic = net;
const snap = snapAt(1);
const seen = evidenceAsOf(evidence, snap.as_of_seq);

describe("NetworkMap", () => {
  it("renders every outfall with a probability label", () => {
    render(<NetworkMap network={net} snapshot={snap} evidence={seen} />);
    const table = screen.getByRole("list", { name: /outfalls/i });
    expect(within(table).getByText(/O1\b.*40%/)).toBeInTheDocument();
    expect(within(table).getByText(/O2\b.*60%/)).toBeInTheDocument();
  });

  it("marks synthetic outfalls with a visible badge", () => {
    render(<NetworkMap network={netWithSynthetic} snapshot={snap} evidence={seen} />);
    // Exactly the one synthetic outfall in the fixture, and it is not hidden from view.
    const badges = screen.getAllByLabelText(/synthetic \(illustrative\) outfall/i);
    expect(badges).toHaveLength(1);
    expect(badges[0]).toBeVisible();
    expect(badges[0]).toHaveTextContent("SYNTHETIC");
  });

  it("shows sparse areas as uncertain, not clean", () => {
    // PRD 14.4 equity safeguard
    render(<NetworkMap network={net} snapshot={snap} evidence={seen} />);
    expect(screen.getByTestId("zone-no-data")).toHaveTextContent(/not enough evidence/i);
    expect(screen.queryByText(/no exposure expected/i)).not.toBeInTheDocument();
  });

  it("colours edges by exposure probability at the selected time", () => {
    const early = new Map(reachData(net, snapAt(0)).map((r) => [r.edge_id, r]));
    const late = new Map(reachData(net, snapAt(1)).map((r) => [r.edge_id, r]));
    // Belief moved from O1 (60%) to O2 (60%): the O2 reach warms, the O1 reach cools.
    expect(late.get("e2")!.colour[3]).toBeGreaterThan(early.get("e2")!.colour[3]);
    expect(late.get("e1")!.colour[3]).toBeLessThan(early.get("e1")!.colour[3]);
    // The shared reach below the junction carries both, so it is the strongest.
    expect(late.get("e3")!.p).toBeCloseTo(1, 6);
  });

  it("has an accessible name for every interactive map control", () => {
    render(<NetworkMap network={net} snapshot={snap} evidence={seen} />);
    const toolbar = screen.getByRole("toolbar", { name: /map view/i });
    const buttons = within(toolbar).getAllByRole("button");
    expect(buttons.length).toBeGreaterThanOrEqual(6);
    for (const b of buttons) expect(b).toHaveAccessibleName();
    const tilt = within(toolbar).getByRole("button", { name: /3D and flat/i });
    expect(tilt).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(tilt);
    expect(tilt).toHaveAttribute("aria-pressed", "false");
  });

  it("says plainly when the 3D view cannot draw, rather than showing an empty box", () => {
    render(<NetworkMap network={net} snapshot={snap} evidence={seen} />);
    expect(screen.getByText(/needs WebGL/i)).toBeInTheDocument();
  });
});
