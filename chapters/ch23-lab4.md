# Lab 4: Walk-Forward Verdict

*Chapter 23. Part VII: Practice. The capstone lab.*

Every trading desk has a graduation ritual — the gauntlet a strategy survives
before it touches money, even paper money. At Meridian-style desks the ritual
has a name whispered like a warning: *the walk-forward.* Most strategies do
not survive it. That is the point.

This lab is the ritual, executable. You will wire three machines you already
own — the walk-forward protocol (Ch 16), the multiplicity control (Ch 17),
and the grading machinery (Ch 15) — into one end-to-end verification pipeline,
and run it against a strategy that is lying to you. The strategy looks
wonderful. Your pipeline must say so, precisely, and then refuse to graduate
it. If your pipeline reports PASS, it fails the lab.

That last sentence is not a trick. It is the job description.

## What you are proving

Chapters 15, 16, and 17 each built one instrument:

- **Ch 16** gave you the *protocol*: anchored folds, mandatory embargo gaps,
  the t+1 execution rule, the lookahead lie detector. Time has an arrow and
  the harness enforces it.
- **Ch 17** gave you the *statistics*: the Probabilistic Sharpe Ratio and
  the Deflated Sharpe Ratio — multiplicity control, so the luckiest of 25
  tries cannot impersonate skill.
- **Ch 15** gave you the *graders*: frozen golden sets, deterministic
  graders, LLM judges measured by Cohen's kappa, and cost-per-verified-success
  as a budget line.

Lab 4 proves the composition. A verification pipeline is not three tools in
a trench coat; it is one pipeline in which each stage consumes the previous
stage's output through a designed seam: `FoldResult.to_dict()` feeds the DSR
math, the frozen dataset pins the judges' ground truth, and the final
`VerdictReport` carries the whole evidence trail. The lab's thesis, stated
once: **a verdict without a reproducible evidence trail is a rumor.**

## The canary

The fixture ships a strategy called `MomentumMirage`. Read its source — it is
short, honest code. It fits the drift of its training window and goes long
when the drift is positive. On its training slice it posts an annualized
Sharpe of **2.47**. There is a test in the lab file that documents exactly
this, and it passes on the fixture itself:

```python
def test_in_sample_sharpe_is_seductive():
    """Documents the trap: on the training window alone, the canary looks
    like a strategy worth funding. This test passes on the fixture itself —
    it is the reason the other tests exist."""
    bars = build_q3_2025_timeline()
    assert in_sample_sharpe(bars) == pytest.approx(2.47, abs=0.05)
```

2.47 is a number that gets strategies funded. It is also, in this case, a
number that describes a world that no longer exists. The replay universe is
600 daily bars: the first 400 are a steady TREND the canary memorizes, and
the last 200 are the EARNINGS_REVERSAL — a grinding downtrend with
volatility, the Q3 earnings season as a regime change. The canary's longs
bleed from the moment the regime turns. Walk it forward honestly and you get
five folds — PASS, PASS, PASS, FAIL, HOLD — and a deflated Sharpe of 0.67
against the 0.95 bar. The in-sample number was real arithmetic about a dead
regime. That is what "looks great in-sample" means, and it is why this lab
exists.

Note the fixture's honesty discipline, which you must preserve end to end:
every bar is labeled `SYNTHETIC`. This is a generated replay universe, and
the label says so. Your pipeline must carry that label through every fold
result untouched. A pipeline that relabels the data REAL — or drops the
label — fails the provenance test. (Ch 9's rule, enforced by Ch 16's
harness: mixed provenance in one fold is refused, not averaged.)

## What is GIVEN and what you build

The lab file ships the fixture, the canary, the honest-flat `FlatLiner`
strategy (emits nothing, ever), the null-trial Sharpe generator for the DSR,
the frozen thesis dataset, the two deterministic judges, and the
`VerdictReport` dataclass your pipeline must fill. All GIVEN. All tested.
All frozen.

You build two functions — the entire student implementation zone:

```python
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
```

Seven steps, three machines, one report. The docstrings are the spec; the
tests are the acceptance criteria.

## The aggregate verdict rule, precisely

The per-fold grades come from the harness (`default_grader`: no fills means
HOLD, positive net means PASS, otherwise FAIL). Your pipeline aggregates:

- **Every fold HOLD → HOLD.** Nothing traded. An honest flat, never a
  fabricated zero. (The `FlatLiner` test enforces this: hard-coding FAIL for
  everything is fabrication in the other direction.)
