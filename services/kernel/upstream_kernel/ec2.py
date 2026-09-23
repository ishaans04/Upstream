"""EC2 - Equivalence Class Edge Cutting (Golovin, Krause & Ray, NeurIPS 2010).

Hypotheses are grouped by the DECISION they imply. Imagine an edge between every pair of
hypotheses that sit in different groups, weighted by the product of their probabilities.
A test is worth exactly the edge weight it is expected to cut. Distinguishing two
hypotheses that lead to the same decision cuts no edges and therefore scores zero - which
is why EC2 beats plain information gain for this problem, and why it carries a
near-optimality guarantee under greedy selection.
"""
from __future__ import annotations

import numpy as np


def edge_weight(p: np.ndarray, classes: np.ndarray) -> float:
    total = float(p.sum())
    per_class = np.bincount(classes, weights=p)
    return 0.5 * (total ** 2 - float((per_class ** 2).sum()))


def expected_residual_weight(p: np.ndarray, classes: np.ndarray,
                             outcome_probs: np.ndarray) -> float:
    """Expected edge weight still standing after the test, over the outcome distribution.

    Each outcome's residual is weighted by how likely that outcome is:

        E[residual] = sum_o P(o) * W(p(.|o))

    and because W is quadratic in the weights, W(p(.|o)) = W(p * P(o|.)) / P(o)^2, so the
    term reduces to W(p * P(o|.)) / P(o).

    Dropping that division - summing the unnormalised W(p * P(o|.)) directly - looks
    harmless but is not. For a test that tells you nothing, P(o|h) = q_o for every h, and
    the unnormalised sum comes to W(p) * sum_o q_o^2, which is strictly less than W(p).
    A useless test would then show a positive gain: with two equally likely outcomes it
    scores half the total edge weight, which is what the plan's own
    `test_an_uninformative_test_has_zero_gain` catches.
    """
    total = 0.0
    for o in range(outcome_probs.shape[0]):
        pw = p * outcome_probs[o]
        p_o = float(pw.sum())
        if p_o <= 0:
            continue
        total += edge_weight(pw, classes) / p_o
    return total


def ec2_gain(p: np.ndarray, classes: np.ndarray, outcome_probs: np.ndarray) -> float:
    return edge_weight(p, classes) - expected_residual_weight(p, classes, outcome_probs)


def greedy_select(p: np.ndarray, classes: np.ndarray,
                  candidate_outcome_probs: dict[str, np.ndarray],
                  costs: dict[str, float], k: int = 5) -> list[tuple[str, float]]:
    """Greedy adaptive-submodular selection, normalised by cost (walking seconds).

    After picking a candidate we condition p on its *expected* outcome so the next pick is
    not redundant. This is the standard greedy policy whose near-optimality EC2 guarantees.
    """
    remaining = dict(candidate_outcome_probs)
    p_work = p.copy()
    picks: list[tuple[str, float]] = []
    for _ in range(min(k, len(remaining))):
        scored = [(cid, ec2_gain(p_work, classes, op) / max(costs.get(cid, 1.0), 1.0))
                  for cid, op in remaining.items()]
        scored.sort(key=lambda x: -x[1])
        best_id, best_score = scored[0]
        if best_score <= 0:
            break
        picks.append((best_id, float(best_score)))
        op = remaining.pop(best_id)
        # Condition on the expected outcome: mixture weighted by each outcome's probability.
        po = np.array([float((p_work * op[o]).sum()) for o in range(op.shape[0])])
        po = po / max(po.sum(), 1e-300)
        p_work = p_work * np.einsum("o,oh->h", po, op)
        p_work = p_work / max(p_work.sum(), 1e-300)
    return picks
