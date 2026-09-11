# Chapter 17 — PSR and DSR: Statistics Against Self-Deception

> *Figure 17.1 — The deflation diagram: the null distribution of the best-of-K Sharpe, the observed Sharpe, and the haircut between them. Full spec: `figs/ch17-figspec.md`.*

The method working correctly looks like heartbreak.

Two hundred and fifty trading modules. Each one walked forward over historical data with embargo gaps, no lookahead, every bar honestly labeled REAL or SYNTHETIC. The raw walk-forward gave 39 PASS, 84 FAIL, and 127 HOLD — and HOLD is the honest verdict: the module produced nothing tradeable, so the harness reported flat instead of inventing a story. Then came multiplicity control. The Deflated Sharpe Ratio, computed across all 250 trials, asked a single question: *how many of these survivors beat what luck alone would produce, given that you tried 250 things?* The answer was zero. Zero of 250 survived.

Fourteen intraday candidates had looked like the answer. Out-of-sample Sharpes between 7 and 20, Probabilistic Sharpe Ratios at or above 0.95 — the kind of numbers that get a strategy funded. But their trial results scattered so wildly across folds that under deflation they died anyway. The dispersion *was* the information: a Sharpe of 12 that only appears when the wind blows right is not an edge, it is weather.

This chapter is the mathematics behind that heartbreak. It is also the chapter that makes the heartbreak a feature rather than a bug: a verification discipline that cannot say "nothing survived" is not a verification discipline. It is a marketing department.

One honesty note before the math. The development sample in that validation was AMD — the same ticker the research family had been tuned on for months. The folds were honest but inbred: the strategy universe had already, indirectly, seen the data's personality. That is precisely why the verdict says "zero survived *on this sample*" and not "no strategy can ever work." Genuinely unseen data is required for the next round. A statistic cannot launder a contaminated sample; it can only tell you, precisely, how unimpressed it is.

## The three lies of the Sharpe ratio

The Sharpe ratio — mean return divided by volatility — is the most quoted and most abused number in finance. It lies in three distinct ways, and you need all three names because each one kills strategies that the other two would have passed.

**Lie one: non-normality.** The Sharpe ratio treats upside and downside volatility as the same sin. A strategy that bleeds a little every day and occasionally makes a fortune (positive skew) looks *worse* than its mirror image that grinds upward and occasionally detonates — even though you would obviously rather own the first one. Negative skew and fat tails (kurtosis) mean the realized Sharpe overstates the risk-adjusted reality. Any correction must therefore know the skew and kurtosis, not just the mean and variance.

**Lie two: short samples.** A Sharpe ratio estimated over forty days is mostly noise wearing a number costume. The shorter the track record, the wider the confidence interval around the estimate — and the interval, not the point estimate, is what you are betting on. We will quantify exactly how short is too short.

**Lie three: multiple testing — the killer.** This is the one that murders careers. You test 250 strategies. Each is pure noise. What is the best Sharpe you expect to see? Not zero. With 250 draws from a Sharpe distribution with standard deviation 0.2, the expected *maximum* is about **0.57** — we will derive this below. So your "0.6 Sharpe strategy, discovered after testing 250 candidates" is not a discovery. It is the expected value of trying. Every backtest you have ever admired without asking "how many did they try?" is suspect until proven otherwise.

## The Probabilistic Sharpe Ratio

Marcos López de Prado and David Bailey's Probabilistic Sharpe Ratio (2012) fixes lies one and two in a single formula. Instead of asking "what is the Sharpe ratio?", it asks the question you actually care about: **what is the probability that the true Sharpe ratio exceeds some benchmark, given the sample length, skew, and kurtosis?**

$$PSR(SR^*) = \Phi\left(\frac{(\hat{SR} - SR^*)\sqrt{T-1}}{\sqrt{1 - \hat{\gamma}_3\hat{SR} + \frac{\hat{\gamma}_4-1}{4}\hat{SR}^2}}\right)$$

