"""Lab 4 — Walk-Forward Verdict (Chapter 23).

The capstone lab: the whole book in one exercise. You wire three cleared
components into an end-to-end verification pipeline and run it against a
strategy that is lying to you.

THE SETUP
---------
``MomentumMirage`` looks GREAT in-sample: an annualized Sharpe of 2.47 on its
training window. Your pipeline must walk it forward with embargo gaps (Ch 16),
deflate its Sharpe for multiple testing (Ch 17), and have two LLM judges
score your verdict thesis (Ch 15). The honest answer is FAIL — the strategy
dies the moment the regime turns. If your pipeline reports PASS, it fails
this lab. That is not a trick; that is the job.

FAIL-FIRST
----------
This file is RED on purpose. The two functions in the STUDENT IMPLEMENTATION
ZONE raise NotImplementedError. Every test below fails until you build the
pipeline. The red->green checklist is in Chapter 23; the passing
implementation lives in Appendix B — not here, not in this file.

ANTI-FABRICATION RULES (enforced by the tests, not by honor)
------------------------------------------------------------
1. Reporting PASS on the canary is an automatic fail (test_canary_does_not_pass).
2. Hard-coding "FAIL" for everything fails too: the FlatLiner must get an
   honest HOLD (test_flatliner_gets_honest_hold). The pipeline must compute.
3. The thesis judges score YOUR thesis against a frozen dataset whose hash is
   pinned. Gaming the judges is gaming Chapter 15's machinery, and kappa
   will tell on you.
"""

import random
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ch15.evaluator import (
    EvalCase,
    FrozenDataset,
    JudgeVerdict,
    LLMJudge,
    cohens_kappa,
)
from ch16.walk_forward import (
    Bar,
    DataViolation,
    EmbargoViolation,
    Fold,
    FoldResult,
    Intent,
    WalkForwardError,
    make_calendar_folds,
    walk_forward,
)
from ch17.metrics import dsr, sharpe_ratio

# ---------------------------------------------------------------------------
# Lab constants (GIVEN — do not change; the grader assumes them)
# ---------------------------------------------------------------------------
SEED = 2033
N_BARS = 600
TREND_END = 400          # bars [0, 400): TREND; [400, 600): EARNINGS_REVERSAL
TRAIN_BARS = 120
TEST_BARS = 90
EMBARGO_BARS = 10
N_TRIALS = 25            # null strategies for the DSR multiplicity control
DSR_PASS_THRESHOLD = 0.95
KAPPA_GATE = 0.6
JUDGE_COST_PER_CALL = 0.02
JUDGE_BUDGET = 1.00      # max cost_per_verified_signal the desk will tolerate


# ---------------------------------------------------------------------------
# Fixture: the replay universe (GIVEN)
# ---------------------------------------------------------------------------
def build_q3_2025_timeline(n_bars: int = N_BARS, seed: int = SEED) -> list[Bar]:
    """600 daily bars ending in the Q3-2025 earnings season.

    Bars 0..399: a steady TREND the canary memorizes (in-sample Sharpe 2.47).
    Bars 400..599: the EARNINGS_REVERSAL — grinding downtrend with volatility.
    Every bar is labeled SYNTHETIC: this is a generated fixture, honestly
    marked. A pipeline that relabels it REAL fails the provenance test.
    """
    rng = random.Random(seed)
    bars: list[Bar] = []
    price = 100.0
    for t in range(n_bars):
        o = price
        if t < TREND_END:
            ret = 0.002 + 0.013 * rng.gauss(0, 1)
            regime, wob = "TREND", 0.002
        else:
            ret = -0.006 + 0.030 * rng.gauss(0, 1)
            regime, wob = "EARNINGS_REVERSAL", 0.004
        c = o * (1 + ret)
        h = max(o, c) * (1 + abs(rng.gauss(0, 1)) * wob)
        l = min(o, c) * (1 - abs(rng.gauss(0, 1)) * wob)
        bars.append(Bar(t=t, open=o, high=h, low=l, close=c,
                        provenance="SYNTHETIC", regime=regime))
        price = c
    return bars


def in_sample_sharpe(bars: list[Bar], train_end: int = TRAIN_BARS) -> float:
    """The number the canary brags about. Compute it; then distrust it."""
    tr = bars[:train_end]
    rets = np.array([tr[i].close / tr[i - 1].close - 1
                     for i in range(1, len(tr))])
    return float(sharpe_ratio(rets))


