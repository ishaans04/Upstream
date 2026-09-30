import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import bench from "@/data/bench.json";

const SUMMARY = resolve(__dirname, "../../bench/results/summary.json");

describe("benchmark numbers on the site", () => {
  it.skipIf(!existsSync(SUMMARY))("are the committed benchmark results, not a stale copy", () => {
    const src = JSON.parse(readFileSync(SUMMARY, "utf8"));
    for (const [k, v] of Object.entries(bench)) expect(src[k], k).toEqual(v);
  });
});
