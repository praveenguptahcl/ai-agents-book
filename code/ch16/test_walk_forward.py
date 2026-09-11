"""Adversarial tests for walk_forward.py.

Every test is an attack on the protocol's honesty: peeking strategies,
missing embargoes, test-data leakage into fit, orders disguised as intents,
mislabeled decisions, unlabeled bars. The harness must refuse, detect, or
report honestly — never silently comply.
"""

import pytest

from walk_forward import (
    Bar,
    ContractViolation,
    DataViolation,
    EmbargoViolation,
    Fill,
    Fold,
    FoldGrade,
    FoldResult,
    Intent,
    PurityReport,
    TemporalViolation,
    WalkForwardError,
    check_temporal_purity,
    default_grader,
    grade_fold,
    make_calendar_folds,
    make_regime_folds,
    run_fold,
    walk_forward,
)


# ---------------------------------------------------------------------------
# Fixtures: deterministic bar builders.
# ---------------------------------------------------------------------------
def make_bars(n, *, start_close=100.0, drift=0.5, provenance="REAL", regime="BULL"):
    """Deterministic up-trend bars: close rises by `drift` per bar."""
    bars = []
    for t in range(n):
        close = start_close + drift * t
        bars.append(
            Bar(
                t=t,
                open=close - 0.1,
                high=close + 0.2,
                low=close - 0.3,
                close=close,
                provenance=provenance,
                regime=regime,
            )
        )
    return bars


def make_known_open_bars(n):
    """Bars with open[t] = 100 + t exactly — for asserting the t+1 rule."""
    return [
        Bar(t=t, open=100.0 + t, high=101.0 + t, low=99.0 + t,
            close=100.5 + t, provenance="REAL", regime="BULL")
        for t in range(n)
    ]


class HonestMomentum:
    """LONG when the last close rose, SHORT when it fell. Uses only history."""

    def fit(self, train_bars):
        self.n_train = len(train_bars)

    def on_bar(self, history):
        if len(history) < 2:
            return None
        t = history[-1].t
        direction = "LONG" if history[-1].close > history[-2].close else "SHORT"
        return Intent(symbol="AAA", direction=direction, confidence=0.6,
                      capital=1000.0, decided_at=t)


class PeekingMomentum:
    """Smuggles the full series at construction and peeks at bar t+1."""

    def __init__(self, full_bars):
        self._full = full_bars

    def fit(self, train_bars):
        pass

    def on_bar(self, history):
        t = history[-1].t
        future_close = self._full[t + 1].close  # the cheat
        direction = "LONG" if future_close > history[-1].close else "SHORT"
        return Intent(symbol="AAA", direction=direction, confidence=0.9,
                      capital=1000.0, decided_at=t)


class SilentStrategy:
    def fit(self, train_bars):
        pass

    def on_bar(self, history):
        return None


class AlternatingStrategy:
    """Unstable across replays: the first instance says LONG, the second says
    SHORT. Models the stochastic strategy — two identical replays disagree, so
    the purity check must say INCONCLUSIVE, not PASS."""

    _built = 0

    def __init__(self):
        AlternatingStrategy._built += 1
        self.parity = AlternatingStrategy._built % 2

    def fit(self, train_bars):
        pass

    def on_bar(self, history):
        direction = "LONG" if self.parity == 0 else "SHORT"
        return Intent(symbol="AAA", direction=direction, confidence=0.5,
                      capital=100.0, decided_at=history[-1].t)


# ---------------------------------------------------------------------------
# The lookahead lie detector.
# ---------------------------------------------------------------------------
def test_purity_check_catches_the_peeker():
    bars = make_bars(40, drift=0.5)
    report = check_temporal_purity(lambda full: PeekingMomentum(full), bars,
                                   decision_bars=[10, 20, 30])
    assert isinstance(report, PurityReport)
    assert report.passed is False
    assert any("LOOKAHEAD" in n for n in report.notes)


def test_purity_check_passes_the_honest_strategy():
    bars = make_bars(40, drift=0.5)
    report = check_temporal_purity(lambda full: HonestMomentum(), bars, decision_bars=[10, 20, 30])
    assert report.passed is True
    assert report.inconclusive is False


def test_purity_check_is_inconclusive_not_pass_for_randomness():
    AlternatingStrategy._built = 0
    bars = make_bars(40, drift=0.5)
    report = check_temporal_purity(lambda full: AlternatingStrategy(), bars, decision_bars=[10])
    assert report.passed is False
    assert report.inconclusive is True
    assert any("INCONCLUSIVE" in n for n in report.notes)