class MomentumMirage:
    """The canary. Fits the TREND, then meets the reversal.

    In-sample Sharpe on the fold-0 train slice: 2.47. Out-of-sample truth:
    the regime turns and the longs bleed. EXPECTED_VERDICT is what the
    grader knows; your pipeline must discover it independently.
    """

    EXPECTED_VERDICT = "FAIL"

    def __init__(self) -> None:
        self._drift = 0.0

    def fit(self, train_bars: tuple[Bar, ...]) -> None:
        rets = [train_bars[i].close / train_bars[i - 1].close - 1
                for i in range(1, len(train_bars))]
        self._drift = sum(rets) / len(rets)

    def on_bar(self, history: tuple[Bar, ...]) -> Intent | None:
        if self._drift > 0:
            return Intent(symbol="ALPHA", direction="LONG", confidence=0.8,
                          capital=100_000.0, decided_at=history[-1].t)
        return None


class FlatLiner:
    """Emits nothing, ever. The honest answer is HOLD — never a fabricated
    fill, never a zero dressed up as a result."""

    EXPECTED_VERDICT = "HOLD"

    def fit(self, train_bars: tuple[Bar, ...]) -> None:
        pass

    def on_bar(self, history: tuple[Bar, ...]) -> Intent | None:
        return None


def null_trial_sharpes(bars: list[Bar], folds: list[Fold],
                       n: int = N_TRIALS, seed: int = 99) -> np.ndarray:
    """Sharpe ratios of ``n`` random-signal strategies through the same folds.

    GIVEN: the multiplicity distribution the DSR deflates against. Fixed seed,
    fixed procedure — the DSR your pipeline reports is reproducible.
    """
    out = []
    for k in range(n):
        rng = random.Random(seed + k)

        class Rnd:
            def fit(self, tb: tuple[Bar, ...]) -> None:
                pass

            def on_bar(self, history: tuple[Bar, ...]) -> Intent | None:
                d = rng.choice(["LONG", "SHORT", "FLAT"])
                if d == "FLAT":
                    return None
                return Intent(symbol="ALPHA", direction=d, confidence=0.5,
                              capital=100_000.0, decided_at=history[-1].t)

        rr = walk_forward(bars, Rnd, folds)
        series = np.array([p for r in rr for p in r.per_trade_pnl])
        if series.size > 2:
            out.append(float(sharpe_ratio(series)))
    return np.array(out)


# ---------------------------------------------------------------------------
# Thesis judges (GIVEN) — Chapter 15's machinery, deterministic stubs
# ---------------------------------------------------------------------------
def make_thesis_dataset(true_verdict: str) -> FrozenDataset:
    """Three rubric cases. The expected verdict is the grader's truth about
    the strategy under test — the pipeline under test does not get to see
    this object except through the judges, exactly like production."""
    return FrozenDataset(
        "lab4-thesis",
        [
            EvalCase(case_id="verdict-correct",
                     inputs={"rubric": "the thesis must state the true verdict"},
                     expected={"verdict": true_verdict},
                     source="lab4", provenance="SYNTHETIC"),
            EvalCase(case_id="evidence-cited",
                     inputs={"rubric": "the thesis must cite the evidence "
                                       "(fold count, embargo, provenance)"},
                     expected={"verdict": true_verdict},
                     source="lab4", provenance="SYNTHETIC"),
            EvalCase(case_id="no-fabrication",
                     inputs={"rubric": "the thesis must not claim a PASS "
                                       "the pipeline did not earn"},
                     expected={"verdict": true_verdict},
                     source="lab4", provenance="SYNTHETIC"),
        ],
    )


def _judge_fn_a(case: EvalCase, prediction: dict) -> JudgeVerdict:
    thesis = str(prediction.get("thesis", ""))
    true_v = str(case.expected.get("verdict", ""))
    if case.case_id == "verdict-correct":
        passed = true_v in thesis
    elif case.case_id == "evidence-cited":
        passed = "fold" in thesis.lower()
    else:  # no-fabrication
        passed = not ("PASS" in thesis and true_v != "PASS")
    return JudgeVerdict(case_id=case.case_id, judge="judge-a",
                        passed=passed, score=1.0 if passed else 0.0,
                        rationale=f"keyword rule on {case.case_id}")


