"""PSR / DSR multiplicity control for walk-forward results.

Chapter 17 of "AI Agents: Systems, Safety, and Practice".

The seam with Chapter 16: a walk-forward run produces a return series for the
selected strategy (one per test fold, concatenated) and the full set of trial
Sharpe ratios across every candidate strategy that was tested. This module
consumes exactly ``(returns, trial_sharpes)`` — it knows nothing about folds,
embargoes, or graders; those belong to Chapters 16 and 15.

Math: Bailey & Lopez de Prado, "The Sharpe Ratio Efficient Frontier" (2012)
for the Probabilistic Sharpe Ratio, and "The Deflated Sharpe Ratio:
Correcting for Selection Bias, Backtest Overfitting and Non-Normality" (2014)
for DSR. Variable names follow the papers.

Dependencies: numpy + the standard library only. The standard normal CDF and
its inverse are implemented from first principles (erf; Acklam's rational
approximation) so the module has no scipy dependency — and so the chapter
can show every line that matters.
"""

from __future__ import annotations

import math

import numpy as np

# Euler-Mascheroni constant, used in the expected-Sharpe-under-the-null term.
EULER_MASCHERONI = 0.5772156649015329


# ---------------------------------------------------------------------------
# Standard normal distribution primitives (no scipy required)
# ---------------------------------------------------------------------------
def norm_cdf(x: float) -> float:
    """Phi(x): P(Z <= x) for Z ~ N(0, 1)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Phi^{-1}(p): the quantile function of N(0, 1), Acklam's approximation.

    Relative error < 1.2e-9 over (0, 1) — far tighter than any financial
    estimate this module will ever see.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"p must lie strictly in (0, 1); got {p!r}")

    # Coefficients for Acklam's rational approximation.
    a = (-39.69683028665376, 220.9460984245205, -275.9285104469687,
         138.3577518672690, -30.66479806614716, 2.506628277459239)
    b = (-54.47609879822406, 161.5858368580409, -155.6989798598866,
         66.80131188771972, -13.28068155288572)
    c = (-0.007784894002430293, -0.3223964580411365, -2.400758277161838,
         -2.549732539343734, 4.374664141464968, 2.938163982698783)
    d = (0.007784695709041462, 0.3224671290700398, 2.445134137142996,
         3.754408661907416)

    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                 ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


# ---------------------------------------------------------------------------
# Sample moments and the ordinary Sharpe ratio
# ---------------------------------------------------------------------------
def sample_moments(returns: np.ndarray) -> tuple[float, float, float, float]:
    """Return (mean, std, skewness, kurtosis) of a 1-D return array.

    Kurtosis here is the Pearson (non-excess) kurtosis: a Normal distribution
    has kurtosis 3, which is why the PSR denominator uses ``(kurt - 1) / 4``.
    """
    x = np.asarray(returns, dtype=float).ravel()
    if x.size < 2:
        raise ValueError(f"need at least 2 returns; got {x.size}")
    if not np.all(np.isfinite(x)):
        raise ValueError("returns contain NaN or inf")
    mean = float(np.mean(x))
    std = float(np.std(x, ddof=1))
    # Floating point means a constant series has std ~1e-18, not exactly 0 —
    # so the degenerate-input guard must use a tolerance, not == 0.0.
    if not std > 1e-12 * max(1.0, abs(mean)):
        raise ValueError("returns have (numerically) zero variance; Sharpe ratio undefined")
    z = (x - mean) / std
    skew = float(np.mean(z ** 3))
    kurt = float(np.mean(z ** 4))
    return mean, std, skew, kurt


def sharpe_ratio(returns: np.ndarray, periods_per_year: float = 252.0) -> float:
    """Annualized Sharpe ratio of a per-period return series (risk-free = 0)."""
    mean, std, _, _ = sample_moments(returns)
    return float((mean / std) * math.sqrt(periods_per_year))


# ---------------------------------------------------------------------------
# Probabilistic Sharpe Ratio
# ---------------------------------------------------------------------------
def psr_from_stats(sr: float, benchmark_sr: float, n_obs: int,
                   skew: float, kurt: float) -> float:
    """PSR(SR*) = Phi( (SR_hat - SR*) * sqrt(T-1)
                        / sqrt(1 - g3*SR_hat + (g4-1)/4 * SR_hat^2) ).

    The probability that the true Sharpe ratio exceeds ``benchmark_sr``,
    corrected for sample length (T), skewness (g3), and kurtosis (g4).

    Frequency discipline: ``sr`` and ``n_obs`` must be in the SAME frequency.
    An annualized Sharpe goes with T in years; a monthly Sharpe goes with T
    in months. Mixing them (annualized Sharpe, T in days) inflates the test
    statistic by sqrt(periods_per_year) — the most common way smart people
    accidentally manufacture significance. The returns-level ``psr()`` below
    handles the conversion; call this function directly only when you have
    already-consistent statistics.
    """
    if n_obs <= 1:
        raise ValueError(
            f"need more than one observation-period for inference; got {n_obs} "
            "(a one-period track record proves nothing — see minTRL)")
    denom_sq = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if denom_sq <= 0.0:
        raise ValueError(f"degenerate PSR denominator: {denom_sq}")
    stat = (sr - benchmark_sr) * math.sqrt(n_obs - 1) / math.sqrt(denom_sq)
    return norm_cdf(stat)


def psr(returns: np.ndarray, benchmark_sr: float = 0.0,
        periods_per_year: float = 252.0) -> float:
    """PSR of a return series against an annualized benchmark Sharpe."""
    x = np.asarray(returns, dtype=float).ravel()
    mean, std, skew, kurt = sample_moments(x)
    # Convert to annualized Sharpe AND years together: the statistic is
    # invariant to frequency only when SR and T are converted jointly.
    sr_annual = (mean / std) * math.sqrt(periods_per_year)
    t_years = x.size / periods_per_year
    return psr_from_stats(sr_annual, benchmark_sr, t_years, skew, kurt)


# ---------------------------------------------------------------------------
# Deflated Sharpe Ratio: PSR with the multiplicity-adjusted benchmark
# ---------------------------------------------------------------------------
def expected_sharpe_null(n_trials: int, trial_sharpes: np.ndarray) -> float:
    """SR_0: the expected Sharpe ratio under the null, across K trials.

    Even if NO strategy has any edge, the best of K tried strategies looks
    good by luck alone. This is the expected value of that lucky maximum,
    estimated from the cross-trial distribution of Sharpe ratios:

        SR_0 = sqrt(V) * ((1-gamma) * Phi^{-1}(1 - 1/K)
                          + gamma * Phi^{-1}(1 - 1/(K*e)))
    """
    trials = np.asarray(trial_sharpes, dtype=float).ravel()
    if n_trials < 2 or trials.size != n_trials:
        raise ValueError("need >= 2 trial Sharpes matching n_trials")
    if not np.all(np.isfinite(trials)):
        raise ValueError("trial Sharpes contain NaN or inf")
    var = float(np.var(trials, ddof=1))
    if not var > 1e-24:
        raise ValueError("trial Sharpes have (numerically) zero variance")
    term = ((1.0 - EULER_MASCHERONI) * norm_ppf(1.0 - 1.0 / n_trials)
            + EULER_MASCHERONI * norm_ppf(1.0 - 1.0 / (n_trials * math.e)))
    return math.sqrt(var) * term


def trial_moments(trial_sharpes: np.ndarray) -> tuple[float, float]:
    """Skewness and (non-excess) kurtosis of the cross-trial Sharpe distribution."""
    trials = np.asarray(trial_sharpes, dtype=float).ravel()
    std = float(np.std(trials, ddof=1))
    if not std > 1e-12 * max(1.0, abs(float(np.mean(trials)))):
        raise ValueError("trial Sharpes have (numerically) zero variance")
    z = (trials - float(np.mean(trials))) / std
    return float(np.mean(z ** 3)), float(np.mean(z ** 4))


def dsr_from_stats(sr: float, n_obs: int, sr_null: float,
                   trial_skew: float, trial_kurt: float) -> float:
    """DSR = PSR(SR_0): the PSR evaluated at the multiplicity benchmark."""
    return psr_from_stats(sr, sr_null, n_obs, trial_skew, trial_kurt)


def dsr(returns: np.ndarray, trial_sharpes: np.ndarray,
        periods_per_year: float = 252.0) -> dict:
    """Deflated Sharpe Ratio of a strategy, given all K trials it survived.

    Returns a dict with the DSR plus its ingredients, so the audit trail
    (Ch 9) can record *why* a strategy passed or failed, not just the verdict.
    """
    x = np.asarray(returns, dtype=float).ravel()
    trials = np.asarray(trial_sharpes, dtype=float).ravel()
    mean, std, _, _ = sample_moments(x)
    sr_annual = float((mean / std) * math.sqrt(periods_per_year))
    t_years = x.size / periods_per_year
    skew_t, kurt_t = trial_moments(trials)
    sr_null = expected_sharpe_null(trials.size, trials)
    value = dsr_from_stats(sr_annual, t_years, sr_null, skew_t, kurt_t)
    return {
        "dsr": value,
        "sharpe_annual": sr_annual,
        "sr_null": sr_null,
        "n_trials": trials.size,
        "n_obs_years": t_years,
        "trial_skew": skew_t,
        "trial_kurt": kurt_t,
    }


# ---------------------------------------------------------------------------
# minTRL: minimum track-record length
# ---------------------------------------------------------------------------
def min_trl(observed_sr: float, benchmark_sr: float,
            skew: float, kurt: float, alpha: float = 0.05) -> float:
    """How many observations before an SR estimate can clear significance.

        minTRL = 1 + (1 - g3*SR* + (g4-1)/4 * SR*^2) * (z_alpha / (SR_hat - SR*))^2

    If your track record is shorter than this, your Sharpe ratio is a rumor.
    """
    if observed_sr <= benchmark_sr:
        raise ValueError("observed Sharpe must exceed the benchmark")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must lie in (0, 1); got {alpha!r}")
    z = norm_ppf(1.0 - alpha)
    scale = 1.0 - skew * benchmark_sr + (kurt - 1.0) / 4.0 * benchmark_sr ** 2
    return 1.0 + scale * (z / (observed_sr - benchmark_sr)) ** 2


# ---------------------------------------------------------------------------
# Bootstrap cross-check: the closed form must agree with resampling
# ---------------------------------------------------------------------------
def bootstrap_psr(returns: np.ndarray, benchmark_sr: float = 0.0,
                  periods_per_year: float = 252.0,
                  n_boot: int = 1000, seed: int = 7) -> float:
    """Mean PSR over block resamples: a model-free check on the closed form."""
    x = np.asarray(returns, dtype=float).ravel()
    if x.size < 2:
        raise ValueError("need at least 2 returns")
    rng = np.random.default_rng(seed)
    total = 0.0
    for _ in range(n_boot):
        sample = rng.choice(x, size=x.size, replace=True)
        try:
            total += psr(sample, benchmark_sr, periods_per_year)
        except ValueError:
            total += 0.5  # degenerate resample: the coin-flip answer
    return total / n_boot