def test_purity_check_rejects_empty_dataset():
    with pytest.raises(WalkForwardError):
        check_temporal_purity(lambda full: HonestMomentum(), [])


# ---------------------------------------------------------------------------
# Embargo enforcement: fail closed, never shrink silently.
# ---------------------------------------------------------------------------
def test_zero_length_embargo_rejected():
    with pytest.raises(EmbargoViolation):
        Fold(fold_id="bad", train=(0, 20), embargo=(20, 20), test=(20, 30))


def test_broken_train_embargo_chain_rejected():
    with pytest.raises(EmbargoViolation):
        Fold(fold_id="bad", train=(0, 20), embargo=(21, 25), test=(25, 35))


def test_broken_embargo_test_chain_rejected():
    with pytest.raises(EmbargoViolation):
        Fold(fold_id="bad", train=(0, 20), embargo=(20, 24), test=(26, 35))


def test_make_calendar_folds_enforces_embargo():
    folds = make_calendar_folds(100, train_bars=40, test_bars=10, embargo_bars=5)
    for f in folds:
        assert f.embargo[1] - f.embargo[0] == 5
        assert f.train[1] == f.embargo[0] == f.embargo[0]
        assert f.embargo[1] == f.test[0]


def test_make_calendar_folds_refuses_impossible_geometry():
    with pytest.raises((EmbargoViolation, WalkForwardError)):
        make_calendar_folds(10, train_bars=40, test_bars=10, embargo_bars=5)


# ---------------------------------------------------------------------------
# Boundary leakage: fit sees the train slice and nothing else.
# ---------------------------------------------------------------------------
def test_fit_never_sees_test_or_embargo_bars():
    bars = make_bars(100)
    folds = make_calendar_folds(100, train_bars=40, test_bars=10, embargo_bars=5)
    fold = folds[0]

    seen = {}

    class Recording(HonestMomentum):
        def fit(self, train_bars):
            seen["idx"] = tuple(b.t for b in train_bars)

    run_fold(bars, Recording(), fold)
    assert max(seen["idx"]) < fold.embargo[0]
    assert min(seen["idx"]) == fold.train[0]


def test_walk_forward_uses_a_fresh_strategy_per_fold():
    bars = make_bars(120)
    folds = make_calendar_folds(120, train_bars=40, test_bars=10, embargo_bars=5)
    created = []

    def factory():
        s = HonestMomentum()
        created.append(s)
        return s

    walk_forward(bars, factory, folds[:2])
    assert len(created) == 2  # no fit-state leaks from fold 0 into fold 1


# ---------------------------------------------------------------------------
# The t+1 rule: decided on bar t, executed at bar t+1's open. Never earlier.
# ---------------------------------------------------------------------------
def test_execution_happens_at_next_bar_open():
    bars = make_known_open_bars(60)
    folds = make_calendar_folds(60, train_bars=30, test_bars=10, embargo_bars=5)
    fold = folds[0]
    te_s = fold.test[0]

    class OneShot(HonestMomentum):
        def on_bar(self, history):
            t = history[-1].t
            if t == te_s:
                return Intent(symbol="AAA", direction="LONG", confidence=0.9,
                              capital=1000.0, decided_at=t)
            return None

    result = run_fold(bars, OneShot(), fold)
    assert result.n_fills == 1
    # price must be open[t+1], not close[t] and not open[t]
    assert result.per_trade_pnl, "expected a recorded trade"
    # reconstruct: qty = 1000 / open[te_s+1]; exit at close of last test bar
    expected_price = 100.0 + (te_s + 1)
    qty = 1000.0 / expected_price
    exit_price = bars[fold.test[1] - 1].close
    assert result.per_trade_pnl[0] == pytest.approx(qty * (exit_price - expected_price))


def test_decision_on_final_test_bar_is_dropped_not_fabricated():
    bars = make_known_open_bars(60)
    folds = make_calendar_folds(60, train_bars=30, test_bars=10, embargo_bars=5)
    fold = folds[0]
    last_t = fold.test[1] - 1

    class LastBarOnly(HonestMomentum):
        def on_bar(self, history):
            t = history[-1].t
            if t == last_t:
                return Intent(symbol="AAA", direction="LONG", confidence=0.9,
                              capital=1000.0, decided_at=t)
            return None

    result = run_fold(bars, LastBarOnly(), fold)
    assert result.dropped_no_next_bar == 1
    assert result.n_fills == 0
    assert result.verdict == "HOLD"  # honest flat, not a fabricated zero-fill PASS