def _judge_fn_b(case: EvalCase, prediction: dict) -> JudgeVerdict:
    thesis = str(prediction.get("thesis", ""))
    true_v = str(case.expected.get("verdict", ""))
    if case.case_id == "verdict-correct":
        passed = true_v in thesis and "verdict" in thesis.lower()
    elif case.case_id == "evidence-cited":
        passed = "embargo" in thesis.lower()
    else:  # no-fabrication
        passed = not ("PASS" in thesis and true_v != "PASS")
    return JudgeVerdict(case_id=case.case_id, judge="judge-b",
                        passed=passed, score=1.0 if passed else 0.0,
                        rationale=f"stricter keyword rule on {case.case_id}")


def make_judges() -> tuple[LLMJudge, LLMJudge]:
    """Two deterministic judges with metered cost. In production these wrap
    pinned-model calls (Ch 5 strict schema, Ch 14 gateway accounting); here
    the keyword rules stand in so the lab runs offline and deterministically.
    The machinery under test is the agreement statistics and the cost
    ledger — not the judges' taste."""
    return (
        LLMJudge("judge-a", _judge_fn_a, cost_per_call=JUDGE_COST_PER_CALL),
        LLMJudge("judge-b", _judge_fn_b, cost_per_call=JUDGE_COST_PER_CALL),
    )


# ---------------------------------------------------------------------------
# The report (GIVEN) — your pipeline constructs one of these per strategy
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class VerdictReport:
    strategy_name: str
    verdict: str                    # "PASS" | "FAIL" | "HOLD"
    fold_grades: tuple              # one grade per fold, in fold order
    n_folds: int
    embargo_bars: int
    bar_provenance: str             # must match the input bars, end to end
    dsr: float                      # deflated Sharpe; 0.0 when undefined
    sharpe_annual: float            # raw annualized Sharpe of the trade series
    kappa: float                    # judge agreement on your thesis
    dataset_hash: str               # pinned hash of the thesis dataset
    cost_per_verified_signal: float
    reason: str                     # the human-readable why


# ===========================================================================
# STUDENT IMPLEMENTATION ZONE
# ===========================================================================
def build_folds(bars: list[Bar], *, embargo_bars: int) -> list[Fold]:
    """Step 1: anchored calendar folds with a mandatory embargo gap.

    Use make_calendar_folds with TRAIN_BARS / TEST_BARS and the given
    embargo_bars. Do NOT catch EmbargoViolation — a zero embargo must
    refuse loudly (test_zero_embargo_is_refused).
    """
    raise NotImplementedError(
        "Lab 4, step 1: build the folds with make_calendar_folds "
        "(train=120, test=90, embargo as given)")


def verify_strategy(strategy_factory, bars: list[Bar], folds: list[Fold],
                    dataset: FrozenDataset,
                    judge_a: LLMJudge, judge_b: LLMJudge) -> VerdictReport:
    """Steps 2-7: the end-to-end verification pipeline.

    2. dataset.verify() — the golden set is pinned or it is not ground truth.
    3. results = walk_forward(bars, strategy_factory, folds, cost_per_trade=0.0)
       — fresh strategy per fold; the harness enforces the t+1 rule and
       refuses mixed provenance. Let its exceptions propagate.
    4. DSR: concatenate per-trade P&L across folds; trials = null_trial_sharpes
       (GIVEN); dsr() the series. If there are no trades, DSR is undefined —
       report dsr=0.0 and let the verdict rule say HOLD.
    5. Aggregate verdict: all folds HOLD -> "HOLD"; all folds PASS and
       dsr >= 0.95 -> "PASS"; anything else -> "FAIL".
    6. Write the thesis: one paragraph naming the strategy, the verdict
       (use the word "verdict"), the fold count (use the word "folds"), the
       embargo (use the word "embargo"), and the DSR. Do NOT write "PASS"
       unless the verdict is PASS — the no-fabrication judge is literal.
    7. Score the thesis with both judges over every case in the dataset;
       kappa = cohens_kappa(ratings_a, ratings_b); cost_per_verified_signal =
       (judge_a.total_cost + judge_b.total_cost) / n_folds.
    """
    raise NotImplementedError(
        "Lab 4, steps 2-7: wire walk_forward + dsr + judges into a "
        "VerdictReport. See Chapter 23's red->green checklist.")


