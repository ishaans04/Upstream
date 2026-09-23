"""TRACE: rank source corridors and explain the ranking from the model, not from an LLM.

PRD 7.3: "for each top candidate, the observations that most supported it and the
observations that eliminated its rivals. This explanation is computed from the model."

That distinction matters. Every number below is a log-evidence contribution the
likelihood actually produced, so the explanation cannot drift from what the posterior
did - unlike a narrative generated after the fact.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import logsumexp

from .model.hypotheses import KIND_POINT
from .model.likelihood import log_likelihood
from .model.posterior import source_marginals


@dataclass(frozen=True)
class Corridor:
    entry_id: str
    probability: float
    node_path: tuple[str, ...]


def source_corridors(post, net, top_k: int = 3) -> list[Corridor]:
    m = source_marginals(post, net)
    ranked = sorted(((k, v) for k, v in m.items() if not k.startswith("__")),
                    key=lambda kv: -kv[1])[:top_k]
    out = []
    for entry_id, p in ranked:
        i = net.node_index[entry_id]
        path = [entry_id] + [net.node_ids[int(net.edges[e][1])]
                             for e in net.downstream_path[i]]
        out.append(Corridor(entry_id=entry_id, probability=float(p),
                            node_path=tuple(path)))
    return out


def explain(post, observations, net, grid, tables, params, top_k: int = 3) -> dict:
    """For each top candidate, the log-evidence each observation contributed to it,
    and the log-evidence it removed from that candidate's closest rival."""
    corridors = source_corridors(post, net, top_k)
    per_obs = {o.event_id: np.asarray(log_likelihood(o, grid, tables, post.flow_idx, params))
               for o in observations}
    lp_prior_only = post.log_p - sum(per_obs.values()) if per_obs else post.log_p

    def group_ll(arr, k):
        mask = (grid.kind == KIND_POINT) & (grid.entry_k == k)
        if not mask.any():
            return 0.0
        w = np.exp(lp_prior_only[mask] - logsumexp(lp_prior_only[mask]))
        return float(np.sum(w * arr[mask]))

    candidates = []
    for rank, c in enumerate(corridors):
        k = net.entry_nodes.index(c.entry_id)
        rivals = [x for x in corridors if x.entry_id != c.entry_id]
        rival_k = net.entry_nodes.index(rivals[0].entry_id) if rivals else k
        supported, eliminated = [], []
        for eid, arr in per_obs.items():
            mine = group_ll(arr, k)
            theirs = group_ll(arr, rival_k)
            entry = {"event_id": eid, "log_evidence": round(mine, 4),
                     "relative_to_rival": round(mine - theirs, 4)}
            (supported if mine - theirs > 0 else eliminated).append(entry)
        supported.sort(key=lambda e: -e["relative_to_rival"])
        eliminated.sort(key=lambda e: e["relative_to_rival"])
        candidates.append({
            "rank": rank + 1, "entry_id": c.entry_id, "probability": round(c.probability, 4),
            "node_path": list(c.node_path),
            "supported_by": supported[:5],
            "eliminated_rivals_by": eliminated[:5],
        })
    return {"candidates": candidates,
            "p_event": round(post.p_event, 4),
            "kernel_version": post.kernel_version,
            "fingerprint": post.fingerprint}