# ---------------------------------------------------------------------------
# Honest reporting: HOLD means flat, and flat is a result.
# ---------------------------------------------------------------------------
def test_empty_signal_fold_reports_hold():
    bars = make_bars(60)
    folds = make_calendar_folds(60, train_bars=30, test_bars=10, embargo_bars=5)
    result = run_fold(bars, SilentStrategy(), folds[0])
    assert result.verdict == "HOLD"
    assert result.net_pnl == 0.0
    assert result.n_fills == 0


def test_losing_fold_reports_fail_not_hold():
    bars = make_bars(60, drift=-2.0)  # steady downtrend; always-LONG loses
    folds = make_calendar_folds(60, train_bars=30, test_bars=10, embargo_bars=5)

    class AlwaysLong(HonestMomentum):
        def on_bar(self, history):
            t = history[-1].t
            return Intent(symbol="AAA", direction="LONG", confidence=0.9,
                          capital=1000.0, decided_at=t)

    result = run_fold(bars, AlwaysLong(), folds[0])
    assert result.n_fills > 0
    assert result.net_pnl < 0
    assert result.verdict == "FAIL"


def test_flat_intent_counts_but_never_fills():
    bars = make_bars(60)
    folds = make_calendar_folds(60, train_bars=30, test_bars=10, embargo_bars=5)

    class AlwaysFlat(HonestMomentum):
        def on_bar(self, history):
            return Intent(symbol="AAA", direction="FLAT", confidence=1.0,
                          capital=1000.0, decided_at=history[-1].t)

    result = run_fold(bars, AlwaysFlat(), folds[0])
    assert result.n_intents > 0
    assert result.n_fills == 0
    assert result.verdict == "HOLD"


def test_costs_are_applied_per_trade():
    bars = make_bars(60, drift=1.0)
    folds = make_calendar_folds(60, train_bars=30, test_bars=10, embargo_bars=5)
    plain = run_fold(bars, HonestMomentum(), folds[0], cost_per_trade=0.0)
    costly = run_fold(bars, HonestMomentum(), folds[0], cost_per_trade=5.0)
    assert costly.costs == pytest.approx(5.0 * costly.n_fills)
    assert costly.net_pnl == pytest.approx(plain.net_pnl - costly.costs)


# ---------------------------------------------------------------------------
# Contract enforcement: intentions only, labeled honestly, bars labeled too.
# ---------------------------------------------------------------------------
def test_order_dict_disguised_as_intent_is_refused():
    bars = make_bars(60)
    folds = make_calendar_folds(60, train_bars=30, test_bars=10, embargo_bars=5)

    class OrderSneaker(HonestMomentum):
        def on_bar(self, history):
            return {"order": {"symbol": "AAA", "qty": 10, "side": "buy"}}  # not an Intent

    with pytest.raises(ContractViolation):
        run_fold(bars, OrderSneaker(), folds[0])


def test_mislabeled_decided_at_is_refused():
    bars = make_bars(60)
    folds = make_calendar_folds(60, train_bars=30, test_bars=10, embargo_bars=5)

    class Mislabeler(HonestMomentum):
        def on_bar(self, history):
            t = history[-1].t
            return Intent(symbol="AAA", direction="LONG", confidence=0.9,
                          capital=1000.0, decided_at=t - 1)  # lies about when it decided

    with pytest.raises(TemporalViolation):
        run_fold(bars, Mislabeler(), folds[0])


def test_unlabeled_bar_is_refused_at_construction():
    with pytest.raises(DataViolation):
        Bar(t=0, open=100, high=101, low=99, close=100.5,
            provenance="REAL-ISH", regime="BULL")


def test_impossible_ohlc_is_refused():
    with pytest.raises(DataViolation):
        Bar(t=0, open=100, high=90, low=99, close=100.5,
            provenance="REAL", regime="BULL")


def test_mixed_provenance_dataset_is_refused():
    bars = make_bars(60, provenance="REAL")
    bars[50] = Bar(t=50, open=100, high=101, low=99, close=100.5,
                   provenance="SYNTHETIC", regime="BULL")
    folds = make_calendar_folds(60, train_bars=30, test_bars=10, embargo_bars=5)
    with pytest.raises(DataViolation):
        run_fold(bars, HonestMomentum(), folds[0])


def test_noncontiguous_bars_are_refused():
    bars = make_bars(60)
    bars = bars[:30] + bars[31:]  # drop bar 30 -> t no longer matches position
    folds = make_calendar_folds(59, train_bars=30, test_bars=10, embargo_bars=5)
    with pytest.raises(DataViolation):
        run_fold(bars, HonestMomentum(), folds[0])