Read it term by term, because every term is doing work:

- $(\hat{SR} - SR^*)$ is the *edge over the benchmark*. Not the Sharpe — the Sharpe minus what you could have had anyway. A benchmark of zero asks "does this beat cash?"; a benchmark of 0.5 asks "does this beat a trivial risk-parity portfolio?"
- $\sqrt{T-1}$ is the *sample-length correction*. Double the data, shrink the uncertainty by $\sqrt{2}$. This is lie two, quantified.
- The denominator's $\hat{\gamma}_3$ (skewness) and $\hat{\gamma}_4$ (kurtosis) terms are lie one, quantified. Negative skew *widens* the denominator — the same observed Sharpe earns less confidence when the returns are left-tailed. Fat tails do the same. (Note: $\hat{\gamma}_4$ here is the Pearson kurtosis — 3.0 for a Normal distribution, which is why the term is $(\gamma_4-1)/4$.)
- $\Phi$ is the standard normal CDF. The whole fraction is a z-statistic; the PSR is the probability the truth clears the benchmark.

Let us work one by hand, the way the chapter's code will do it. A strategy with a **monthly** Sharpe of 0.5, observed over 60 months, with skewness −0.5 and kurtosis 5, against a benchmark of zero:

- Denominator: $1 - (-0.5)(0.5) + \frac{5-1}{4}(0.25) = 1 + 0.25 + 0.25 = 1.5$. So $\sqrt{1.5} \approx 1.2247$. Notice how the negative skew and fat tails each added 0.25 — the same 0.5 Sharpe with normal returns would have a denominator of $\sqrt{1.0625}$, earning noticeably more confidence.
- Numerator: $(0.5 - 0)\sqrt{59} = 0.5 \times 7.6811 = 3.8406$.
- z-statistic: $3.8406 / 1.2247 = 3.1362$.
- $PSR = \Phi(3.1362) \approx 0.9991$.

A 99.9% probability the true monthly Sharpe beats zero, *after* penalizing the ugly higher moments. That is a number you can take to an investment committee — unlike the bare "0.5" which tells you nothing about whether 60 months is enough.

The implementation starts with the normal-distribution primitives. This module deliberately avoids scipy — not out of austerity, but so the chapter can show every line that matters:

```python
def norm_cdf(x: float) -> float:
    """Phi(x): P(Z <= x) for Z ~ N(0, 1)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
```

