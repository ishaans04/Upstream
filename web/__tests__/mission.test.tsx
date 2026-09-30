import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MissionFlow } from "@/components/MissionFlow";
import type { Mission } from "@/lib/types";
import { axe } from "./axe";

const soon = (min: number) => new Date(Date.now() + min * 60_000).toISOString();

const mission = (over: Partial<Mission> = {}): Mission => ({
  mission_id: "M-7F2A", episode_id: "EE-7C31", node_id: "N00412", window_start: soon(-10), window_end: soon(50),
  methods: ["test_strip", "citizen_visual_olfactory"], mode: "protect", status: "created", assignee_id: "vol-sim-03",
  realised_gain: null, stream: "sim", walk_cost_s: 540, lon: 77.23, lat: 28.58, summary: "",
  expected_effect: "Expected to rule out about 2 of 3 warning patterns (41% of the remaining uncertainty).", ...over,
});

const actions = () => ({
  accept: vi.fn(async () => ({ mission_id: "M-7F2A", status: "accepted" })),
  submit: vi.fn(async () => ({ queued: false, feedback: {
    mission_id: "M-7F2A", status: "completed", realised_gain: 0.2, sources_before: 3, sources_after: 1,
    effect: "Your sample ruled out 2 of 3 possible sources. 1 remain." } })),
  feedback: vi.fn(async () => ({ mission_id: "M-7F2A", status: "completed", realised_gain: 0.2, sources_before: 3,
    sources_after: 1, effect: "Your sample ruled out 2 of 3 possible sources. 1 remain." })),
});

describe("the mission app (FR-38, G7)", () => {
  it("shows the mission's expected effect before the volunteer accepts", () => {
    render(<MissionFlow mission={mission()} volunteerId="vol-sim-03" actions={actions()} />);
    expect(screen.getByText(/expected to rule out/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /accept mission/i })).toBeEnabled();
  });

  it("shows the measured effect after completion", async () => {
    const a = actions();
    render(<MissionFlow mission={mission()} volunteerId="vol-sim-03" actions={a} />);
    fireEvent.click(screen.getByRole("button", { name: /accept mission/i }));
    fireEvent.click(await screen.findByRole("radio", { name: /looked normal/i }));
    fireEvent.click(screen.getByRole("button", { name: /save reading/i }));
    // G7: "your sample eliminated two of three suspects", in the backend's own words.
    expect(await screen.findByText(/your (check|sample) ruled out/i)).toBeInTheDocument();
    const [id, reading] = a.submit.mock.calls[0] as unknown as [string, { observedAt: Date; result: string; method: string }];
    expect(id).toBe("M-7F2A");
    expect(reading.result).toBe("negative");
    expect(reading.method).toBe("test_strip");
    expect(Math.abs(reading.observedAt.getTime() - Date.now())).toBeLessThan(5000);
  });

  it("keeps asking until the effect has been measured", async () => {
    // The phone completes before the kernel has recomputed; the first answer is pending.
    const a = actions();
    a.submit.mockResolvedValueOnce({ queued: false, feedback: {
      mission_id: "M-7F2A", status: "completed", realised_gain: null, sources_before: null, sources_after: null,
      effect: "Recorded. The effect will show once the belief has been recomputed with it." } } as never);
    render(<MissionFlow mission={mission({ status: "accepted" })} volunteerId="vol-sim-03" actions={a} pollMs={10} />);
    fireEvent.click(screen.getByRole("radio", { name: /looked normal/i }));
    fireEvent.click(screen.getByRole("button", { name: /save reading/i }));
    expect(await screen.findByText(/your sample ruled out 2 of 3/i)).toBeInTheDocument();
    expect(a.feedback).toHaveBeenCalled();
  });

  it("moves on from 'waiting for signal' once the queued reading has been sent", async () => {
    const a = actions();
    a.submit.mockResolvedValueOnce({ queued: true } as never);
    // While offline the mission is not completed yet; after the outbox drains it is.
    a.feedback.mockResolvedValueOnce({ mission_id: "M-7F2A", status: "accepted", realised_gain: null,
      sources_before: null, sources_after: null, effect: "This mission has not been completed yet." } as never);
    render(<MissionFlow mission={mission({ status: "accepted" })} volunteerId="vol-sim-03" actions={a} pollMs={10} />);
    fireEvent.click(screen.getByRole("radio", { name: /looked normal/i }));
    fireEvent.click(screen.getByRole("button", { name: /save reading/i }));
    expect(await screen.findByText(/saved on this phone/i)).toBeInTheDocument();
    expect(await screen.findByText(/your sample ruled out 2 of 3/i)).toBeInTheDocument();
  });

  it("tells the volunteer a reading made without signal is kept, not lost", async () => {
    const a = actions();
    a.submit.mockResolvedValueOnce({ queued: true } as never);
    render(<MissionFlow mission={mission({ status: "accepted" })} volunteerId="vol-sim-03" actions={a} />);
    fireEvent.click(screen.getByRole("radio", { name: /contamination/i }));
    fireEvent.click(screen.getByRole("button", { name: /save reading/i }));
    expect(await screen.findByText(/saved on this phone/i)).toBeInTheDocument();
  });

  it("refuses to show a mission whose safety window has closed", () => {
    render(<MissionFlow mission={mission({ window_start: soon(-90), window_end: soon(-5) })} volunteerId="vol-sim-03" actions={actions()} />);
    expect(screen.getByText(/safe window.*has closed/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /accept mission/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/expected to rule out/i)).not.toBeInTheDocument();
  });

  it("will not let someone else's mission be taken", () => {
    render(<MissionFlow mission={mission({ assignee_id: "vol-sim-09" })} volunteerId="vol-sim-03" actions={actions()} />);
    expect(screen.getByText(/offered to another volunteer/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /accept mission/i })).not.toBeInTheDocument();
  });

  it("meets the automated accessibility rules", async () => {
    const { container } = render(<MissionFlow mission={mission()} volunteerId="vol-sim-03" actions={actions()} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
