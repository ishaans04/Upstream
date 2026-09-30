// NFR-9: the mission app works without signal and syncs later with correct event times.
//
// The observation's `observed_at` is stamped on the DEVICE when the strip is read and
// is never rewritten on sync -- the server supplies `recorded_at` (GC-4). The
// idempotency key is minted at the same moment and becomes the event id, so any
// number of retries (this page, the service worker, a second tab) record one event.
//
// public/sw.js drains the same IndexedDB store on a Background Sync `sync` event and
// must stay in step with `send` below; browsers without Background Sync flush from
// the page when it comes back online.
import type { components } from "./api-schema";
import { API_BASE } from "./config";
import type { MissionFeedback, MissionSubmission } from "./types";

export const DB = "upstream-outbox";
export const STORE = "outbox";
export const FAILED = "failed";
export const SYNC_TAG = "upstream-outbox";

export type Queued = MissionSubmission & { id?: number; queued_at: string };
export type Failed = Queued & { error: string; status: number };

export type Reading = {
  missionId: string;
  nodeId: string;
  method: string;
  result: "positive" | "negative";
  observerId: string;
  observedAt: Date;
};

export type SubmitOutcome = { queued: boolean; feedback?: MissionFeedback };

class Permanent extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
      req.result.createObjectStore(FAILED, { keyPath: "id" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx<T>(stores: string[], mode: IDBTransactionMode,
                     fn: (t: IDBTransaction) => IDBRequest<T> | void): Promise<T | undefined> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const t = db.transaction(stores, mode);
    const req = fn(t);
    t.oncomplete = () => { db.close(); resolve(req ? req.result : undefined); };
    t.onerror = () => { db.close(); reject(t.error); };
  });
}

export async function readQueue(): Promise<Queued[]> {
  return (await tx<Queued[]>([STORE], "readonly", (t) => t.objectStore(STORE).getAll())) ?? [];
}

export async function readFailed(): Promise<Failed[]> {
  return (await tx<Failed[]>([FAILED], "readonly", (t) => t.objectStore(FAILED).getAll())) ?? [];
}

export async function clearQueue(): Promise<void> {
  await tx([STORE, FAILED], "readwrite", (t) => { t.objectStore(STORE).clear(); t.objectStore(FAILED).clear(); });
}

async function enqueue(record: Queued): Promise<void> {
  await tx([STORE], "readwrite", (t) => t.objectStore(STORE).add(record));
}

async function registerSync(): Promise<void> {
  try {
    // getRegistration, not `ready`: `ready` never settles when no worker is registered
    // (first visit, private window, workers blocked), and the Save would hang with it.
    const reg = await navigator.serviceWorker?.getRegistration();
    await (reg as ServiceWorkerRegistration & { sync?: { register(tag: string): Promise<void> } })
      ?.sync?.register(SYNC_TAG);
  } catch { /* no Background Sync: the page flushes on `online` instead */ }
}

async function post(path: string, body: unknown): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
}

/**
 * Record the reading, then complete the mission with it. Throws TypeError when the
 * network fails (retry later) and Permanent when the server refuses (never retry).
 */
// Typed against the API's own schema (lib/api-schema.ts, generated): if the backend
// renames a field, this stops compiling instead of failing on a volunteer's phone.
type ConfirmIn = components["schemas"]["ConfirmIn"];
type CompleteIn = components["schemas"]["CompleteIn"];

async function send(r: MissionSubmission): Promise<MissionFeedback> {
  const body: ConfirmIn = {
    node_id: r.node_id, observed_at: r.observed_at, method: r.method as ConfirmIn["method"],
    result: r.result, observer_id: r.observer_id, observer_type: "citizen", snap_distance_m: 0,
    confirmed_by_observer: true, mission_id: r.mission_id, idempotency_key: r.idempotency_key,
  };
  const confirm = await post("/ingest/report/confirm", body);
  if (confirm.status >= 500) throw new TypeError(`server error ${confirm.status}`);
  if (!confirm.ok) throw new Permanent(confirm.status, await confirm.text());
  const { event_id } = await confirm.json();

  const mid = encodeURIComponent(r.mission_id);
  const complete: CompleteIn = { evidence_event_id: event_id };
  const done = await post(`/missions/${mid}/complete`, complete);
  if (done.status >= 500) throw new TypeError(`server error ${done.status}`);
  if (done.ok) return done.json();
  if (done.status === 409) {
    // Completed already: an earlier attempt got through and only its answer was lost.
    const m = await fetch(`${API_BASE}/missions/${mid}`);
    if (m.ok && (await m.json()).status === "completed") {
      const fb = await fetch(`${API_BASE}/missions/${mid}/feedback`);
      if (fb.ok) return fb.json();
    }
  }
  throw new Permanent(done.status, await done.text());
}

export async function submitMission(missionId: string, reading: Reading): Promise<SubmitOutcome> {
  const record: Queued = {
    mission_id: missionId, node_id: reading.nodeId, method: reading.method, result: reading.result,
    observer_id: reading.observerId,
    observed_at: reading.observedAt.toISOString(),          // the device's clock, once
    idempotency_key: crypto.randomUUID(),
    queued_at: new Date().toISOString(),
  };
  if (!navigator.onLine) {
    await enqueue(record);
    await registerSync();
    return { queued: true };
  }
  try {
    return { queued: false, feedback: await send(record) };
  } catch (e) {
    if (e instanceof Permanent) throw e;
    await enqueue(record);
    await registerSync();
    return { queued: true };
  }
}

let flushing: Promise<number> | null = null;

/** Send everything queued, oldest first. Returns how many went through. */
export function flushQueue(): Promise<number> {
  flushing ??= (async () => {
    let sent = 0;
    try {
      for (const record of await readQueue()) {
        try {
          await send(record);
        } catch (e) {
          if (!(e instanceof Permanent)) break;              // offline again: keep the rest, in order
          await tx([STORE, FAILED], "readwrite", (t) => {
            t.objectStore(STORE).delete(record.id!);
            t.objectStore(FAILED).put({ ...record, error: e.message, status: e.status });
          });
          continue;
        }
        await tx([STORE], "readwrite", (t) => t.objectStore(STORE).delete(record.id!));
        sent += 1;
      }
    } finally {
      flushing = null;
    }
    return sent;
  })();
  return flushing;
}
