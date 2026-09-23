import numpy as np, pytest
from upstream_kernel.ec2 import edge_weight, ec2_gain, greedy_select

def test_edge_weight_is_zero_when_all_mass_is_in_one_class():
    p = np.array([0.5, 0.5]); classes = np.array([0, 0])
    assert edge_weight(p, classes) == pytest.approx(0.0)

def test_edge_weight_is_maximal_for_an_even_split_across_classes():
    even = edge_weight(np.array([0.5, 0.5]), np.array([0, 1]))
    skewed = edge_weight(np.array([0.9, 0.1]), np.array([0, 1]))
    assert even > skewed

def test_a_test_that_perfectly_separates_two_classes_cuts_all_edges():
    p = np.array([0.5, 0.5]); classes = np.array([0, 1])
    # outcome 0 happens only under h0, outcome 1 only under h1
    outcomes = np.array([[1.0, 0.0], [0.0, 1.0]])
    assert ec2_gain(p, classes, outcomes) == pytest.approx(edge_weight(p, classes))

def test_an_uninformative_test_has_zero_gain():
    p = np.array([0.5, 0.5]); classes = np.array([0, 1])
    outcomes = np.array([[0.5, 0.5], [0.5, 0.5]])
    assert ec2_gain(p, classes, outcomes) == pytest.approx(0.0, abs=1e-12)

def test_ec2_ignores_a_test_that_only_separates_within_one_class():
    """This is the whole point of EC2 over information gain: distinguishing hypotheses
    that lead to the SAME decision is worth nothing."""
    p = np.array([0.25, 0.25, 0.5]); classes = np.array([0, 0, 1])
    within = np.array([[1.0, 0.0, 0.5], [0.0, 1.0, 0.5]])   # splits h0 from h1, same class
    across = np.array([[1.0, 1.0, 0.0], [0.0, 0.0, 1.0]])   # splits class 0 from class 1
    assert ec2_gain(p, classes, across) > ec2_gain(p, classes, within)

def test_gain_is_never_negative():
    rng = np.random.default_rng(0)
    for _ in range(50):
        p = rng.dirichlet(np.ones(8)); classes = rng.integers(0, 3, 8)
        o = rng.uniform(0.01, 0.99, 8); outcomes = np.stack([o, 1 - o])
        assert ec2_gain(p, classes, outcomes) >= -1e-12

def test_greedy_select_prefers_high_gain_per_cost():
    p = np.array([0.5, 0.5]); classes = np.array([0, 1])
    perfect = np.array([[1.0, 0.0], [0.0, 1.0]])
    cands = {"cheap_perfect": perfect, "expensive_perfect": perfect}
    picks = greedy_select(p, classes, cands, {"cheap_perfect": 60.0,
                                              "expensive_perfect": 600.0}, k=2)
    assert picks[0][0] == "cheap_perfect"

def test_uninformative_test_scores_zero_for_every_outcome_split():
    """The zero has to hold for any outcome distribution, not just an even one.

    Summing unnormalised residuals gives W(p) * sum_o q_o^2 for a test that tells you
    nothing, which is positive for every q - so a lopsided split would hide the bug
    that an even one exposes.
    """
    p = np.array([0.4, 0.6])
    classes = np.array([0, 1])
    for q in (0.5, 0.1, 0.9, 0.25):
        outcomes = np.array([[q, q], [1 - q, 1 - q]])
        assert ec2_gain(p, classes, outcomes) == pytest.approx(0.0, abs=1e-12), q


def test_within_class_separation_is_worth_exactly_nothing():
    """Not merely less than across-class separation - zero. That is the EC2 property."""
    p = np.array([0.25, 0.25, 0.5])
    classes = np.array([0, 0, 1])
    within = np.array([[1.0, 0.0, 0.5], [0.0, 1.0, 0.5]])
    assert ec2_gain(p, classes, within) == pytest.approx(0.0, abs=1e-12)


def test_gain_never_exceeds_the_total_edge_weight():
    rng = np.random.default_rng(7)
    for _ in range(50):
        p = rng.dirichlet(np.ones(6))
        classes = rng.integers(0, 3, 6)
        o = rng.uniform(0.01, 0.99, 6)
        outcomes = np.stack([o, 1 - o])
        assert ec2_gain(p, classes, outcomes) <= edge_weight(p, classes) + 1e-12

