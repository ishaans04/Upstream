"""Task 8.2: baselines, the matched filter, and the claim it is better than looking blind.

No database here. Every count is drawn from a known negative-binomial truth, so
each test knows the right answer before it asks.
"""
import numpy as np
import pytest
from clinical_stats.baselines import Baseline, fit_baseline, simulate
from clinical_stats.cluster import blind_scan
from clinical_stats.matched_filter import expected_curve, matched_filter_test
from upstream_shared.codes import SEWAGE_PATHOGEN_MIX, PathogenClass

DAY0 = 20_000                   # an arbitrary absolute day; only differences matter
WINDOW = 35                     # days tested
EXPOSURE_OFFSET = 14            # exposure falls on this day of the window
KW = {"episode_id": "EE-1", "area_code": "A", "syndrome": "acute_gastroenteritis"}

# Eight presentations a day, a mild season, and a quieter Sunday (weekday 6).
TRUTH = Baseline(area_code="A", syndrome="acute_gastroenteritis", alpha=0.05,
                 coefficients=(np.log(8.0), 0.2, 0.3, 0, 0, 0, 0, 0, -0.3), origin=0,
                 harmonics=1, trend=False, n_obs=0)


def exposure_on(day: int, population: int = 2000) -> dict:
    """Six hours of exposure starting 08:00 UTC on `day` (days on the absolute scale)."""
    t0 = day * 86400.0 + 8 * 3600
    return {"t_grid": np.arange(t0, t0 + 6 * 3600, 300.0), "p_exposed": np.full(72, 0.5),
            "population": population}


Z = exposure_on(DAY0)


@pytest.fixture(scope="module")
def history_days():
    return np.arange(DAY0 - 730, DAY0)


@pytest.fixture(scope="module")
def baseline(history_days):
    counts = simulate(TRUTH, history_days, np.random.default_rng(1))
    return fit_baseline(history_days, counts, area_code="A", syndrome="acute_gastroenteritis")


@pytest.fixture(scope="module")
def window_days():
    return np.arange(DAY0, DAY0 + WINDOW)


@pytest.fixture(scope="module")
def shape():
    """The predicted excess across the window, for exposure on day EXPOSURE_OFFSET."""
    s = np.zeros(WINDOW)
    s[EXPOSURE_OFFSET:] = expected_curve(Z, SEWAGE_PATHOGEN_MIX,
                                         days=np.arange(WINDOW - EXPOSURE_OFFSET))
    return s


# --- The predicted curve ----------------------------------------------------


def test_expected_curve_peaks_after_the_exposure_window():
    c = expected_curve(Z, SEWAGE_PATHOGEN_MIX, days=np.arange(0, 21))
    assert 2 <= int(np.argmax(c)) <= 8          # sewage mix peaks a few days out


def test_nobody_presents_on_the_day_of_exposure():
    c = expected_curve(Z, SEWAGE_PATHOGEN_MIX, days=np.arange(0, 21))
    assert c[0] < 0.01 * c.max()


def test_norovirus_heavy_mix_peaks_earlier_than_a_crypto_heavy_mix():
    early = expected_curve(Z, {PathogenClass.NOROVIRUS: 1.0}, days=np.arange(0, 21))
    late = expected_curve(Z, {PathogenClass.CRYPTOSPORIDIUM: 1.0}, days=np.arange(0, 21))
    assert np.argmax(early) < np.argmax(late)


def test_curve_integrates_to_the_attack_rate_times_population():
    c = expected_curve(Z, SEWAGE_PATHOGEN_MIX, days=np.arange(0, 40), attack_rate=0.02)
    assert c.sum() == pytest.approx(0.02 * Z["population"], rel=0.05)


def test_a_later_exposure_moves_the_curve_by_the_same_number_of_days():
    """The shape is anchored to when the water was dirty, not to when it was reported."""
    later = exposure_on(DAY0 + 3)
    later["t_grid"] = np.concatenate([Z["t_grid"][:1], later["t_grid"]])
    later["p_exposed"] = np.concatenate([[0.0], later["p_exposed"]])
    base = expected_curve(Z, SEWAGE_PATHOGEN_MIX, days=np.arange(0, 21))
    moved = expected_curve(later, SEWAGE_PATHOGEN_MIX, days=np.arange(0, 21))
    assert int(np.argmax(moved)) == int(np.argmax(base)) + 3


# --- The baseline -----------------------------------------------------------


