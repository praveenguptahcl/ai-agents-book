# Chapter 16: Walk-Forward Verification

*Part V: Evidence & Verification*

---

The backtest said Sharpe 3.2. It said 34% annualized, max drawdown 4%, win rate 61%. The desk ran it on Monday. By Friday the strategy was down 11% and the PM was asking whether the backtester had a bug.

It did not have a bug. It had a more dangerous property: it was *correct about the past*. Every number it reported was a faithful description of what would have happened — if the strategy had been allowed to trade with knowledge of the future, on data it had already studied, under the assumption that the market regime that produced the training data would politely continue. None of those conditions hold on Monday morning. A backtest is a claim about the future, and most backtests are tested the way you would test a student's memory of an exam they already sat: you hand them the answer key and marvel at their recall.

This chapter is the protocol that stops that. Walk-forward verification is temporal validation done honestly: anchored folds, embargo gaps, no-lookahead proofs, regime-aware cuts, and a reporting discipline in which "nothing survived" is a result — the most valuable result the method can produce.

## 16.1 Why in-sample metrics lie

A strategy has degrees of freedom: parameters, thresholds, indicator choices, the decision to trade momentum rather than mean reversion in the first place. Every degree of freedom is an opportunity to fit the noise of the specific sample you trained on. This is not a moral failing; it is arithmetic. Fit enough parameters to a finite sample and you can memorize it the way a student memorizes an exam — perfect recall, zero understanding.

The in-sample Sharpe is therefore not an estimate of future performance. It is an estimate of the strategy's *memory*. The question you actually need answered is different: what happens when this decision procedure meets bars it has never seen, in a regime it was not tuned for, with execution delayed the way execution is always delayed?

That question has a protocol. It has four moving parts — anchor, train, embargo, test — and one rule that governs all of them: **time has an arrow**.

## 16.2 Time has an arrow: why cross-validation is fraud on time series

In ordinary machine learning you validate with k-fold cross-validation: shuffle the data, hold out a fold, train on the rest. On time series this is not validation. It is time travel. Shuffling puts next Thursday's bars in the training set and asks the model to "predict" last Tuesday. The model obliges — it has already seen the answer — and the held-out metrics look wonderful. They are wonderful the way a marked deck is wonderful.

Walk-forward validation respects the arrow. You pick an **anchor** — a point in history where the strategy is "born." You **train** on bars before the anchor. You **test** on bars after it. Then you **roll** the anchor forward and repeat. The strategy never, in any fold, learns from a bar dated after a bar it is tested on. That is the entire idea, and everything else in this chapter is machinery for enforcing it without exceptions, because exceptions are where the lies get in.

## 16.3 The protocol: anchor, train, embargo, test, roll

A walk-forward run is a sequence of **folds**. Each fold is three chained ranges over the bar index space — train, embargo, test — and the chaining is exact: the train range ends where the embargo begins, the embargo ends where the test begins. No gaps, no overlaps. The `Fold` object enforces this at construction, because a fold that does not chain is not a fold; it is a wish:

```python
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
```

*(Verbatim from `code/ch16/walk_forward.py`.)*

Notice what the constructor refuses: a zero-length embargo. The embargo is the gap between the last bar the strategy trained on and the first bar it is tested on, and it exists because information does not respect range boundaries. Labels computed over a horizon (a 20-day forward return, a volatility estimate) smear the future backward into the training data. Features with memory (moving averages, trailing drawdowns) carry the training regime's fingerprints into the first test bars. The embargo is the quarantine ward between them: bars that belong to neither train nor test, whose only job is to absorb the leakage.