# ---------------------------------------------------------------------------
# Regime-aware folds.
# ---------------------------------------------------------------------------
def test_regime_folds_cut_at_boundaries():
    bars = make_bars(30, regime="BULL") + make_bars(30, regime="BEAR")
    # rebuild with correct contiguous t (make_bars restarts t at 0 per call)
    rebuilt = []
    for i, b in enumerate(bars):
        rebuilt.append(Bar(t=i, open=b.open, high=b.high, low=b.low, close=b.close,
                           provenance=b.provenance, regime=b.regime))
    folds = make_regime_folds(rebuilt, embargo_bars=5)
    assert folds, "expected at least one regime fold"
    for f in folds:
        te_s, te_e = f.test
        regimes = {rebuilt[i].regime for i in range(te_s, te_e)}
        assert len(regimes) == 1, "test window must not straddle a regime boundary"


def test_regime_fold_without_embargo_room_is_skipped_not_shrunk():
    bars = make_bars(4, regime="BULL") + make_bars(10, regime="BEAR")
    rebuilt = [Bar(t=i, open=b.open, high=b.high, low=b.low, close=b.close,
                   provenance=b.provenance, regime=b.regime)
               for i, b in enumerate(bars)]
    # only 4 bars before the BEAR run: embargo of 5 cannot fit -> skip honestly
    with pytest.raises(WalkForwardError):
        make_regime_folds(rebuilt, embargo_bars=5)


# ---------------------------------------------------------------------------
# Seams: Ch 15 graders plug in; Ch 17 consumes to_dict().
# ---------------------------------------------------------------------------
def test_custom_grader_overrides_the_default():
    bars = make_bars(60, drift=1.0)
    folds = make_calendar_folds(60, train_bars=30, test_bars=10, embargo_bars=5)
    strict = lambda r: FoldGrade("FAIL", "house policy: nothing auto-passes")
    result = run_fold(bars, HonestMomentum(), folds[0], grader=strict)
    assert result.verdict == "FAIL"


def test_grade_fold_seam_accepts_any_callable():
    bars = make_bars(60, drift=1.0)
    folds = make_calendar_folds(60, train_bars=30, test_bars=10, embargo_bars=5)
    result = run_fold(bars, HonestMomentum(), folds[0])
    grade = grade_fold(result, default_grader(min_net_edge=10_000.0))
    assert grade.grade == "FAIL"  # edge too high -> honest FAIL


def test_to_dict_is_the_ch17_contract():
    bars = make_bars(60, drift=1.0)
    folds = make_calendar_folds(60, train_bars=30, test_bars=10, embargo_bars=5)
    result = run_fold(bars, HonestMomentum(), folds[0])
    d = result.to_dict()
    assert isinstance(d["per_trade_pnl"], list)
    assert len(d["per_trade_pnl"]) == d["n_fills"]
    for key in ("fold_id", "verdict", "net_pnl", "gross_pnl", "costs",
                "embargo_bars", "train_bars", "test_bars", "bar_provenance"):
        assert key in d


def test_fills_are_labeled_synthetic():
    bars = make_bars(60, drift=1.0, provenance="REAL")
    folds = make_calendar_folds(60, train_bars=30, test_bars=10, embargo_bars=5)
    result = run_fold(bars, HonestMomentum(), folds[0])
    assert result.bar_provenance == "REAL"
    assert result.n_fills > 0
    # fills are synthetic by construction (Fill.provenance defaults to SYNTHETIC)
    assert Fill.__dataclass_fields__["provenance"].default == "SYNTHETIC"


def test_purity_check_default_target_is_not_a_noop():
    # Regression: the default target was once [len(bars) - 1]. _perturb_future
    # only modifies bars strictly AFTER after_t, so targeting the final bar
    # left zero bars to perturb — the smuggled copy was identical to the
    # original and the lie detector silently passed every cheater when
    # decision_bars was omitted. The default must target a bar that HAS a
    # future to perturb.
    bars = make_bars(40, drift=0.5)
    report = check_temporal_purity(lambda full: PeekingMomentum(full), bars)
    assert report.passed is False
    assert any("LOOKAHEAD" in n for n in report.notes)


def test_purity_check_default_target_passes_honest_strategy():
    # The fixed default must not manufacture false positives: an honest
    # strategy still passes when decision_bars is omitted.
    bars = make_bars(40, drift=0.5)
    report = check_temporal_purity(lambda full: HonestMomentum(), bars)
    assert report.passed is True