def test_baseline_captures_day_of_week_effect(history_days, baseline):
    future = np.arange(DAY0, DAY0 + 364)
    sundays, mondays = future[future % 7 == 6], future[future % 7 == 0]
    assert baseline.predict(mondays).mean() > baseline.predict(sundays).mean()


def test_baseline_recovers_the_level_and_the_dispersion(baseline, window_days):
    """Close, not exact: two years of noisy counts leave a few percent of error.

    With this history the fit is about 8% high over the window -- a slope that is
    noise but passes the trend test, plus seasonal error. That is what an estimated
    baseline is like, and it is why the calibration tests below are conditional on
    the baseline rather than on a truth the service never sees.
    """
    ratio = baseline.predict(window_days) / TRUTH.predict(window_days)
    assert ratio.mean() == pytest.approx(1.0, abs=0.15)
    assert 0.01 < baseline.alpha < 0.15


def test_a_short_history_gets_no_season_it_cannot_support():
    days = np.arange(DAY0 - 60, DAY0)
    b = fit_baseline(days, simulate(TRUTH, days, np.random.default_rng(3)), area_code="A",
                     syndrome="acute_gastroenteritis")
    assert b.harmonics == 0


def test_too_little_history_is_refused_rather_than_fitted():
    days = np.arange(DAY0 - 10, DAY0)
    with pytest.raises(ValueError):
        fit_baseline(days, simulate(TRUTH, days, np.random.default_rng(3)), area_code="A",
                     syndrome="acute_gastroenteritis")


def test_suppressed_days_are_left_out_not_read_as_zero(history_days):
    counts = simulate(TRUTH, history_days, np.random.default_rng(1))
    holed = counts.copy()
    holed[::3] = np.nan
    full = fit_baseline(history_days, counts, area_code="A", syndrome="ag")
    partial = fit_baseline(history_days, holed, area_code="A", syndrome="ag")
    # Reading the holes as zero would pull the level down by about a third.
    assert partial.predict(history_days).mean() == pytest.approx(
        full.predict(history_days).mean(), rel=0.05)


def test_a_stored_baseline_predicts_what_the_fitted_one_did(baseline, window_days):
    row = baseline.to_row()
    restored = Baseline.from_row("A", "acute_gastroenteritis", baseline.alpha, row,
                                 baseline.n_obs)
    assert np.allclose(restored.predict(window_days), baseline.predict(window_days))


# --- The matched filter -----------------------------------------------------


def test_matched_filter_detects_an_injected_excess_matching_the_shape(baseline, shape,
                                                                     window_days):
    counts = simulate(TRUTH, window_days, np.random.default_rng(7), extra=shape)
    r = matched_filter_test(counts, baseline, shape, days=window_days, **KW)
    assert r.p_value < 0.01 and r.effect_size > 0


def test_the_effect_size_is_the_excess_as_a_multiple_of_the_prediction(baseline, shape,
                                                                       window_days):
    """1.0 means "about as many extra cases as the episode predicts"."""
    effects = [matched_filter_test(simulate(TRUTH, window_days, np.random.default_rng(s),
                                            extra=2.0 * shape), baseline, shape,
                                   days=window_days, n_sim=99, **KW).effect_size
               for s in range(40)]
    assert np.mean(effects) == pytest.approx(2.0, rel=0.2)


def test_matched_filter_ignores_an_excess_with_the_wrong_shape(baseline, shape, window_days):
    """The whole point: looking for a known shape, not for any bump.

    The same excess, two weeks early -- the right size, at the wrong time. One seed
    could land anywhere, so the rate over many is what is asserted: an excess the
    episode cannot explain must not look like one it predicted.
    """
    wrong = np.zeros(WINDOW)
    wrong[: WINDOW - EXPOSURE_OFFSET] = shape[EXPOSURE_OFFSET:]
    counts = simulate(TRUTH, window_days, np.random.default_rng(11), extra=wrong)
    assert matched_filter_test(counts, baseline, shape, days=window_days, **KW).p_value > 0.10

    ps = np.array([matched_filter_test(simulate(TRUTH, window_days, np.random.default_rng(s),
                                                extra=wrong), baseline, shape,
                                       days=window_days, n_sim=999, **KW).p_value
                   for s in range(60)])
    assert np.mean(ps < 0.10) <= 0.20


