// PRD R2: an invented outfall must never look like a surveyed one. No public register of
// outfalls exists for these drains, so every location is illustrative and says so.
export function SyntheticBadge() {
  return (
    <span className="synthetic" aria-label="Synthetic (illustrative) outfall location"
          title="Synthetic (illustrative) outfall location: no public register exists for these drains">
      SYNTHETIC
    </span>
  );
}
