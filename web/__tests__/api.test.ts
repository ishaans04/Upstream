import { afterEach, describe, expect, it, vi } from "vitest";
import { getReplay } from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());

describe("belief replay client (FR-37)", () => {
  it("asks for a snapshot at its own timestamp, to the microsecond", async () => {
    // The API stores microseconds; a JS Date keeps milliseconds. Rounding the stored
    // moment down asked for the instant *before* the snapshot, so every replay point
    // showed the previous belief and the first one was a 404.
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await getReplay("2026-09-30T06:13:03.300453+00:00", "sim");
    const url = new URL(String((fetchMock.mock.calls[0] as unknown[])[0]), "http://x");
    expect(url.searchParams.get("at")).toBe("2026-09-30T06:13:03.300453+00:00");
  });

  it("still accepts a Date", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await getReplay(new Date("2026-09-30T06:13:03.300Z"), "sim");
    const url = new URL(String((fetchMock.mock.calls[0] as unknown[])[0]), "http://x");
    expect(url.searchParams.get("at")).toBe("2026-09-30T06:13:03.300Z");
  });
});
