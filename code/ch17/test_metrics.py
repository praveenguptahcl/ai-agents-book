"""Adversarial tests for Chapter 17's PSR/DSR multiplicity control.

Each test attacks a specific way of lying to yourself with backtests:
fabricating edge (PSR coin-flip), ignoring multiplicity (DSR deflation),
mistrusting the closed form (bootstrap agreement), and worshipping short
track records (minTRL).
"""

import math

import numpy as np
import pytest

from metrics import (
    bootstrap_psr,
    dsr,
    dsr_from_stats,
    expected_sharpe_null,
    min_trl,
    norm_cdf,
    norm_ppf,
    psr,
    psr_from_stats,
    sample_moments,
    sharpe_ratio,
)

RNG = np.random.default_rng(20260911)


# ---------------------------------------------------------------------------
# Normal-distribution primitives
# ---------------------------------------------------------------------------
def test_norm_cdf_at_zero_is_one_half():
    assert norm_cdf(0.0) == pytest.approx(0.5, abs=1e-12)


def test_norm_ppf_is_inverse_of_cdf():
    for p in (0.025, 0.1, 0.5, 0.9, 0.975, 0.999):
        assert norm_cdf(norm_ppf(p)) == pytest.approx(p, abs=1e-9)


def test_norm_ppf_known_quantiles():
    assert norm_ppf(0.975) == pytest.approx(1.959964, abs=1e-5)
    assert norm_ppf(0.5) == pytest.approx(0.0, abs=1e-9)


def test_norm_ppf_rejects_degenerate_probabilities():
    for bad in (0.0, 1.0, -0.2, 1.5):
        with pytest.raises(ValueError):
            norm_ppf(bad)


def _exact_sharpe_returns(annual_sr: float, n_obs: int, seed: int) -> np.ndarray:
    """Return series with EXACTLY the target annualized Sharpe (daily bars).

    Standardizing the noise first removes sample luck, so these tests assert
    on the math rather than on one RNG draw.
    """
    z = np.random.default_rng(seed).standard_normal(n_obs)
    z = (z - z.mean()) / z.std()
    return z / math.sqrt(252.0) + annual_sr / 252.0


# ---------------------------------------------------------------------------
# PSR on true SR=0 streams: uniform, so the MEAN is the coin-flip answer
# ---------------------------------------------------------------------------
def test_psr_of_zero_edge_streams_averages_one_half():
    # A single zero-edge stream gives a Uniform(0, 1) PSR — the honest test
    # is that the average over many independent streams is ~0.5.
    rng = np.random.default_rng(4242)
    vals = [psr(rng.standard_normal(1000)) for _ in range(200)]
    assert sum(vals) / len(vals) == pytest.approx(0.5, abs=0.10)


def test_psr_of_strong_edge_is_near_one():
    returns = _exact_sharpe_returns(1.27, 2000, seed=5)
    assert psr(returns, benchmark_sr=0.0) > 0.99


def test_psr_is_symmetric_about_benchmark():
    # Same distance above and below the benchmark: p and 1-p.
    returns = RNG.normal(0.03, 1.0, 1500)
    sr = sharpe_ratio(returns)
    above = psr_from_stats(sr, sr - 0.2, 1500, 0.0, 3.0)
    below = psr_from_stats(sr, sr + 0.2, 1500, 0.0, 3.0)
    assert above + below == pytest.approx(1.0, abs=1e-9)


def test_psr_matches_hand_worked_arithmetic():
    # Chapter hand example: SR=0.5, bench 0, T=60, skew -0.5, kurt 5.
    # denom = sqrt(1 + 0.25 + 0.25) = sqrt(1.5); stat = 0.5*sqrt(59)/sqrt(1.5).
    expected = norm_cdf(0.5 * math.sqrt(59) / math.sqrt(1.5))
    assert psr_from_stats(0.5, 0.0, 60, -0.5, 5.0) == pytest.approx(expected, abs=1e-9)
    assert psr_from_stats(0.5, 0.0, 60, -0.5, 5.0) == pytest.approx(0.9991, abs=0.0005)


def test_psr_rejects_a_one_period_track_record():
    # Exactly one observation-period proves nothing; the formula needs T > 1.
    with pytest.raises(ValueError):
        psr_from_stats(1.0, 0.0, 1.0, 0.0, 3.0)


# ---------------------------------------------------------------------------
# DSR: a "great" Sharpe dies under 250 trials
# ---------------------------------------------------------------------------
def _null_trials(k: int, sd: float, seed: int) -> np.ndarray:
    """Trial Sharpes under the null: no edge anywhere, dispersion only."""
    return np.random.default_rng(seed).normal(0.0, sd, k)


