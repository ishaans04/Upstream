import type { Stream } from "./types";

// Build-time settings (NEXT_PUBLIC_* are inlined by Next). Defaults run the app
// against a local Core API through the same-origin rewrite in next.config.mjs.
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/core";
export const STREAM: Stream = process.env.NEXT_PUBLIC_STREAM === "sim" ? "sim" : "live";
export const TIME_ZONE = process.env.NEXT_PUBLIC_TZ || "Asia/Kolkata";
export const CATCHMENT = {
  name: "Barapullah drain system",
  place: "South Delhi",
  reaches: "Kushak Nallah · Barapulla Nala · South Delhi",
};
/** GC-12, verbatim. Every health-facing output carries it. */
export const NOT_A_DIAGNOSIS = "Environmental context, not a diagnosis.";