(The inverse, `norm_ppf`, uses Acklam's rational approximation with relative error below $1.2 \times 10^{-9}$ — far tighter than any financial estimate it will ever serve. It lives in `metrics.py` in full.)

Sample moments come next, with a guard the test suite forced into existence — more on that below:

```python
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
```

And the PSR itself, in two layers — the statistics-level function the hand calculation above mirrors exactly, and the returns-level wrapper:

```python
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
```

That "frequency discipline" paragraph in the docstring is not decoration. During development, the first version of `psr()` annualized the Sharpe but passed the raw day count as T — inflating every test statistic by $\sqrt{252} \approx 15.9$ and making pure noise look like a 99.99% certainty. The adversarial test suite caught it, because one of the tests asserts that PSR over many independent zero-edge streams averages ~0.5. Mixing frequencies is the most common way smart people accidentally manufacture significance, and now the module refuses to let you do it silently: `psr()` converts Sharpe and T jointly, and `psr_from_stats()` documents the contract for direct callers.

## The Deflated Sharpe Ratio: multiplicity control

The PSR fixes lies one and two. Lie three — multiple testing — needs the Deflated Sharpe Ratio (Bailey & López de Prado, 2014). The idea is disarmingly simple: **the DSR is the PSR evaluated at a benchmark that accounts for how many strategies you tried.**

That benchmark is $SR_0$, the expected Sharpe ratio under the null hypothesis — the expected value of the *best* Sharpe among $K$ trials when none of them has any edge. Extreme-value theory gives it a closed form:

$$SR_0 = \sqrt{\hat{V}} \left((1-\gamma)\Phi^{-1}\!\left(1-\frac{1}{K}\right) + \gamma\,\Phi^{-1}\!\left(1-\frac{1}{Ke}\right)\right)$$

where $\hat{V}$ is the variance of the $K$ trial Sharpe ratios, $\gamma \approx 0.5772$ is the Euler–Mascheroni constant, and the two $\Phi^{-1}$ terms are the expected maximum of $K$ standard normals (with a refined second-order correction). The intuition: the more strategies you try, and the more dispersed their Sharpes, the higher the bar luck alone can clear.

Work it by hand for the chapter's running example. $K = 250$ trials, trial-Sharpe standard deviation 0.2:

- $\Phi^{-1}(1 - 1/250) = \Phi^{-1}(0.996) \approx 2.6521$
- $\Phi^{-1}(1 - 1/(250e)) \approx 2.9736$
- $SR_0 = 0.2 \times ((1 - 0.5772)(2.6521) + 0.5772(2.9736)) = 0.2 \times (1.1213 + 1.7164) = 0.2 \times 2.8377 \approx 0.5675$

Read that number slowly. **You tried 250 things, and the null hypothesis — pure noise — expects your best Sharpe to be 0.57.** Your "0.6 Sharpe strategy, discovered after testing 250 candidates" is not a discovery. It is the expected value of trying.

Then $DSR = PSR(SR_0)$: the same probability machinery, but the benchmark is the luck-adjusted bar, and the skew/kurtosis in the denominator come from the *cross-trial* distribution (how the 250 Sharpes scatter), not from the selected strategy's returns:

```python
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
```

The cross-trial moments come from `trial_moments` (skewness and Pearson kurtosis of the $K$ trial Sharpes — the dispersion the DSR listens to), and the verdict itself is one line:

```python
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
```

Note that `dsr()` returns the full ingredient list, not just the verdict. That is deliberate, and it is a Chapter 9 decision wearing Chapter 17 clothes: the audit trail must record *why* a strategy passed or failed — the null benchmark, the trial count, the cross-trial moments — so that a future investigator can re-derive the verdict instead of trusting it. A single number is a claim; the ingredients are evidence.

Now the two hand-worked verdicts. **The death.** A strategy with an annualized Sharpe of 0.65, observed over 5 years, selected from 250 trials with $SR_0 = 0.5675$ and normal cross-trial moments:

- Denominator: $\sqrt{1 + \frac{3-1}{4}(0.65^2)} = \sqrt{1.2113} \approx 1.1006$
- Numerator: $(0.65 - 0.5675)\sqrt{4} = 0.0825 \times 2 = 0.165$
- z = 0.1499 → **DSR ≈ 0.56**

A 0.65 Sharpe — respectable on any desk, the kind of number that survives every single-trial test you throw at it — is a *coin flip* once you admit the 250 tries. The code agrees: `dsr_from_stats(0.65, 5.0, 0.5675, 0.0, 3.0)` returns 0.5596.

**The survivor.** The same setup, but an annualized Sharpe of 1.2 sustained over 20 years:

- Denominator: $\sqrt{1 + 0.5(1.44)} = \sqrt{1.72} \approx 1.3114$
- Numerator: $(1.2 - 0.5675)\sqrt{19} = 0.6325 \times 4.3589 = 2.757$
- z = 2.102 → **DSR ≈ 0.98**

It survives — at the price of twenty years. That price *is* the lesson. Multiplicity control does not say good strategies don't exist; it says the evidence required to believe in one scales with how hard you looked. The fourteen intraday candidates from the opening story had Sharpes of 7 to 20 and PSRs above 0.95 — and died anyway, because their cross-trial dispersion pushed the null benchmark up and their effective track records were short. Dispersion is information. The DSR listens to it.

## minTRL: how long before a Sharpe means anything

There is a companion question the PSR answers implicitly but `minTRL` answers explicitly: **how many observations do you need before a Sharpe estimate can clear significance at all?**

$$minTRL = 1 + \left(1 - \gamma_3 SR^* + \frac{\gamma_4-1}{4}{SR^*}^2\right)\left(\frac{z_\alpha}{\hat{SR} - SR^*}\right)^2$$

Work it. A strategy with Sharpe 0.8 against a benchmark of 0.5, normal returns, $\alpha = 0.05$ ($z = 1.6449$):

- Scale: $1 + \frac{3-1}{4}(0.25) = 1.125$
- $(1.6449 / 0.3)^2 = 30.06$
- $minTRL = 1 + 1.125 \times 30.06 = 34.82$ → **about 35 observations**

And a thinner edge — Sharpe 0.6 against the same 0.5 benchmark: $(1.6449/0.1)^2 = 270.57$, so $minTRL = 1 + 1.125 \times 270.57 = 305.4$ → **about 306 observations**. Proving a small edge takes roughly nine times the data of proving a moderate one. Most backtests die right here, before any fancy math: the track record is simply too short for the claimed edge, and no amount of clever statistics can fix a sample that small. If your track record is shorter than minTRL, your Sharpe ratio is a rumor.

```python
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
```

## Two roads, same answer: the bootstrap cross-check

Closed-form statistics deserve a model-free sparring partner. `bootstrap_psr` resamples the return series with replacement, computes the PSR on each resample, and averages — no normality assumptions, no moment estimates, just the empirical distribution arguing with the formula:

```python
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
```

The test suite demands the two roads agree within 0.05 on a strong edge, and that the bootstrap is deterministic for a fixed seed. When the closed form and the resampling disagree, you do not average them and move on — you investigate, because one of your assumptions is lying. (The degenerate-resample fallback to 0.5 is worth noticing: a resample with no variance carries no information, and the only honest PSR for "no information" is the coin flip.)

## The honest-reporting discipline

Step back from the formulas. What this chapter actually teaches is a reporting discipline, and it has four rules:

1. **Report the trial count.** A Sharpe without a K is a rumor with better formatting. The DSR's first input is how many things you tried — hide it and the number is meaningless.
2. **HOLD is a verdict.** The 127 HOLDs in the opening story are not failures of the harness; they are the harness working. A module that produces nothing tradeable must be reported as flat, never massaged into a small positive or quietly dropped from the denominator. Dropped trials are just unreported multiplicity.
3. **Name the contamination.** The AMD sample was the development sample. Say so, in the report, next to the numbers — "folds honest but inbred; genuinely unseen data required." A statistic cannot launder a contaminated sample; the honest sentence next to the number is doing real work.
4. **Zero survivors is a result.** The DSR said zero of 250. That is not the method failing. That is the method *working* — refusing to certify noise. A verification discipline that cannot say "nothing survived" is a marketing department.

These rules are why the DSR returns its ingredients alongside the verdict, why the walk-forward chapter (Ch 16) reports HOLDs instead of fabricating fills, and why the evidence chapter (Ch 9) insists the audit trail record the *why*. The spine of this book is Intent → Authority → Capability → Action → Evidence → Verification → Accountability, and this chapter is Verification at its most adversarial: not verifying that the system works, but verifying that your *belief* that it works survives contact with arithmetic.

## Handoff

The statistics are done. Part V closes here: the graders (Ch 15) score the system, the walk-forward protocol (Ch 16) keeps it honest about time, and the PSR/DSR (this chapter) keeps it honest about luck. What remains is the question the numbers cannot answer — who is *allowed* to run such a system, under what framework, and who goes to jail, figuratively or otherwise, when the ledger disagrees with reality. Part VI opens with the enterprise frameworks: the off-the-shelf agent stacks your organization already bought, and the wrappers that force them to live under every discipline this book has built.