- **Every fold PASS *and* DSR ≥ 0.95 → PASS.** Both conditions. Walk-forward
  alone is not enough — the canary passes three of five folds and still must
  not graduate, because 25 random strategies were tried alongside it and the
  deflated bar is 0.95.
- **Anything else → FAIL.** Mixed folds, a deflated Sharpe, an undefined
  DSR with trades on the books — all FAIL. The rule is deliberately
  asymmetric: graduation is hard, rejection is cheap. That asymmetry is the
  entire risk posture of a verification pipeline.

One deliberate simplification, stated so nobody mistakes it for a standard:
the lab feeds the *per-trade P&L series* into the DSR machinery. In
production you would use daily strategy returns; the multiplicity math does
not care about the clock, only the observation count, and the machinery is
identical. The chapter says this once, here, so the simplification is
documented instead of smuggled.

## The thesis and the judges

A verdict the desk cannot read is a verdict the desk cannot trust. Step 6
requires a one-paragraph thesis — and step 7 has two judges score it against
a frozen rubric: does it state the true verdict, does it cite the evidence
(fold count, embargo, provenance), does it refrain from claiming a PASS it
did not earn. The judges are deterministic keyword rules in the lab (in
production they wrap pinned-model calls behind the Ch 5 strict schema), but
the machinery under test is Ch 15's: agreement statistics and the cost
ledger. Your thesis must satisfy *both* judges well enough that kappa clears
0.6, and the whole judging run must cost no more than the desk's budget of
1.00 per verified signal. Verification has a budget line. The lab enforces
it.

Write the thesis like an auditor will read it, because one will. Name the
strategy. State the verdict with the word "verdict". Cite the folds, the
embargo, the DSR. If the verdict is not PASS, the string "PASS" must not
appear as a claim — the no-fabrication judge is literal, and so is the
auditor.

## The failure gallery: what each red test guards

When the file is red, it is red in five specific ways, and each one teaches
a different lesson. Read them as a curriculum, not an error log.

**test_canary_does_not_pass** is the lab. Everything else is scaffolding
around it. It encodes the single most expensive mistake in quantitative
history: mistaking a fitted past for a tradeable future. The canary's 2.47
in-sample Sharpe is not a lie — the arithmetic is correct. It is a true
statement about a dead regime. Your pipeline's job is to be the institutional
memory that the regime died: the walk-forward shows the bleeding, the DSR
shows the luck. A pipeline that reports PASS here has built a machine for
manufacturing confidence, which is worse than no machine at all.

**test_flatliner_gets_honest_hold** guards the opposite failure. It is easy
— suspiciously easy — to write a pipeline that rejects everything and call
it "conservative." A rejection machine is not a verification pipeline; it is
a doorstop. The `FlatLiner` never emits an intent, so every fold grades
HOLD, and the aggregate rule must say HOLD: nothing traded, nothing claimed.
An honest flat is a result. The test exists because the temptation to
hard-code FAIL "to be safe" is real, and safety theater is also fabrication.

**test_report_carries_the_evidence** is the audit-trail test. A verdict is a
claim; the report is the evidence. It pins the fold grades tuple
(PASS, PASS, PASS, FAIL, HOLD) — the exact shape of an honest run against
this fixture — the SYNTHETIC provenance end to end, the deflated Sharpe
below the bar, judge agreement above the gate, the dataset hash matching the
pinned golden set, the cost within budget, and a non-empty `reason`. If any
of these is missing, the verdict is a rumor with formatting. Auditors do not
read verdicts; they read trails.

**test_zero_embargo_is_refused** is the leakage test. An embargo of zero
bars means the test window begins where training ended, and adjacent bars
share information — autocorrelation does not respect your good intentions.
The fold builder must refuse a zero embargo loudly, at construction time,
not "handle" it downstream. This test is why `build_folds` takes
`embargo_bars` as a parameter instead of hard-coding it: the refusal must be
in the code path, not in your memory of the code path.

**test_mixed_provenance_is_refused** is the contamination test. One REAL bar
smuggled into a SYNTHETIC dataset — or the reverse — and the harness raises
`DataViolation`. Your pipeline must let it propagate. The lesson generalizes
beyond this lab: provenance is a property of the dataset, and any stage
that silently "fixes" a provenance mismatch is laundering data. Refuse or
relabel explicitly; never coerce quietly.

