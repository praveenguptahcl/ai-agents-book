"""Walk-forward verification for the AlphaForge paper-trading desk.

Thesis: a backtest is a claim about the future, and claims about the future
must be tested the way the future actually arrives — one bar at a time, with
no peeking. ``walk_forward()`` is the protocol; ``check_temporal_purity()``
is the lie detector.

Temporal invariants (AlphaForge discipline, enforced here, not suggested):
  - Strategies see only bars through the current bar, as fresh tuples.
    Peeking at bar t+1 while deciding on bar t is a ``TemporalViolation``.
  - An intent decided on bar t executes no earlier than bar t+1's open.
  - Every bar is labeled REAL or SYNTHETIC at construction. Fills are always
    SYNTHETIC (paper trading). The harness refuses unlabeled bars.
  - Strategies emit intentions, never orders. Anything else is refused.

The honest-reporting discipline: a fold that produces no qualifying signal
is reported HOLD (honest flat), never zeroed out, never fabricated. "Zero of
N survive" is a *result*, not a failure of the method — Ch 17's DSR then
deflates whatever survives across trials.

Seams:
  - Ch 15 (graders): ``grade_fold(result, grader)`` takes any callable
    ``FoldResult -> FoldGrade``. The default grader is a net-edge threshold;
    Ch 15's real graders plug into the same slot.
  - Ch 17 (PSR/DSR): ``FoldResult.to_dict()`` is the contract — per-trade
    net PnL series plus fold metadata. Ch 17 consumes it; it derives nothing.

Stdlib only: dataclasses, math, random, typing.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from typing import Callable, Literal, Protocol, Sequence

Direction = Literal["LONG", "SHORT", "FLAT"]
Provenance = Literal["REAL", "SYNTHETIC"]
Verdict = Literal["PASS", "FAIL", "HOLD"]


# ---------------------------------------------------------------------------
# Violations. Each is a distinct failure mode with a distinct name, because
# "the backtest failed" is not a diagnosis.
# ---------------------------------------------------------------------------
class WalkForwardError(Exception):
    """Base class for every walk-forward protocol violation."""


class EmbargoViolation(WalkForwardError):
    """A fold with a missing, zero-length, or broken embargo gap."""


class TemporalViolation(WalkForwardError):
    """A strategy touched the future or mislabeled the bar it decided on."""


class ContractViolation(WalkForwardError):
    """A strategy returned something that is not an Intent (e.g. an order)."""


class DataViolation(WalkForwardError):
    """A bar without valid provenance or with impossible OHLC geometry."""


# ---------------------------------------------------------------------------
# Value objects. Frozen: the past does not get edited.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Bar:
    """One price bar. ``provenance`` is mandatory — REAL or SYNTHETIC, no third
    option, no default that lets the caller forget to choose."""

    t: int
    open: float
    high: float
    low: float
    close: float
    provenance: Provenance
    regime: str = "UNKNOWN"

    def __post_init__(self) -> None:
        if self.provenance not in ("REAL", "SYNTHETIC"):
            raise DataViolation(f"bar t={self.t}: provenance must be REAL or SYNTHETIC")
        if self.t < 0:
            raise DataViolation(f"bar t={self.t}: negative index")
        if not (self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high):
            raise DataViolation(f"bar t={self.t}: impossible OHLC geometry")
        if not self.regime:
            raise DataViolation(f"bar t={self.t}: regime label may not be empty")


@dataclass(frozen=True)
class Intent:
    """A trading *intention* — symbol, direction, confidence, capital. Never an
    order. The strategy proposes; the executor (Ch 10) disposes."""

    symbol: str
    direction: Direction
    confidence: float
    capital: float
    decided_at: int

    def __post_init__(self) -> None:
        if self.direction not in ("LONG", "SHORT", "FLAT"):
            raise ContractViolation(f"direction must be LONG/SHORT/FLAT, got {self.direction!r}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ContractViolation(f"confidence {self.confidence} outside [0, 1]")
        if self.capital <= 0:
            raise ContractViolation(f"capital must be positive, got {self.capital}")
        if self.decided_at < 0:
            raise ContractViolation("decided_at must be non-negative")


@dataclass(frozen=True)
class Fold:
    """One anchored walk-forward fold. Ranges are [start, end) bar indices and
    must chain exactly: train -> embargo -> test, no gaps, no overlaps."""

    fold_id: str
    train: tuple[int, int]
    embargo: tuple[int, int]
    test: tuple[int, int]

    def __post_init__(self) -> None:
        tr_s, tr_e = self.train
        em_s, em_e = self.embargo
        te_s, te_e = self.test
        if not (0 <= tr_s < tr_e):
            raise EmbargoViolation(f"{self.fold_id}: empty or inverted train range")
        if tr_e != em_s:
            raise EmbargoViolation(f"{self.fold_id}: train and embargo must chain (gap/overlap)")
        if em_e != te_s:
            raise EmbargoViolation(f"{self.fold_id}: embargo and test must chain (gap/overlap)")
        if em_e - em_s < 1:
            raise EmbargoViolation(f"{self.fold_id}: embargo gap is zero bars — information leaks")
        if te_e - te_s < 1:
            raise EmbargoViolation(f"{self.fold_id}: empty test range")


@dataclass(frozen=True)
class Fill:
    """A paper fill. Provenance is SYNTHETIC by construction — fills are
    simulated, and the label says so."""

    intent: Intent
    executed_at: int
    price: float
    qty: float
    provenance: Provenance = "SYNTHETIC"


@dataclass(frozen=True)
class FoldResult:
    """Everything Ch 17 needs, nothing it must recompute."""

    fold_id: str
    verdict: Verdict
    n_intents: int
    n_fills: int
    dropped_no_next_bar: int
    gross_pnl: float
    costs: float
    net_pnl: float
    per_trade_pnl: tuple[float, ...]
    embargo_bars: int
    train_bars: int
    test_bars: int
    bar_provenance: Provenance  # provenance of the input bars

    def to_dict(self) -> dict:
        """The Ch 17 seam: per-trade series plus fold metadata."""
        return {
            "fold_id": self.fold_id,
            "verdict": self.verdict,
            "n_intents": self.n_intents,
            "n_fills": self.n_fills,
            "gross_pnl": self.gross_pnl,
            "costs": self.costs,
            "net_pnl": self.net_pnl,
            "per_trade_pnl": list(self.per_trade_pnl),
            "embargo_bars": self.embargo_bars,
            "train_bars": self.train_bars,
            "test_bars": self.test_bars,
            "bar_provenance": self.bar_provenance,
        }


# ---------------------------------------------------------------------------
# Strategies. The protocol the harness enforces.
# ---------------------------------------------------------------------------
class Strategy(Protocol):
    def fit(self, train_bars: tuple[Bar, ...]) -> None:
        """Learn from the train slice ONLY. The harness never passes test bars."""

    def on_bar(self, history: tuple[Bar, ...]) -> Intent | None:
        """Decide on the last bar of ``history``. ``history`` is a fresh tuple
        of bars[:t+1] — the future is physically absent, not merely hidden."""


def _check_intent(intent: object, t: int) -> Intent:
    """Intentions only. Orders, dicts, and wishful thinking are refused."""
    if not isinstance(intent, Intent):
        raise ContractViolation(
            f"bar t={t}: strategy returned {type(intent).__name__}, not an Intent — "
            "strategies emit intentions, never orders"
        )
    if intent.decided_at != t:
        raise TemporalViolation(
            f"bar t={t}: intent labeled decided_at={intent.decided_at} — "
            "an intent must be labeled with the bar it was decided on"
        )
    return intent


# ---------------------------------------------------------------------------
# The lookahead lie detector.
#
# Structural prevention (truncated tuples) stops the honest mistake. This
# catches the dishonest one: a strategy that smuggled the full series into
# its closure at construction time and peeks at it during on_bar.
#
# Method: build the strategy twice — once with the real full series, once
# with a series whose FUTURE (bars after t) has been perturbed — then replay
# both on identical truncated views. A decision made on bar t must be
# INVARIANT to perturbation of bars after t. If changing the future changes
# the decision, the strategy looked.
#
# Note the subtlety this encodes: you cannot catch smuggling by perturbing
# what you hand the strategy (it only ever receives truncated views — the
# future is already absent there). You catch it by perturbing what it might
# have SMUGGLED. The factory receives the full series for exactly this
# reason; an honest strategy ignores the argument.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PurityReport:
    passed: bool
    inconclusive: bool
    notes: tuple[str, ...]


def _perturb_future(bars: Sequence[Bar], after_t: int, seed: int, pct: float) -> list[Bar]:
    rng = random.Random(seed)
    out = list(bars)
    for i in range(after_t + 1, len(out)):
        b = out[i]
        new_close = b.close * (1.0 + rng.uniform(-pct, pct))
        out[i] = replace(
            b,
            close=new_close,
            high=max(b.high, new_close),
            low=min(b.low, new_close),
        )
    return out


def _replay(strategy: Strategy, bars: Sequence[Bar], upto_t: int) -> Intent | None:
    intent: Intent | None = None
    for i in range(upto_t + 1):
        raw = strategy.on_bar(tuple(bars[: i + 1]))
        if raw is not None:
            intent = _check_intent(raw, i)
    return intent


def check_temporal_purity(
    strategy_factory: Callable[[Sequence[Bar]], Strategy],
    bars: Sequence[Bar],
    decision_bars: Sequence[int] | None = None,
    *,
    seed: int = 7,
    perturb_pct: float = 0.05,
) -> PurityReport:
    """Fail the fold's strategy if its bar-t decision changes when the future
    changes. ``strategy_factory`` receives the full bar series — the same
    thing a cheating strategy would smuggle — so the check perturbs the
    SMUGGLED copy, not the truncated views (which never contained the future
    anyway). A stochastic strategy (two identical replays disagree) is reported
    INCONCLUSIVE, not PASS — the check cannot see through randomness, and it
    says so instead of blessing it."""
    if not bars:
        raise WalkForwardError("purity check needs at least one bar")
    targets = list(decision_bars) if decision_bars is not None else [max(0, len(bars) - 2)]
    # NOTE: the default targets bar len(bars)-2, never the last bar.
    # _perturb_future only touches bars AFTER after_t; targeting the final
    # bar would leave zero bars to perturb, and the smuggled dataset would
    # be identical to the original — the lie detector would pass every
    # cheating strategy silently. The default must always have future to
    # perturb, or the check is a no-op wearing a lab coat.
    notes: list[str] = []
    failed = False
    inconclusive = False
    for t in targets:
        if not (0 <= t < len(bars)):
            raise WalkForwardError(f"decision bar {t} outside dataset")
        a = _replay(strategy_factory(bars), bars, t)
        b = _replay(strategy_factory(bars), bars, t)
        if a != b:
            inconclusive = True
            notes.append(f"bar t={t}: INCONCLUSIVE — identical replays disagree (stochastic strategy)")
            continue
        smuggled = _perturb_future(bars, t, seed, perturb_pct)
        c = _replay(strategy_factory(smuggled), bars, t)
        if c != a:
            failed = True
            notes.append(f"bar t={t}: LOOKAHEAD — decision changed when the smuggled future was perturbed")
    if not notes:
        notes.append("all checked decision bars invariant to future perturbation")
    return PurityReport(passed=not failed and not inconclusive, inconclusive=inconclusive, notes=tuple(notes))


# ---------------------------------------------------------------------------
# Fold construction.
# ---------------------------------------------------------------------------
def make_calendar_folds(
    n_bars: int,
    *,
    train_bars: int,
    test_bars: int,
    embargo_bars: int,
    step_bars: int | None = None,
) -> list[Fold]:
    """Rolling anchored folds: train -> embargo -> test, stepped forward."""
    if min(train_bars, test_bars, embargo_bars) < 1:
        raise EmbargoViolation("train, test, and embargo must each be >= 1 bar")
    step = step_bars if step_bars is not None else test_bars
    folds: list[Fold] = []
    start, i = 0, 0
    while True:
        tr_e, em_e, te_e = start + train_bars, start + train_bars + embargo_bars, start + train_bars + embargo_bars + test_bars
        if te_e > n_bars:
            break
        folds.append(
            Fold(
                fold_id=f"fold-{i:02d}",
                train=(start, tr_e),
                embargo=(tr_e, em_e),
                test=(em_e, te_e),
            )
        )
        i += 1
        start += step
    if not folds:
        raise WalkForwardError("no folds fit: dataset too short for train+embargo+test")
    return folds


def make_regime_folds(bars: Sequence[Bar], *, embargo_bars: int) -> list[Fold]:
    """Folds cut at regime boundaries instead of calendar quarters: train on
    earlier regimes, embargo, test on the next regime. Folds that cannot fit
    an embargo are skipped honestly — never shrunk silently."""
    if embargo_bars < 1:
        raise EmbargoViolation("embargo must be >= 1 bar")
    runs: list[tuple[str, int, int]] = []  # (regime, start, end)
    for b in bars:
        if runs and runs[-1][0] == b.regime:
            runs[-1] = (runs[-1][0], runs[-1][1], b.t + 1)
        else:
            runs.append((b.regime, b.t, b.t + 1))
    folds: list[Fold] = []
    for k in range(1, len(runs)):
        regime, te_s, te_e = runs[k]
        em_s = te_s - embargo_bars
        if em_s <= 0:
            continue  # not enough history for a real embargo — skip, don't shrink
        folds.append(
            Fold(
                fold_id=f"regime-{regime}-{k:02d}",
                train=(0, em_s),
                embargo=(em_s, te_s),
                test=(te_s, te_e),
            )
        )
    if not folds:
        raise WalkForwardError("no regime folds fit with the requested embargo")
    return folds


# ---------------------------------------------------------------------------
# The protocol itself.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FoldGrade:
    grade: Verdict
    reason: str


GraderFn = Callable[[FoldResult], FoldGrade]


def default_grader(min_net_edge: float = 0.0) -> GraderFn:
    """HOLD when nothing traded (honest flat); PASS above the edge; else FAIL."""

    def grade(result: FoldResult) -> FoldGrade:
        if result.n_fills == 0:
            return FoldGrade("HOLD", "no qualifying intents in the test window — honest flat")
        if result.net_pnl > min_net_edge:
            return FoldGrade("PASS", f"net {result.net_pnl:.2f} above edge {min_net_edge:.2f}")
        return FoldGrade("FAIL", f"net {result.net_pnl:.2f} at or below edge {min_net_edge:.2f}")

    return grade


def grade_fold(result: FoldResult, grader: GraderFn) -> FoldGrade:
    """The Ch 15 seam: any grader — deterministic, statistical, or LLM judge —
    scores a FoldResult through this one callable."""
    return grader(result)


def run_fold(
    bars: Sequence[Bar],
    strategy: Strategy,
    fold: Fold,
    *,
    cost_per_trade: float = 0.0,
    min_net_edge: float = 0.0,
    grader: GraderFn | None = None,
) -> FoldResult:
    """Run one fold. Fit sees the train slice only; decisions see bars[:t+1];
    every intent executes at the NEXT bar's open — the t+1 rule, enforced."""
    tr_s, tr_e = fold.train
    te_s, te_e = fold.test
    if te_e > len(bars):
        raise WalkForwardError(f"{fold.fold_id}: test range exceeds dataset")
    if any(b.t != i for i, b in enumerate(bars)):
        raise DataViolation("bars must be 0-indexed and contiguous — the harness indexes positionally")
    provenance = bars[0].provenance
    if any(b.provenance != provenance for b in bars):
        raise DataViolation("mixed REAL/SYNTHETIC provenance in one fold — label the dataset, not the wish")

    strategy.fit(tuple(bars[tr_s:tr_e]))

    fills: list[Fill] = []
    n_intents = 0
    dropped = 0
    for t in range(te_s, te_e):
        raw = strategy.on_bar(tuple(bars[: t + 1]))
        if raw is None:
            continue
        intent = _check_intent(raw, t)
        n_intents += 1
        if intent.direction == "FLAT":
            continue
        if t + 1 >= te_e:
            dropped += 1  # no next bar inside the test window: no fake fill
            continue
        exec_bar = bars[t + 1]
        price = exec_bar.open  # the t+1 rule: execution at the NEXT bar's open
        qty = intent.capital / price
        fills.append(Fill(intent=intent, executed_at=t + 1, price=price, qty=qty))

    exit_price = bars[te_e - 1].close
    per_trade: list[float] = []
    for f in fills:
        sign = 1.0 if f.intent.direction == "LONG" else -1.0
        per_trade.append(sign * f.qty * (exit_price - f.price) - cost_per_trade)
    costs = cost_per_trade * len(fills)
    gross = sum(per_trade) + costs

    result = FoldResult(
        fold_id=fold.fold_id,
        verdict="HOLD",  # placeholder; the grader assigns the real one below
        n_intents=n_intents,
        n_fills=len(fills),
        dropped_no_next_bar=dropped,
        gross_pnl=gross,
        costs=costs,
        net_pnl=gross - costs,
        per_trade_pnl=tuple(per_trade),
        embargo_bars=fold.embargo[1] - fold.embargo[0],
        train_bars=tr_e - tr_s,
        test_bars=te_e - te_s,
        bar_provenance=provenance,
    )
    g = grader if grader is not None else default_grader(min_net_edge)
    grade = grade_fold(result, g)
    return replace(result, verdict=grade.grade)


def walk_forward(
    bars: Sequence[Bar],
    strategy_factory: Callable[[], Strategy],
    folds: Sequence[Fold],
    **kwargs,
) -> list[FoldResult]:
    """Run every fold with a FRESH strategy instance — fit-state from fold N
    must never contaminate fold N+1. That would be training on the test set
    with extra steps."""
    return [run_fold(bars, strategy_factory(), fold, **kwargs) for fold in folds]