def test_expected_sharpe_null_grows_with_trials():
    trials_10 = _null_trials(1000, 0.2, 1)[:10]
    trials_250 = _null_trials(1000, 0.2, 1)[:250]
    assert expected_sharpe_null(250, trials_250) > expected_sharpe_null(10, trials_10)


def test_expected_sharpe_null_matches_hand_arithmetic():
    # K=250, trial sd 0.2, normal: SR0 = 0.2*((1-g)Q(0.996) + g*Q(1-1/(250e))).
    trials = _null_trials(250, 0.2, 3)
    sr0 = expected_sharpe_null(250, trials)
    assert sr0 == pytest.approx(0.5675, abs=0.05)


def test_dsr_deflates_under_250_trials():
    # A 0.6 Sharpe looks strong alone (PSR > 0.95) but dies at 250 trials.
    returns = _exact_sharpe_returns(0.6, 2520, seed=21)  # 10 years, daily
    trials = _null_trials(250, 0.2, 11)
    assert psr(returns, 0.0) > 0.90
    result = dsr(returns, trials)
    assert result["dsr"] < 0.90
    assert result["n_trials"] == 250
    assert result["sr_null"] > 0.4  # the lucky-maximum the null expects


def test_dsr_survives_when_edge_is_overwhelming():
    returns = _exact_sharpe_returns(1.2, 5040, seed=22)  # 20 years, daily
    trials = _null_trials(250, 0.2, 11)
    assert dsr(returns, trials)["dsr"] > 0.95


def test_dsr_hand_worked_case_is_below_the_bar():
    # Chapter hand example: 0.65 Sharpe, 5 years, K=250 -> DSR ~0.56,
    # far below any sane 0.95 bar.
    assert dsr_from_stats(0.65, 5.0, 0.5675, 0.0, 3.0) == pytest.approx(0.56, abs=0.02)
    assert dsr_from_stats(0.65, 5.0, 0.5675, 0.0, 3.0) < 0.95


def test_dsr_hand_worked_survivor_clears_the_bar():
    # The same setup with a 1.2 Sharpe over 20 years: DSR ~0.98. Note the
    # price of survival — the honest lesson of this chapter.
    assert dsr_from_stats(1.2, 20.0, 0.5675, 0.0, 3.0) > 0.95


def test_dsr_needs_multiple_trials():
    with pytest.raises(ValueError):
        dsr(np.ones(100), np.array([1.0]))


# ---------------------------------------------------------------------------
# Closed form vs bootstrap: two roads, same answer
# ---------------------------------------------------------------------------
def test_bootstrap_agrees_with_closed_form_on_edge():
    returns = _exact_sharpe_returns(1.27, 2000, seed=9)
    closed = psr(returns, 0.0)
    boot = bootstrap_psr(returns, 0.0, n_boot=300, seed=99)
    assert abs(closed - boot) < 0.05
    assert closed > 0.9 and boot > 0.9


def test_bootstrap_is_deterministic_for_fixed_seed():
    returns = _exact_sharpe_returns(1.27, 2000, seed=9)
    assert bootstrap_psr(returns, n_boot=300, seed=99) == \
           bootstrap_psr(returns, n_boot=300, seed=99)


# ---------------------------------------------------------------------------
# minTRL: short track records are rumors
# ---------------------------------------------------------------------------
def test_min_trl_hand_arithmetic():
    # 0.8 vs benchmark 0.5, normal, alpha 0.05:
    #   scale = 1 + (3-1)/4 * 0.5^2 = 1.125
    #   minTRL = 1 + 1.125 * (1.6449/0.3)^2 ~= 34.82 -> ~35 observations.
    assert min_trl(0.8, 0.5, 0.0, 3.0) == pytest.approx(34.82, abs=0.1)


def test_min_trl_explodes_for_thin_edges():
    # Proving a 0.6 against a 0.5 benchmark needs ~306 observations.
    assert min_trl(0.6, 0.5, 0.0, 3.0) == pytest.approx(305.37, abs=0.5)


def test_min_trl_rejects_observed_below_benchmark():
    with pytest.raises(ValueError):
        min_trl(0.4, 0.5, 0.0, 3.0)


def test_min_trl_tighter_alpha_needs_longer_record():
    loose = min_trl(1.0, 0.0, 0.0, 3.0, alpha=0.10)
    tight = min_trl(1.0, 0.0, 0.0, 3.0, alpha=0.01)
    assert tight > loose > 0


# ---------------------------------------------------------------------------
# Degenerate inputs fail closed
# ---------------------------------------------------------------------------
def test_zero_variance_returns_raise():
    with pytest.raises(ValueError):
        sharpe_ratio(np.full(100, 0.01))


def test_nan_returns_raise():
    bad = np.full(100, 0.01)
    bad[5] = np.nan
    with pytest.raises(ValueError):
        sample_moments(bad)


def test_empty_returns_raise():
    with pytest.raises(ValueError):
        sample_moments(np.array([]))
