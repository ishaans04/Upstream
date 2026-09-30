import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Console } from "@/components/Console";
import type { TimelinePoint } from "@/lib/types";
import { axe } from "./axe";
import { episode, net, snapshots, timeline } from "./fixtures";

const twoSnapshots = timeline;
const loadSnapshot = vi.fn(async (p: TimelinePoint) => snapshots.find((s) => s.fingerprint === p.fingerprint)!);

function renderConsole() {
  return render(<Console network={net} episode={episode} timeline={twoSnapshots} loadSnapshot={loadSnapshot} />);
}

describe("Console and belief replay (FR-36, FR-37)", () => {
  it("shows the belief as of the slider position, not the latest", async () => {
    renderConsole();
    expect(await screen.findByText("90%")).toBeInTheDocument();         // the latest p_event
    fireEvent.change(screen.getByRole("slider"), { target: { value: "0" } });
    expect(await screen.findByText(/62%/)).toBeInTheDocument();          // the earlier p_event
    expect(screen.getByText(/viewing a past belief/i)).toBeInTheDocument();
    expect(screen.getByText("sha256:aaaa1111")).toBeInTheDocument();
  });

  it("labels the slider for screen readers with the timestamp it is showing", async () => {
    renderConsole();
    await screen.findByText("90%");
    expect(screen.getByRole("slider")).toHaveAccessibleName(/showing belief at/i);
  });

  it("explains each top candidate with the observations that supported it", async () => {
    renderConsole();
    await screen.findByText("90%");
    expect(screen.getByText(/supported by/i)).toBeInTheDocument();
    expect(screen.getByText(/eliminated rivals/i)).toBeInTheDocument();
  });

  it("shows negative evidence distinctly from positive evidence", async () => {
    renderConsole();
    await screen.findByText("90%");
    fireEvent.click(screen.getByRole("button", { name: /evidence/i }));
    const dialog = screen.getByRole("dialog", { name: /evidence log/i });
    const neg = within(dialog).getByTestId("evidence-negative");
    expect(neg).toHaveAccessibleDescription(/checked.*normal/i);
    expect(within(dialog).getAllByTestId("evidence-positive")[0]).toHaveAccessibleDescription(/contamination seen/i);
  });

  it("shows retracted evidence struck through, never hidden", async () => {
    renderConsole();
    await screen.findByText("90%");
    fireEvent.click(screen.getByRole("button", { name: /evidence/i }));
    const row = screen.getByTestId("evidence-retracted");
    expect(row.querySelector(".what")).toHaveClass("line-through");
    expect(row).toHaveTextContent(/withdrawn: reported the wrong drain/i);
  });

  it("displays the fingerprint so a judge can verify reproducibility", async () => {
    renderConsole();
    expect(await screen.findByText(/sha256:/)).toBeInTheDocument();
  });

  it("closes the evidence log with Escape and returns focus to what opened it", async () => {
    renderConsole();
    await screen.findByText("90%");
    const opener = screen.getByRole("button", { name: /evidence/i });
    fireEvent.click(opener);
    fireEvent.keyDown(document, { key: "Escape" });
    await act(async () => { await new Promise((r) => setTimeout(r, 260)); });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("meets the automated accessibility rules", async () => {
    const { container } = renderConsole();
    await screen.findByText("90%");
    // NFR-10 / GC-14. jsdom cannot compute colour contrast; e2e/a11y.spec.ts checks
    // that in a real browser on every route.
    expect(await axe(container)).toHaveNoViolations();
  });
});
