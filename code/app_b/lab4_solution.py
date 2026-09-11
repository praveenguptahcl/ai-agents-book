"""Lab 4 answer key (Appendix B) — the reference verification pipeline.

The capstone: Ch 16's walk-forward (the temporal protocol) + Ch 17's
DSR (the multiplicity control) + Ch 15's judges (the agreement
machinery), wired end to end against a strategy that is lying to you.

The verdict rule is the book's honesty thesis as code:

    all folds HOLD            -> HOLD   (honest flat, never a zero)
    all folds PASS and DSR OK  -> PASS   (earned, not claimed)
    anything else              -> FAIL

The canary (MomentumMirage) has an in-sample Sharpe of 2.47 and dies the
moment the regime turns: its folds grade PASS/PASS/PASS/FAIL/HOLD and
its DSR lands at ~0.98 against 25 null trials — above the 0.95 bar, so
the folds deliver the FAIL. The FlatLiner never trades: every fold grades HOLD, so HOLD.
Nothing is hard-coded: swap in a genuinely good strategy and the same
code reports PASS.

The thesis is written for the judges literally: it must state the true
verdict (use the word "verdict"), cite the fold count and the embargo
(the keyword rules check for "fold" and "embargo"), and must NOT claim
a PASS the pipeline did not earn — the no-fabrication judge fails any
thesis containing "PASS" when the true verdict is not PASS. So the
thesis carries the verdict and the evidence, never the grade table.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))           # the lab's GIVEN fixtures
sys.path.insert(0, str(_HERE.parent))    # ch15 / ch16 / ch17 machinery

from ch15.evaluator import cohens_kappa  # noqa: E402
from ch16.walk_forward import (  # noqa: E402
    make_calendar_folds,
    walk_forward,
)
from ch17.metrics import dsr  # noqa: E402
from test_lab4_verify import (  # noqa: E402 — the lab's GIVEN fixtures
    DSR_PASS_THRESHOLD,
    N_TRIALS,
    TEST_BARS,
    TRAIN_BARS,
    VerdictReport,
    null_trial_sharpes,
)


def build_folds(bars: list, *, embargo_bars: int) -> list:
    """Step 1: anchored calendar folds with a mandatory embargo gap.

    The EmbargoViolation is deliberately NOT caught: a zero embargo is
    information leakage with a permission slip, and the fold builder must
    refuse loudly rather than round up.
    """
    return make_calendar_folds(
        len(bars),
        train_bars=TRAIN_BARS,
        test_bars=TEST_BARS,
        embargo_bars=embargo_bars,
    )


def verify_strategy(strategy_factory, bars: list, folds: list,
                    dataset, judge_a, judge_b) -> VerdictReport:
    """Steps 2-7: the end-to-end verification pipeline."""
    # 2. The golden set is pinned or it is not ground truth. A tampered
    #    dataset raises here, before a single bar is walked.
    dataset.verify()

    # 3. Walk it forward. Fresh strategy instance per fold (the harness
    #    enforces it); the t+1 rule and the provenance check are the
    #    harness's job, and their exceptions propagate — the pipeline
    #    must not swallow a DataViolation.
    results = walk_forward(bars, strategy_factory, folds, cost_per_trade=0.0)
    fold_grades = tuple(r.verdict for r in results)
    n_folds = len(folds)
    bar_provenance = bars[0].provenance
    embargo_bars = folds[0].embargo[1] - folds[0].embargo[0]

    # 4. DSR against the GIVEN null-trial distribution. No trades means
    #    the DSR is undefined — report 0.0 and let the verdict rule say
    #    HOLD. A zero dressed up as a statistic is fabrication.
    series = np.array([p for r in results for p in r.per_trade_pnl],
                      dtype=float)
    if series.size == 0:
        dsr_value, sharpe_annual = 0.0, 0.0
    else:
        trials = null_trial_sharpes(bars, folds)
        out = dsr(series, trials)
        dsr_value = float(out["dsr"])
        sharpe_annual = float(out["sharpe_annual"])

    # 5. The aggregate verdict. Note what it takes to PASS: EVERY fold
    #    green AND the multiplicity control cleared. Anything less is
    #    FAIL — including the canary's three green folds, because the
    #    fourth fold said no, even though the DSR cleared the threshold.
    if all(g == "HOLD" for g in fold_grades):
        verdict = "HOLD"
    elif all(g == "PASS" for g in fold_grades) \
            and dsr_value >= DSR_PASS_THRESHOLD:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    reason = (
        f"fold grades {list(fold_grades)}; DSR {dsr_value:.3f} against "
        f"{DSR_PASS_THRESHOLD} threshold; {n_folds} folds with a "
        f"{embargo_bars}-bar embargo; bars labeled {bar_provenance}; "
        f"annualized Sharpe {sharpe_annual:.2f}"
    )

    # 6. The thesis, written for the judges literally: the strategy, the
    #    verdict (the word "verdict"), the fold count ("folds"), the
    #    embargo ("embargo"), the DSR. It never claims a PASS the
    #    pipeline did not earn — the grade table lives in `reason`,
    #    which the judges never see.
    thesis = (
        f"Strategy {strategy_factory.__name__}: the walk-forward verdict "
        f"is {verdict} across {n_folds} folds with a {embargo_bars}-bar "
        f"embargo. The deflated Sharpe ratio is {dsr_value:.2f} against "
        f"{N_TRIALS} null trials (annualized Sharpe {sharpe_annual:.2f})."
    )

    # 7. Score the thesis with both judges over every rubric case; the
    #    machinery under test is the agreement statistics and the cost
    #    ledger, not the judges' taste.
    prediction = {"thesis": thesis}
    ratings_a, ratings_b = [], []
    for case_id in dataset.case_ids():
        case = dataset.get(case_id)
        ratings_a.append(int(judge_a.judge(case, prediction).passed))
        ratings_b.append(int(judge_b.judge(case, prediction).passed))
    kappa = cohens_kappa(ratings_a, ratings_b)
    cost_per_verified_signal = (
        (judge_a.total_cost + judge_b.total_cost) / n_folds
    )

    return VerdictReport(
        strategy_name=strategy_factory.__name__,
        verdict=verdict,
        fold_grades=fold_grades,
        n_folds=n_folds,
        embargo_bars=embargo_bars,
        bar_provenance=bar_provenance,
        dsr=dsr_value,
        sharpe_annual=sharpe_annual,
        kappa=kappa,
        dataset_hash=dataset.pinned_hash,  # property on Ch 15's FrozenDataset
        cost_per_verified_signal=cost_per_verified_signal,
        reason=reason,
    )
