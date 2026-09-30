"use client";
// Registers the service worker and flushes the mission outbox whenever the device
// comes back online. Background Sync does the same from the worker where the browser
// supports it; both paths send the same idempotency keys, so racing is harmless.
import { useEffect } from "react";
import { flushQueue } from "@/lib/offline";

export function OfflineSync() {
  useEffect(() => {
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js").catch(() => { /* the app still works online */ });
    }
    const flush = () => { flushQueue().catch(() => {}); };
    window.addEventListener("online", flush);
    if (navigator.onLine) flush();
    return () => window.removeEventListener("online", flush);
  }, []);
  return null;
}
