"""PRD 7.7: misconnections and overflows recur at the same place. Pool closed episodes.

A single citizen-driven episode may leave the source unclear. Across episodes, a point
that keeps appearing near the top of the ranking is probably a recurring source, even
when no one episode was conclusive.

The model. Either there is a recurring source R at some entry point, or there is none.
Each closed episode came from R with probability RHO, and otherwise from the ordinary
background of sources (the prior pi). With p_i the episode's final belief over entry
points, conditioned on an event, the likelihood of episode i under "R = k", relative to
"no recurring source", is

    RHO * p_i(k) / pi(k) + (1 - RHO)

so P(R = k | episodes) is proportional to (1 - Q) pi(k) prod_i [that], and
P(no recurring source) to Q.

Why not the plan's sum of per-episode log-odds (a product of posteriors): it counts the
prior once per episode, and a single episode elsewhere puts ~0 on k and erases a source
that recurred ten times. Under the mixture that episode costs k a factor of 1 - RHO,
which is what one unrelated incident should cost.

`pi` is the type-driven base rate, normalised. The episodes' own priors also carried
rainfall and history; dividing by the base rate alone is an approximation, and says so.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

RHO = 0.5                   # chance a given episode came from the recurring source
Q_NONE = 0.5                # prior that there is no recurring source at all
MIN_EPISODES = 2            # one episode is an incident, not a pattern
IMPLICATED_AT = 0.2         # an episode "implicates" a point it gave at least this
REPORT_AT = 0.2             # pooled probability worth an inspection
CLOSED_STATES = ("CONFIRMED", "RESOLVED")   # REFUTED: nothing happened; says nothing


@dataclass(frozen=True)
class ClosedEpisode:
    episode_id: str
    opened_at: dt.datetime
    marginals: dict[str, float]            # the belief it closed on, pseudo-sources included

    def event_marginals(self) -> dict[str, float]:
        """Belief over real entry points, given that something happened."""
        pts = {k: float(v) for k, v in self.marginals.items() if not k.startswith("__")}
        total = sum(pts.values())
        return {k: v / total for k, v in pts.items()} if total > 0 else {}


@dataclass(frozen=True)
class RecurringSource:
    entry_id: str
    source_type: str
    episode_count: int
    pooled_probability: float
    first_seen: dt.datetime
    last_seen: dt.datetime
    evidence_episode_ids: list[str]
    suggested_action: str


def _base_prior(net) -> np.ndarray:
    base = np.asarray(net.entry_base_rate, dtype=np.float64)
    return base / base.sum()


def pool_episodes(episodes: list[ClosedEpisode], net, *,
                  labels: dict[str, str] | None = None) -> list[RecurringSource]:
    """Recurring sources worth inspecting, likeliest first. Pure; no I/O.

    `labels` maps an entry node to the name an officer knows it by (the outfall id).
    """
    labels = labels or {}
    if len(episodes) < MIN_EPISODES:
        return []
    entries = list(net.entry_nodes)
    pi = _base_prior(net)
    beliefs = [e.event_marginals() for e in episodes]
    P = np.array([[b.get(k, 0.0) for k in entries] for b in beliefs])      # (N, K)

    log_like = np.log(RHO * P / pi + (1.0 - RHO)).sum(axis=0)             # (K,)
    log_w = np.concatenate([[np.log(Q_NONE)], np.log(1.0 - Q_NONE) + np.log(pi) + log_like])
    post = np.exp(log_w - log_w.max())
    post /= post.sum()
    pooled = post[1:]

    out = []
    for k, entry_id in enumerate(entries):
        implicating = [e for e, b in zip(episodes, beliefs, strict=True)
                       if b.get(entry_id, 0.0) >= IMPLICATED_AT]
        if pooled[k] < REPORT_AT or len(implicating) < MIN_EPISODES:
            continue
        stype = net.entry_source_type[k]
        out.append(RecurringSource(
            entry_id=entry_id, source_type=stype, episode_count=len(implicating),
            pooled_probability=float(pooled[k]),
            first_seen=min(e.opened_at for e in implicating),
            last_seen=max(e.opened_at for e in implicating),
            evidence_episode_ids=[e.episode_id for e in implicating],
            # GC-12 / PRD 14.4: a place to look, never a party to blame.
            suggested_action=(f"Inspect {labels.get(entry_id, entry_id)} "
                              f"({stype.replace('_', ' ')}) for a "
                              f"recurring discharge: it was implicated in {len(implicating)} "
                              f"closed episodes. Consider it for a restoration measure.")))
    return sorted(out, key=lambda r: -r.pooled_probability)


def past_episode_counts(episodes: list[ClosedEpisode], net) -> np.ndarray:
    """Expected number of past episodes from each entry point (PriorInputs, role 3).

    Soft counts: an episode that closed 60/40 between two points adds 0.6 and 0.4,
    rather than a whole episode to its top source and nothing to the runner-up.
    """
    index = {k: i for i, k in enumerate(net.entry_nodes)}
    counts = np.zeros(len(index), dtype=np.float64)
    for e in episodes:
        for k, p in e.event_marginals().items():
            if k in index:
                counts[index[k]] += p
    return counts


def closed_episodes(conn, catchment_id: str, stream: str, *,
                    since_days: int = 365) -> list[ClosedEpisode]:
    """Closed episodes of one catchment and stream, each with the belief it closed on.

    Scoped to the stream on purpose: a simulated episode must never shape live
    priors (GC-10). Readable by kernel_role (SELECT on episodes and snapshots).
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.episode_id, e.opened_at, s.source_marginals
            FROM episodes e
            JOIN LATERAL (SELECT source_marginals FROM posterior_snapshots p
                          WHERE p.fingerprint = e.latest_fingerprint
                            AND p.catchment_id = e.catchment_id AND p.stream = e.stream
                          ORDER BY p.ts DESC LIMIT 1) s ON TRUE
            WHERE e.catchment_id = %s AND e.stream = %s AND e.state = ANY(%s)
              AND e.opened_at > now() - make_interval(days => %s)
            ORDER BY e.opened_at""",
                    (catchment_id, stream, list(CLOSED_STATES), since_days))
        return [ClosedEpisode(r[0], r[1], dict(r[2] or {})) for r in cur.fetchall()]


def pool_closed_episodes(conn, net, catchment_id: str, stream: str, *,
                         since_days: int = 365,
                         labels: dict[str, str] | None = None) -> list[RecurringSource]:
    return pool_episodes(closed_episodes(conn, catchment_id, stream,
                                         since_days=since_days), net, labels=labels)
