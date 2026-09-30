import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearQueue, flushQueue, readFailed, readQueue, submitMission } from "@/lib/offline";

// A fake Core API that behaves like the real one: an idempotency key that arrives
// twice is recorded once (services/core-api/.../ingest/routes.py), and completing a
// mission twice is a 409.
function fakeApi() {
  const events = new Map<string, { observed_at: string; mission_id: string }>();
  const completed = new Set<string>();
  const calls: string[] = [];
  let failNext: string | null = null;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace(/^\/api\/core/, "").split("?")[0];
    calls.push(`${init?.method ?? "GET"} ${path}`);
    if (failNext && path.includes(failNext)) { failNext = null; throw new TypeError("Failed to fetch"); }
    if (path === "/ingest/report/confirm") {
      const body = JSON.parse(String(init!.body));
      const again = events.has(body.idempotency_key);
      events.set(body.idempotency_key, body);
      return json({ seq: events.size, event_id: body.idempotency_key }, again ? 200 : 201);
    }
    const done = /^\/missions\/([^/]+)\/complete$/.exec(path);
    if (done) {
      if (completed.has(done[1])) return json({ detail: "mission is completed" }, 409);
      completed.add(done[1]);
      return json({ mission_id: done[1], status: "completed", effect: "Your sample ruled out 2 of 3 possible sources. 1 remain." });
    }
    const one = /^\/missions\/([^/]+)$/.exec(path);
    if (one) return json({ mission_id: one[1], status: completed.has(one[1]) ? "completed" : "accepted" });
    const fb = /^\/missions\/([^/]+)\/feedback$/.exec(path);
    if (fb) return json({ mission_id: fb[1], status: "completed", effect: "Your sample ruled out 2 of 3 possible sources. 1 remain." });
    if (path.startsWith("/missions/M-GONE")) return json({ detail: "gone" }, 404);
    return json({ detail: "not found" }, 404);
  });
  return { fetchMock, events, calls, failOn: (p: string) => { failNext = p; } };
}
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let online = true;
beforeEach(async () => {
  online = true;
  Object.defineProperty(navigator, "onLine", { configurable: true, get: () => online });
  await clearQueue();
});

const reading = (mission: string, at: Date) => ({
  nodeId: "N00412", method: "test_strip", result: "negative" as const, observerId: "vol-sim-03",
  observedAt: at, missionId: mission,
});

describe("offline mission submission (NFR-9)", () => {
  it("queues a submission when offline and keeps the original observed_at", async () => {
    const api = fakeApi();
    vi.stubGlobal("fetch", api.fetchMock);
    online = false;
    const observedAt = new Date("2026-09-30T05:41:17.250Z");
    const out = await submitMission("M-1", reading("M-1", observedAt));
    expect(out.queued).toBe(true);
    expect(api.fetchMock).not.toHaveBeenCalled();
    const [q] = await readQueue();
    expect(q.observed_at).toBe(observedAt.toISOString());                       // GC-4
  });

  it("saves offline even when no service worker is registered", async () => {
    // `serviceWorker.ready` never settles without a registration (first visit, private
    // window, workers blocked): awaiting it left the volunteer's Save hanging forever.
    const api = fakeApi();
    vi.stubGlobal("fetch", api.fetchMock);
    Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: {
      ready: new Promise(() => {}), getRegistration: async () => undefined } });
    try {
      online = false;
      const out = await submitMission("M-1", reading("M-1", new Date("2026-09-30T05:41:00Z")));
      expect(out.queued).toBe(true);
      expect(await readQueue()).toHaveLength(1);
    } finally {
      delete (navigator as { serviceWorker?: unknown }).serviceWorker;
    }
  }, 2000);

  it("flushes the queue in order when connectivity returns", async () => {
    const api = fakeApi();
    vi.stubGlobal("fetch", api.fetchMock);
    online = false;
    await submitMission("M-1", reading("M-1", new Date("2026-09-30T05:40:00Z")));
    await submitMission("M-2", reading("M-2", new Date("2026-09-30T05:55:00Z")));
    online = true;
    const sent = await flushQueue();
    expect(sent).toBe(2);
    expect(api.calls.filter((c) => c.endsWith("/complete"))).toEqual([
      "POST /missions/M-1/complete", "POST /missions/M-2/complete"]);
    expect(await readQueue()).toEqual([]);
    // The server received the time the strip was read, not the time it was sent.
    expect([...api.events.values()].map((e) => e.observed_at)).toEqual([
      "2026-09-30T05:40:00.000Z", "2026-09-30T05:55:00.000Z"]);
  });

  it("does not double-submit after a retry", async () => {
    const api = fakeApi();
    vi.stubGlobal("fetch", api.fetchMock);
    // The confirmation lands but the completion is lost on the way: the phone cannot
    // tell, so it queues the whole submission and sends it again later.
    api.failOn("/complete");
    const first = await submitMission("M-1", reading("M-1", new Date()));
    expect(first.queued).toBe(true);
    await flushQueue();
    expect(api.calls.filter((c) => c === "POST /ingest/report/confirm")).toHaveLength(2);
    expect(api.events.size).toBe(1);                       // same key both times: one event
    expect(await readQueue()).toEqual([]);
  });

  it("treats an already-completed mission as done rather than retrying forever", async () => {
    const api = fakeApi();
    vi.stubGlobal("fetch", api.fetchMock);
    await submitMission("M-1", reading("M-1", new Date()));
    // The mission was completed from another tab; this reading still lands as evidence
    // and the phone shows the recorded effect instead of queueing a 409 for ever.
    await clearQueue();
    const out = await submitMission("M-1", { ...reading("M-1", new Date()) });
    expect(out.queued).toBe(false);
    expect(out.feedback?.effect).toMatch(/ruled out/);
  });

  it("does not let a permanently refused record block the ones behind it", async () => {
    const api = fakeApi();
    vi.stubGlobal("fetch", api.fetchMock);
    online = false;
    await submitMission("M-GONE", reading("M-GONE", new Date()));
    await submitMission("M-2", reading("M-2", new Date()));
    online = true;
    api.fetchMock.mockImplementationOnce(async () => json({ detail: "no such mission: M-GONE" }, 404));
    await flushQueue();
    expect(await readQueue()).toEqual([]);
    expect((await readFailed()).map((r) => r.mission_id)).toEqual(["M-GONE"]);
    expect(api.calls).toContain("POST /missions/M-2/complete");
  });
});