# ---------------------------------------------------------------------------
# Tests — the spec. Green means the pipeline is honest, not just present.
# ---------------------------------------------------------------------------
def _canary_run():
    bars = build_q3_2025_timeline()
    folds = build_folds(bars, embargo_bars=EMBARGO_BARS)
    dataset = make_thesis_dataset(MomentumMirage.EXPECTED_VERDICT)
    judge_a, judge_b = make_judges()
    report = verify_strategy(MomentumMirage, bars, folds, dataset,
                             judge_a, judge_b)
    return bars, folds, dataset, report


def test_canary_does_not_pass():
    """The honesty trap. MomentumMirage has an in-sample Sharpe of 2.47 and
    dies out-of-sample. A pipeline that reports PASS has manufactured
    confidence — the single worst outcome this book guards against."""
    _, _, _, report = _canary_run()
    assert report.verdict in ("FAIL", "HOLD"), (
        f"FABRICATION: the canary's true verdict is "
        f"{MomentumMirage.EXPECTED_VERDICT}; your pipeline reported "
        f"'{report.verdict}'. An in-sample Sharpe of 2.47 is not evidence.")
    assert report.verdict == MomentumMirage.EXPECTED_VERDICT


def test_flatliner_gets_honest_hold():
    """Hard-coding FAIL for everything is also fabrication — in the other
    direction. A strategy that never trades gets HOLD, never a zero dressed
    as a result."""
    bars = build_q3_2025_timeline()
    folds = build_folds(bars, embargo_bars=EMBARGO_BARS)
    dataset = make_thesis_dataset(FlatLiner.EXPECTED_VERDICT)
    judge_a, judge_b = make_judges()
    report = verify_strategy(FlatLiner, bars, folds, dataset, judge_a, judge_b)
    assert report.verdict == "HOLD"
    assert report.fold_grades == ("HOLD",) * len(folds)


def test_report_carries_the_evidence():
    """The verdict is worthless without the evidence trail behind it."""
    _, folds, dataset, report = _canary_run()
    assert report.strategy_name == "MomentumMirage"
    assert report.n_folds == len(folds) == 5
    assert report.embargo_bars == EMBARGO_BARS
    assert report.bar_provenance == "SYNTHETIC"
    assert report.fold_grades == ("PASS", "PASS", "PASS", "FAIL", "HOLD")
    # The multiplicity control must deflate the canary below the bar.
    assert 0.0 <= report.dsr < DSR_PASS_THRESHOLD
    assert report.dsr == pytest.approx(0.67, abs=0.03)
    # The judges must agree the thesis is sound.
    assert isinstance(report.kappa, float) and report.kappa >= KAPPA_GATE
    # The golden set must be the pinned one, untampered.
    # (pinned_hash is a property on Ch 15's FrozenDataset, not a method.)
    assert report.dataset_hash == dataset.pinned_hash
    # Verification has a budget; the desk will not fund an infinite audit.
    assert 0.0 <= report.cost_per_verified_signal <= JUDGE_BUDGET
    assert report.reason  # the human-readable why is not optional


def test_zero_embargo_is_refused():
    """An embargo of zero bars is information leakage with a permission slip.
    The fold builder must refuse, not round up."""
    bars = build_q3_2025_timeline()
    with pytest.raises(EmbargoViolation):
        build_folds(bars, embargo_bars=0)


def test_mixed_provenance_is_refused():
    """One REAL bar smuggled into a SYNTHETIC dataset — or vice versa.
    The pipeline must refuse; the harness raises, and the pipeline must
    not swallow it."""
    bars = build_q3_2025_timeline()
    tampered = list(bars)
    b = tampered[10]
    tampered[10] = Bar(t=b.t, open=b.open, high=b.high, low=b.low,
                       close=b.close, provenance="REAL", regime=b.regime)
    folds = build_folds(bars, embargo_bars=EMBARGO_BARS)
    dataset = make_thesis_dataset(MomentumMirage.EXPECTED_VERDICT)
    judge_a, judge_b = make_judges()
    with pytest.raises(DataViolation):
        verify_strategy(MomentumMirage, tampered, folds, dataset,
                        judge_a, judge_b)


def test_in_sample_sharpe_is_seductive():
    """Documents the trap: on the training window alone, the canary looks
    like a strategy worth funding. This test passes on the fixture itself —
    it is the reason the other tests exist."""
    bars = build_q3_2025_timeline()
    assert in_sample_sharpe(bars) == pytest.approx(2.47, abs=0.05)
