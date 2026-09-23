"""GC-6: a posterior is reproducible from its fingerprint alone.

The fingerprint names everything that determined the answer - which evidence, which
network, which parameters, which kernel build, which stream, which horizon - so a
snapshot can be recomputed bit for bit months later and shown to match.

Evidence ids are sorted, so the order events happened to arrive in does not change
the fingerprint. That is the same property `compute_posterior` has: the posterior is
recomputed from the full set, never updated incrementally, so late and out-of-order
data is not a special case.
"""
import hashlib
import json


def fingerprint(evidence_ids, *, network_version: str, params_version: str,
                kernel_version: str, stream: str,
                horizon_start: float, horizon_end: float) -> str:
    canon = json.dumps({
        "evidence": sorted(str(e) for e in evidence_ids),
        "network_version": network_version,
        "params_version": params_version,
        "kernel_version": kernel_version,
        "stream": stream,
        "horizon": [round(horizon_start, 3), round(horizon_end, 3)],
    }, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canon.encode()).hexdigest()
