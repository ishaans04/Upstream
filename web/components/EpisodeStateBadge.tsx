import { STATE_LABEL } from "@/lib/belief";
import type { EpisodeState } from "@/lib/types";

const CLASS: Record<string, string> = {
  PROBABLE: "b-probable", CONFIRMED: "b-probable", SUSPECTED: "b-suspected",
};

/** The episode's recorded lifecycle state (FR-20), as the workflow wrote it. */
export function EpisodeStateBadge({ state }: { state: EpisodeState }) {
  return (
    <span className={`badge ${CLASS[state] ?? "b-quiet"}`} style={{ marginLeft: 10, verticalAlign: "middle" }}>
      <span className="sr-only">State: </span>{STATE_LABEL[state] ?? state}
    </span>
  );
}