**test_in_sample_sharpe_is_seductive** is the odd one out: it passes on the
fixture itself, before you build anything. It is documentation as a test —
the trap, stated numerically, so that when your pipeline later reports FAIL
you can hold the two numbers side by side (2.47 in, FAIL out) and see the
whole book in one comparison.

## Anti-fabrication rules

Stated plainly, because the lab's threat model includes you:

1. **Reporting PASS on the canary is an automatic fail.**
   `test_canary_does_not_pass` knows the canary's true verdict. Your
   pipeline must discover it independently — by computing, not by reading
   the test.
2. **Hard-coding verdicts fails the other tests.** Return "FAIL" for
   everything and the `FlatLiner` HOLD test catches you. Return "HOLD" for
   everything and the canary test catches you. The only way through is a
   pipeline that actually runs.
3. **The golden set is pinned.** `dataset.verify()` runs inside your
   pipeline, and the report carries the dataset hash. Mutate a case to make
   the judges agree and the hash will not match.
4. **Exceptions propagate.** A zero embargo must raise `EmbargoViolation`
   from the fold builder; mixed provenance must raise `DataViolation` from
   the harness. Catching these to "make the tests pass" is the precise
   behavior the tests are watching for — the tests assert the exceptions,
   not their absence.

## Red → green checklist

The file is red on purpose. Work it green in this order:

- [ ] **Red baseline:** run `pytest test_lab4_verify.py -q`. Confirm 5
      failures, all `NotImplementedError`, and 1 pass (the seductive-Sharpe
      documentation test). If anything else fails, the fixture is broken —
      stop and re-read the GIVEN sections before writing a line.
- [ ] **Step 1 — folds:** implement `build_folds`. Green:
      `test_zero_embargo_is_refused`. The embargo is load-bearing; a zero
      embargo is leakage with a permission slip.
- [ ] **Steps 2–3 — the walk:** `dataset.verify()`, then `walk_forward`
      with a fresh strategy per fold. Print the per-fold verdicts. You
      should see PASS, PASS, PASS, FAIL, HOLD for the canary. If you see
      anything else, your wiring is wrong — the fixture is deterministic.
- [ ] **Step 4 — the deflation:** concatenate per-trade P&L, generate the
      GIVEN null trials, call `dsr()`. Expect ≈0.67 for the canary — below
      the 0.95 bar. Handle the no-trades case: DSR undefined, `dsr=0.0`,
      verdict HOLD.
- [ ] **Step 5 — the aggregate:** implement the verdict rule exactly as
      specified. The asymmetry is the point.
- [ ] **Steps 6–7 — the thesis and the judges:** write the paragraph, run
      both judges over every case, compute kappa, meter the cost. Green:
      the kappa assertion and the budget assertion in
      `test_report_carries_the_evidence`.
- [ ] **Full green:** all 6 tests pass. Then re-read your `reason` field —
      it is the one string a human will actually read. Make it earn that.

## What Appendix B provides

The passing implementation — the reference `build_folds` and
`verify_strategy`, the expected per-fold table, the expected DSR, the
reference thesis paragraph — lives in Appendix B, and only there. This
chapter contains the spec, the checklist, and the threat model. Do not look
at the answer key until your pipeline is green; the lab's value is the
wiring, not the answer.

## The capstone

Look at what you just built, if you built it honestly. The strategy
proposes intentions, never orders (Ch 4's contracts, Ch 2's Decide). Every
intent executes at the next bar's open (Ch 16's t+1 rule, Ch 10's action
plane). Every bar carries its provenance label from fixture to fold result
(Ch 9's evidence spine). The golden set is frozen and hash-pinned (Ch 15).
The Sharpe is deflated for the 25 tries nobody talks about (Ch 17). The
thesis is judged, the judges are measured, and the whole audit costs less
than a dollar of model calls (Ch 14's cost discipline). The kill switch
never fired because nothing escaped — the pipeline rejected the strategy
before it needed one (Ch 11).

That is the book. Not the chapters — the composition. A strategy that
cannot survive this lab does not trade. That rule, executed in code rather
than in policy documents, is the difference between an agent system and a
hope.

*Figure 23.1 — the Lab 4 pipeline: fixture → folds → walk-forward → DSR → thesis → judges → VerdictReport. Full spec: `figs/ch23-figspec.md`.*