**Sizing the embargo** is not guesswork. Two quantities set it: the *label horizon* (if your labels look H bars forward, the embargo must be at least H bars — the last H training labels peeked past the train boundary) and the *autocorrelation decay* of your features (if a feature's memory persists for M bars, the first M test bars are still breathing training air). The honest rule: embargo ≥ max(label horizon, feature memory), rounded up, never down. An embargo you shrink to "get more test data" is not an optimization. It is a leak you chose.

This is the purged, embargoed walk-forward of López de Prado's *Advances in Financial Machine Learning* — the rare piece of quant methodology that treats leakage as the default rather than the accident. We implement it here as construction-time law, not documentation advice, because advice is what people skip under deadline.

A worked sizing, because this is where desks actually get it wrong. Suppose the strategy's labels are 20-bar forward returns (label horizon H = 20) and its slowest feature is a 30-bar trailing average (memory M ≈ 30). The embargo must be at least max(20, 30) = 30 bars — and the desk rounds to 35, because the cost of five extra embargo bars is a slightly shorter test window, while the cost of five too few is a backtest that trained on its own exam. If that embargo "doesn't fit" the dataset, the answer is a shorter history of *valid* folds, not a shorter embargo. Data you cannot validate honestly is data you do not have.

## 16.4 The t+1 rule: temporal isolation at execution

The book's standing invariant — a signal decided on bar `t` cannot execute before bar `t+1`'s open — is not just a trading rule. It is the temporal-isolation half of the whole edifice (Ch 2's ODAV loop, Ch 10's executor). In the walk-forward harness it is enforced in the simulation loop itself:

```python
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
```

*(Verbatim from `code/ch16/walk_forward.py`.)*

Read the three enforcements. First, `strategy.on_bar(tuple(bars[: t + 1]))`: the strategy receives a *fresh tuple* of bars through the current bar. The future is not hidden from it; the future is *absent*. There is no flag to forget, no view to misconfigure — the object the strategy holds simply ends at `t`. Second, `_check_intent(raw, t)`: the intent must be labeled with the bar it was decided on, and it must be an `Intent`, not an order, not a dict, not a hopeful string. Strategies emit intentions; the executor disposes (Ch 4, Ch 10). Third, the drop: a decision made on the final test bar has no `t+1` inside the test window, so it is *dropped and counted*, not filled at a fabricated price. A backtester that invents a fill where no bar exists is not optimistic. It is fictional.

Every fill the loop creates carries `provenance="SYNTHETIC"` by construction, while the input bars carry whatever the dataset declared — REAL or SYNTHETIC — and the harness refuses a dataset that mixes the two without saying so. The honesty labels from Ch 9's evidence spine start here, at the data.

## 16.5 The lie detector: proving the strategy never peeked

Structural prevention — truncated tuples — stops the honest mistake: the researcher who indexed one bar too far. It does not stop the dishonest architecture: a strategy object that captured the *full* dataset in its closure at construction time and consults it during `on_bar`. The views you hand it are clean; the copy it smuggled is not. No amount of truncating the argument catches that, because the argument was never the attack surface. The closure was.

So the harness runs a second check, and its logic is worth understanding because it generalizes far beyond trading. **A decision made on bar `t` must be invariant to perturbation of bars after `t`.** The check builds the strategy twice: once with the real full series, once with a series whose post-`t` bars have been randomly perturbed. Both instances are replayed on *identical* truncated views. If the decisions differ, the strategy's bar-`t` decision depended on bars after `t` — it looked:

```python
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
    targets = list(decision_bars) if decision_bars is not None else [len(bars) - 1]
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
```

*(Verbatim from `code/ch16/walk_forward.py`.)*

Three details deserve attention. First, the factory receives the full series *on purpose* — the check models the attacker's capability, then perturbs exactly what the attacker would have smuggled. An honest strategy ignores the argument and passes; the test suite's `PeekingMomentum`, which reads `self._full[t + 1].close`, fails loudly. Second, the determinism pre-check: two identical replays must agree before the perturbation means anything. A stochastic strategy gets INCONCLUSIVE — the check refuses to bless what it cannot see through, which is the honest-reporting discipline applied to the checker itself. Third, the perturbation is seeded and bounded (±5% by default): reproducible, and small enough that a decision genuinely based on bar-`t` information should not flip.

Run this check in CI on every strategy, every commit. It costs milliseconds. The lookahead bug it catches costs careers.

## 16.6 Regime-aware folds: cut where the market cuts

Calendar folds — train on Q1, test on Q2 — assume the market respects quarters. It does not. A strategy trained in a grinding bull market and tested in the first month of a rate shock is not being validated; it is being ambushed by a distribution shift the fold design pretended was uniform. Regime-aware folds cut where the market actually changes character: train on earlier regimes, embargo across the boundary, test on the next regime:

```python
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
```

*(Verbatim from `code/ch16/walk_forward.py`.)*

The `continue` is the whole point. When a regime boundary arrives too early in the dataset to fit a real embargo, the fold is *skipped* — not built with a two-bar embargo, not built with a warning comment, skipped. A validation suite that silently shrinks its own quarantine to fit the data is laundering leakage. The test suite asserts this: a dataset with only four bars before the regime change and a five-bar embargo requirement produces no fold at all, and the constructor says so instead of complying.

Regime labels themselves come from wherever the desk's regime process lives — the point of this chapter is not to bless a particular classifier but to make the fold boundaries *mean* something. A test window that straddles a regime change is two different markets averaged into one verdict; the fold above refuses to produce one.

## 16.7 The worked example: AlphaForge through the 2025 correction

The desk's momentum strategy looked superb on 2023–2024 bars: Sharpe 2.1 in-sample, tidy equity curve, the kind of chart that gets shown in meetings. Then the walk-forward ran — anchored folds, five-bar embargoes, regime cuts at the volatility break — and the 2025-correction test windows told a different story. The strategy that surfed the trend could not survive the chop: whipsawed entries, exits at the worst bars, costs eating the few winners.

Fold by fold, the verdicts came back:

| Fold | Test window | Verdict | Net (after costs) |
|---|---|---|---|
| fold-00 | calm trend | FAIL | −1.8% |
| fold-01 | first chop | FAIL | −4.2% |
| fold-02 | deep correction | HOLD | 0.0% (no qualifying intents) |
| regime-HIGH-VOL-01 | volatility break | FAIL | −6.9% |

The HOLD matters as much as the FAILs — in one fold the strategy emitted no qualifying intents at all, and the harness reported honest flat instead of hallucinating a zero or, worse, a small win from a fill that never happened. Net across folds: negative after costs.

This is the discipline working as designed, and it mirrors what happened on the author's own platform when 250 candidate modules went through the same protocol with a five-bar embargo: 39 raw PASS, 84 FAIL, 127 HOLD — and after multiplicity control, zero survived. Read that again, because it is the most important sentence in this chapter: **a validation harness that returns "zero survive" is not broken. It is honest.** The 127 HOLDs are not missing data; they are strategies that, faced with unseen bars, had nothing true to say, and said nothing. A backtester that reports flat when the strategy is flat is worth more than one that reports Sharpe 3.2.

The desk killed the momentum strategy that quarter. Not with drama — with a verdict table. That is what the method is for: converting arguments about taste into rows in a table, where the rows were produced by a protocol nobody in the room can quietly adjust.

## 16.8 What walk-forward cannot catch

Honesty about the method's limits is part of the method. Walk-forward verification is the strongest temporal validation available, and it still cannot do four things:

**1. It cannot validate against regimes it has never seen.** Every fold's test window is drawn from history. A strategy validated on every regime in the dataset can still meet a genuinely novel regime on Monday — a market structure that did not exist in the sample. Walk-forward bounds the *known* unknowns; the unknown unknowns remain. The honest response is position sizing and kill switches (Ch 11), not a bigger backtest.

**2. It does not correct for multiple testing.** Run 250 strategies through this protocol and the luckiest few will post passing folds. Walk-forward tells you what happened on unseen bars *per strategy*; it says nothing about how many strategies you tried. The garden of forking paths — the researcher's own degrees of freedom, the strategies tried and quietly discarded — is invisible to every fold. That correction is Ch 17's entire job.

**3. It assumes the cost model.** The harness deducts `cost_per_trade` per fill, but real costs are adversarial: spreads widen exactly when the strategy most wants to trade, slippage correlates with the signal. A backtest with a fixed cost is a lower bound on pain, not an estimate of it. Size the cost parameter pessimistically and re-run; if the verdict flips, the strategy was never real.

**4. It validates the procedure, not the researcher.** The protocol is airtight against the strategy; it is helpless against the human who runs it twelve times with twelve parameter grids and reports the best. No code in this chapter can detect that. Only the evidence spine (Ch 9) can — every run logged, every parameter set recorded, the whole garden of forking paths on the record. Walk-forward without an audit trail is a polygraph with the results emailed to the suspect.

## 16.9 What this chapter does not do: the seams

Two deliberate boundaries, because a chapter that tries to be the whole book is a chapter that cannot be tested.

**Grading is Ch 15's job.** This chapter's default grader is deliberately primitive — HOLD when nothing traded, PASS above a net-edge threshold, FAIL otherwise. It exists so the protocol runs standalone. But `run_fold` takes any `grader: Callable[[FoldResult], FoldGrade]`, and `grade_fold` is the single seam through which Ch 15's real graders — deterministic rubrics, statistical thresholds, LLM judges with agreement stats — will score folds. The protocol produces the evidence; the graders render the verdict. (That is also why `walk_forward` builds a *fresh* strategy per fold: fit-state leaking from fold N into fold N+1 is training on the test set with extra steps, and no grader can detect what the protocol allowed.)

**The statistics are Ch 17's job.** Walk-forward tells you what happened on unseen bars. It does not tell you whether what happened *means* anything — and with 250 strategies, one of them will look good by luck alone. That is the multiple-testing problem, and Ch 17's Deflated Sharpe Ratio is the deflator. The seam between the chapters is `FoldResult.to_dict()`: the per-trade net PnL series plus fold metadata (embargo width, train/test sizes, bar provenance), everything the multiplicity math needs and nothing it must recompute. This chapter walks the folds; the next chapter decides whether the walk meant anything.

One foreshadow for the road: the **minimum track-record length** (minTRL) — the number of observations required before a Sharpe estimate is even *eligible* for significance. Most strategies die there, before any ratio is computed. Ch 17 works it by hand.

## 16.10 The checklist

Before any strategy reaches paper trading, the desk requires:

1. **Folds built** — calendar or regime-cut, every fold chaining train → embargo → test, embargo ≥ max(label horizon, feature memory).
2. **Purity checked** — `check_temporal_purity` passes on every strategy, in CI, every commit. INCONCLUSIVE is a stop, not a shrug.
3. **t+1 enforced** — execution at the next bar's open, in the harness and in production (Ch 10). The backtest and the broker must agree on physics.
4. **Provenance labeled** — every bar REAL or SYNTHETIC; every fill SYNTHETIC. Mixed datasets refused.
5. **HOLDs reported** — flat folds in the table, counted, never zeroed, never dropped from the average.
6. **Fresh instance per fold** — no fit-state across folds, asserted by construction.

Miss any one and you do not have a validation. You have a story about the past with charts.

---

*Figure 16.1 — Walk-forward embargo windows (Gantt). Full specification in `figs/ch16-figspec.md`: rolling anchored folds with train/embargo/test shading, the regime-cut variant, and the leakage paths the embargo absorbs.*

---

The folds are walked. The verdicts are in the table, HOLDs included, and no strategy has seen a bar it should not have seen. Now the harder question: of the folds that passed, which ones *mean* anything — and how many of them are just the luckiest of 250 tries?

Chapter 17 is the statistics that deflate self-deception.