def test_no_excess_gives_a_uniform_p_value_distribution(baseline, shape, window_days):
    """Calibration: under the null, p-values should be roughly uniform.

    "The null" is the baseline the test is given. A p-value can promise nothing
    about a truth it was never shown; how close the baseline is to the truth is the
    job of the baseline tests above.
    """
    ps = np.array([matched_filter_test(simulate(baseline, window_days,
                                                np.random.default_rng(s)),
                                       baseline, shape, days=window_days, n_sim=1999,
                                       **KW).p_value for s in range(200)])
    assert 0.02 <= np.mean(ps < 0.05) <= 0.10
    assert 0.40 <= np.mean(ps < 0.50) <= 0.60


def test_the_same_counts_give_the_same_p_value(baseline, shape, window_days):
    """GC-6: the bootstrap is seeded, so a result can be reproduced."""
    counts = simulate(TRUTH, window_days, np.random.default_rng(5), extra=shape)
    a = matched_filter_test(counts, baseline, shape, days=window_days, **KW)
    b = matched_filter_test(counts, baseline, shape, days=window_days, **KW)
    assert a.p_value == b.p_value and a.effect_size == b.effect_size


def test_missing_days_drop_out_of_the_test(baseline, shape, window_days):
    counts = simulate(TRUTH, window_days, np.random.default_rng(7), extra=shape)
    counts[::4] = np.nan
    r = matched_filter_test(counts, baseline, shape, days=window_days, **KW)
    assert r.n_days == int(np.count_nonzero(~np.isnan(counts)))
    assert r.p_value < 0.05


def test_a_window_with_nothing_to_look_for_says_so(baseline, window_days):
    counts = simulate(TRUTH, window_days, np.random.default_rng(7))
    r = matched_filter_test(counts, baseline, np.zeros(WINDOW), days=window_days, **KW)
    assert r.p_value == 1.0 and r.effect_size == 0.0


def test_the_wire_form_carries_no_count(baseline, shape, window_days):
    counts = simulate(TRUTH, window_days, np.random.default_rng(7), extra=shape)
    wire = matched_filter_test(counts, baseline, shape, days=window_days, **KW).to_wire()
    assert set(wire) == {"episode_id", "area_code", "syndrome", "method", "p_value",
                         "effect_size", "n_days", "computed_at"}


# --- G5 ---------------------------------------------------------------------


def _first_detection(counts, days, test, *, alpha=0.01) -> int:
    """Days after exposure until `test` first rejects, run once a day as data arrive."""
    for d in range(EXPOSURE_OFFSET, WINDOW):
        if test(counts[: d + 1], days[: d + 1]) < alpha:
            return d - EXPOSURE_OFFSET
    return WINDOW - EXPOSURE_OFFSET          # never: charged the whole horizon


def test_matched_filter_beats_a_blind_cluster_scan_on_detection_delay(baseline, shape,
                                                                      window_days):
    """G5 -- the claim the PRD makes, tested directly.

    Both tests run daily on the same counts at the same significance level, the way
    a surveillance system would run them. The blind scan pays for not knowing when
    or what shape to look for; the matched filter does not.
    """
    matched, blind = [], []
    for s in range(30):
        counts = simulate(TRUTH, window_days, np.random.default_rng(100 + s), extra=shape)
        matched.append(_first_detection(counts, window_days, lambda c, d: matched_filter_test(
            c, baseline, shape, days=d, n_sim=999, **KW).p_value))
        blind.append(_first_detection(counts, window_days, lambda c, d: blind_scan(
            c, baseline, days=d, n_sim=999).p_value))
    mean_delay_matched, mean_delay_blind_scan = np.mean(matched), np.mean(blind)
    assert mean_delay_matched < mean_delay_blind_scan


def test_the_blind_scan_is_itself_calibrated(baseline, window_days):
    """Otherwise G5 would be won against a strawman that cries wolf, or never does."""
    ps = np.array([blind_scan(simulate(baseline, window_days, np.random.default_rng(s)), baseline,
                              days=window_days, n_sim=999).p_value for s in range(150)])
    assert 0.02 <= np.mean(ps < 0.05) <= 0.10


def test_the_blind_scan_finds_a_sharp_cluster_and_says_where(baseline, window_days):
    extra = np.zeros(WINDOW)
    extra[20:23] = 15.0
    counts = simulate(TRUTH, window_days, np.random.default_rng(2), extra=extra)
    c = blind_scan(counts, baseline, days=window_days)
    assert c.p_value < 0.01
    assert window_days[19] <= c.start_day and c.end_day <= window_days[23]
