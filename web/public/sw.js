// Upstream service worker (NFR-9): keep the mission app usable without signal.
//
// * The app shell and the basemap are cached, so the mission pages open offline.
// * API reads are network-first with the last good answer as the fallback.
// * Queued mission readings (lib/offline.ts writes them to IndexedDB) are sent on a
//   Background Sync event, oldest first, with the idempotency key minted on the phone,
//   so a retry here and a flush from the page cannot record the same reading twice.
//   `send` below must stay in step with `send` in lib/offline.ts.
const VERSION = "upstream-v1";
const SHELL = ["/missions", "/basemap.json", "/icon.svg", "/manifest.webmanifest"];
const DB = "upstream-outbox", STORE = "outbox", FAILED = "failed", TAG = "upstream-outbox";
const API = "/api/core";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function networkFirst(req) {
  const cache = await caches.open(VERSION);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(req, { ignoreSearch: req.mode === "navigate" });
    if (hit) return hit;
    if (req.mode === "navigate") {
      const shell = await cache.match("/missions");
      if (shell) return shell;
    }
    throw err;
  }
}

async function cacheFirst(req) {
  const cache = await caches.open(VERSION);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) cache.put(req, res.clone());
  return res;
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/_next/static/") || url.pathname === "/basemap.json" || url.pathname.startsWith("/_next/static/media/")) {
    e.respondWith(cacheFirst(req));
  } else if (req.mode === "navigate" || url.pathname.startsWith(API + "/missions") || url.pathname.startsWith(API + "/network")) {
    e.respondWith(networkFirst(req));
  }
});

// ---- the outbox -------------------------------------------------------------------

function openDb() {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => {
      r.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
      r.result.createObjectStore(FAILED, { keyPath: "id" });
    };
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

function run(db, stores, mode, fn) {
  return new Promise((resolve, reject) => {
    const t = db.transaction(stores, mode);
    const req = fn(t);
    t.oncomplete = () => resolve(req ? req.result : undefined);
    t.onerror = () => reject(t.error);
  });
}

class Permanent extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

const post = (path, body) => fetch(API + path, {
  method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(body),
});

async function send(r) {
  const confirm = await post("/ingest/report/confirm", {
    node_id: r.node_id, observed_at: r.observed_at, method: r.method, result: r.result,
    observer_id: r.observer_id, observer_type: "citizen", snap_distance_m: 0,
    confirmed_by_observer: true, mission_id: r.mission_id, idempotency_key: r.idempotency_key,
  });
  if (confirm.status >= 500) throw new TypeError("server error " + confirm.status);
  if (!confirm.ok) throw new Permanent(confirm.status, await confirm.text());
  const { event_id } = await confirm.json();
  const mid = encodeURIComponent(r.mission_id);
  const done = await post(`/missions/${mid}/complete`, { evidence_event_id: event_id });
  if (done.status >= 500) throw new TypeError("server error " + done.status);
  if (done.ok) return;
  if (done.status === 409) {
    const m = await fetch(`${API}/missions/${mid}`);
    if (m.ok && (await m.json()).status === "completed") return;
  }
  throw new Permanent(done.status, await done.text());
}

async function drain() {
  const db = await openDb();
  const queued = await run(db, [STORE], "readonly", (t) => t.objectStore(STORE).getAll());
  for (const record of queued) {
    try {
      await send(record);
    } catch (e) {
      if (!(e instanceof Permanent)) throw e;             // still offline: let the browser retry the sync
      await run(db, [STORE, FAILED], "readwrite", (t) => {
        t.objectStore(STORE).delete(record.id);
        t.objectStore(FAILED).put({ ...record, error: e.message, status: e.status });
      });
      continue;
    }
    await run(db, [STORE], "readwrite", (t) => t.objectStore(STORE).delete(record.id));
  }
  db.close();
  const clients = await self.clients.matchAll();
  clients.forEach((c) => c.postMessage({ type: "outbox-drained" }));
}

self.addEventListener("sync", (e) => {
  if (e.tag === TAG) e.waitUntil(drain());
});

// Web push for new missions (Phase 6 sends them).
self.addEventListener("push", (e) => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch { data = { body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(data.title || "Upstream mission nearby", {
    body: data.body || "", icon: "/icon.svg", data: { url: data.url || "/missions" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(self.clients.openWindow(e.notification.data && e.notification.data.url ? e.notification.data.url : "/missions"));
});
