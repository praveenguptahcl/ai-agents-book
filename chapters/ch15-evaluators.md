# Chapter 15: Evaluators — Deterministic Grades and LLM Judges

*Part V: Evidence & Verification. The grading machinery.*

## 15.1 The only defense against "it worked on my prompt"

Every agent demo in history has worked on the presenter's prompt. The demo is
a sample of size one, drawn from a distribution the presenter chose, scored by
the presenter, on hardware the presenter controls. It proves the agent can
succeed once, under supervision, when it matters least. Production is the
opposite of a demo: unsupervised, adversarial, and scored by reality.

Evaluations are the only defense. Not the only *good* defense — the only one.
Everything else this book has built — contracts, sessions, kill switches,
evidence chains — constrains what the agent *may* do. Only evals tell you what
it *actually does*, repeatedly, measurably, before your users find out.

This chapter builds the grading machinery: frozen golden sets, deterministic
graders, LLM judges with agreement statistics, cost-aware CI gates, code-task
evals, and retrieval evals. It is deliberately the *machinery*, not the
*methodology*. Chapter 16 owns the temporal protocol — walk-forward folds,
embargoes, no-lookahead proofs — and it imports these graders to score its
folds. Chapter 17 owns the statistics of self-deception — PSR and DSR — and
consumes scored results. If you are looking for the chapter that tells you
whether your strategy is real, that is Chapter 16 and 17. This chapter tells
you whether your *grades* are real. A walk-forward built on uncalibrated
graders is a precision instrument measuring nothing.

The chapter's quant thread follows the AlphaForge desk's nightly ritual: every
trading thesis the signal agent produces is graded before it is allowed near
paper capital. A deterministic grader checks the thesis cites only REAL-labeled
bars. An LLM judge scores whether the thesis actually matches historical
conditions. The two are compared with Cohen's kappa. And the whole thing runs
under a cost budget, because a grading pipeline the desk cannot afford is a
grading pipeline the desk will quietly stop running.

## 15.2 Golden sets: frozen, curated, and honest about provenance

A golden set is a collection of cases with known-correct answers. It is the
ruler against which the agent is measured, and rulers do not get to change
length between measurements. Three disciplines make a golden set trustworthy:

**Frozen.** The cases are pinned by content hash at load time, and every read
path re-verifies the pin. If a case is edited after pinning — a "helpful"
cleanup, a merge gone wrong, a quiet fix to make the numbers look better —
verification fails loudly. Chapter 9's evidence router already maintains an
eval dataset of curated events frozen at scoring time; this chapter's
`FrozenDataset` is the grading-side expression of the same discipline. The
hash is SHA-256 over canonical JSON (sorted keys, no whitespace):

```python
def _canonical(obj: Any) -> str:
    """Canonical JSON rendering for hashing: sorted keys, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()
```

**Curated.** A golden set is not a random sample of production traffic. It is
*chosen*: it covers the failure modes you fear (the spoofed invoice, the
synthetic bar presented as history, the threshold the agent learned to split),
it includes the boring cases that guard against regression, and every case
carries its source. Curation is part of validity — an eval set nobody curated
is an eval set nobody thought about, and unthought-about evals measure
whatever the data happened to contain.

**Provenance-labeled.** Every case is marked REAL or SYNTHETIC, the same
labels Chapter 2 demanded for market bars. This matters because of the
ugliest failure in evaluation: **train-on-test contamination**. If the cases
in your golden set — or anything derived from them — appeared in the model's
training data, your eval measures memorization, not capability. The defense
is partly procedural (keep golden sets out of training pipelines, rotate
them) and partly structural: provenance labels let you audit *what* the
agent was graded on, and a sudden jump in scores on REAL cases with flat
scores on fresh SYNTHETIC cases is the signature of contamination, not
improvement.

A word on size, because "how many cases?" is the first question every team
asks and the Wilson interval is the answer. Twelve cases cannot support a
0.90 gate — the interval (0.646, 0.985) says the true rate could be 0.65.
Two hundred cases can: 190/200 gives (0.910, 0.973), and the lower bound
clears the gate honestly. The desk's rule of thumb: size the golden set so
that the Wilson lower bound at your target pass rate clears your gate with
room to spare, then add the cases your failure modes demand on top. A golden
set sized by vibes is a gate that cannot hold.

## 15.3 Deterministic graders: seeded, self-checked, or refused

A grader is a function from (case, prediction) to a score. The deterministic
ones are the foundation: exact match, schema conformance, range checks,
citation-label checks. Their virtue is not sophistication — it is that they
cannot flatter you. An exact-match grader does not care how eloquent the
wrong answer was.

But determinism must be *enforced*, not assumed. A grader that uses randomness
— shuffling, sampling, a stochastic tie-break — without a fixed seed will
produce different scores on different runs, and a score that changes between
runs is a rumor. The base class in `evaluator.py` makes the discipline
executable:

```python
    def grade(self, case: EvalCase,
              prediction: Mapping[str, Any]) -> ScoreResult:
        first = self._grade(case, prediction, self._rng())
        second = self._grade(case, prediction, self._rng())
        if (first.passed, first.score) != (second.passed, second.score):
            raise NondeterministicGraderError(
                f"grader {self._name!r} disagreed with itself on "
                f"{case.case_id!r}: {first.score} vs {second.score}")
        return first
```

Two mechanisms, both load-bearing. First, construction *requires* an explicit
seed — `UnseededGraderError` otherwise. There is no default seed, because a
default seed is a seed nobody chose, and unchosen seeds get "tuned" until the
numbers look good. Second, every `grade` call runs the underlying `_grade`
twice with fresh RNGs and demands agreement. A grader that claims determinism
but disagrees with itself is caught at grading time, not discovered months
later when the audit asks why the numbers moved.

Note the fresh-RNG-per-call detail: `self._rng()` constructs a new
`random.Random(self._seed)` each time. Grading order must not matter. A grader
whose score for case 47 depends on whether case 46 was graded first is
carrying hidden state, and hidden state in a grader is a bug wearing a lab
coat.

The chapter's trading-thesis grader is a `DeterministicGrader` subclass with
a paper-trading invariant baked in:

```python
class RealBarsOnlyGrader(DeterministicGrader):
    """The trading-thesis grader from the chapter's quant thread.

    A trading thesis cites market bars. Any cited bar not labeled REAL is a
    validity failure — a thesis grounded in synthetic data presented as
    history is fabrication, not analysis. (Meridian invariant: every bar
    labeled REAL or SYNTHETIC; paper-trading honesty, Ch 2's Verify.)
    """
```

A thesis that cites a SYNTHETIC bar as historical evidence fails — not with a
low score, with a *validity* failure. The distinction matters: a low score
says "weak thesis"; a validity failure says "this evaluation cannot be
trusted." Conflating the two is how fabricated backtests survive review.

## 15.4 LLM-as-judge: measured, never trusted

Some things cannot be graded deterministically. Whether a trading thesis
*actually matches* historical conditions, whether a summary is faithful,
whether a plan is sensible — these need judgment. The industry answer is
LLM-as-judge: a pinned model, called with temperature 0 and a strict schema
(the Chapter 5 discipline), scores the output.

The danger is obvious: you have replaced the agent you do not trust with a
judge you have not verified. The chapter's answer is that **judges are
measured, not trusted**, and the measurement is agreement statistics.

### Cohen's kappa, worked by hand

Two judges score five thesis cases, pass or fail:

- Judge A: pass, pass, pass, fail, fail
- Judge B: pass, pass, fail, fail, fail

Raw agreement: they agree on four of five cases — 80%. That sounds good. It
is flattering, because it ignores chance. Both judges say "pass" most of the
time; two coin-flippers with the same bias would agree often without agreeing
about anything.

Cohen's kappa subtracts chance agreement. Observed agreement $p_o = 4/5 =
0.80$. Expected agreement by chance: A says pass $3/5$ of the time, B says
pass $2/5$, so both-pass-by-chance is $(3/5)(2/5) = 6/25$; both-fail-by-chance
is $(2/5)(3/5) = 6/25$; $p_e = 12/25 = 0.48$. Then:

$$\kappa = \frac{p_o - p_e}{1 - p_e} = \frac{0.80 - 0.48}{1 - 0.48}
        = \frac{0.32}{0.52} = \frac{8}{13} \approx 0.615$$

The implementation the hand-computation must match:

```python
def cohens_kappa(a: Sequence[int], b: Sequence[int]) -> float:
    """Cohen's kappa for two raters on categorical labels (e.g. pass/fail).

    Raw agreement overstates reliability: two judges that both say "pass"
    95% of the time agree 90% of the time by chance alone. Kappa subtracts
    chance agreement. The chapter works this by hand once; this is the
    implementation the hand-computation must match.
    """
```

A kappa of 0.615 is *substantial* agreement (on the Landis–Koch scale) but
nowhere near perfect — and crucially, it is much less comforting than the raw
80%. That gap between raw agreement and kappa is the whole point: **report
kappa, not raw agreement**, and distrust any judge evaluation that reports
only the latter. The desk's rule: the deterministic grader and the LLM judge
must reach kappa ≥ 0.6 on the thesis set before the judge's scores are
allowed into the CI gate. Below that, the judge is not measuring thesis
quality; it is measuring its own mood.

Judge-vs-human agreement gets the same treatment on a sampled subset. The
human is not ground truth either — humans disagree — but human-judge kappa
tells you whether the judge's errors at least resemble human errors, which is
the minimum bar for delegating grading to it.

The desk learned this the expensive way, and the story is worth telling
because it is the reason the nightly ritual exists. In the AlphaForge team's
second month, the signal agent produced a thesis on a semiconductor name:
clean setup, cited bars all REAL-labeled, deterministic graders green. It
went to paper capital without a judge's review — the judge pipeline was
"almost ready." The thesis was technically accurate and strategically
absurd: it had matched the *shape* of a historical setup while missing that
the setup occurred under a completely different volatility regime. The
deterministic graders could not see it — every citation resolved, every
number was real. A judge scoring thesis-vs-conditions alignment would have
flagged it in seconds. The paper portfolio bled for a week before a human
noticed the regime mismatch. Nothing was lost but pretend money and real
confidence, and the team wrote the rule that evening: no thesis reaches
capital — paper or otherwise — without both a deterministic grade and a
judge's verdict, and the two must agree with each other (kappa ≥ 0.6)
before either is allowed to agree with the agent. The incident became the
first case in the golden set, provenance REAL, source "the week we learned."

### Judge calibration: the judge is an instrument, and instruments drift

A pinned model at temperature 0 is deterministic *today*. Model providers
deprecate versions, "the same" model gets silent updates, and a judge whose
behavior shifted between Tuesday and Thursday will move your scores without
moving your agent. The defense is calibration:

- **Pin the version.** The judge configuration names the exact model version,
  not "the latest." A version change is a config change, reviewed like one.
- **Keep a calibration set.** A small frozen set of cases with known judge
  verdicts. Re-score it whenever the model version, the judge prompt, or the
  temperature changes. If the calibration verdicts move, the judge moved —
  investigate before trusting new scores.
- **Treat the judge prompt as a contract.** The rubric the judge applies is
  versioned text, reviewed like code, with the same strict-schema discipline
  as Chapter 5's provider calls. A rubric edited casually is a grader edited
  casually.

Judge drift is insidious because it looks like agent improvement or
regression. The calibration set is the control group that tells you which
one moved.

### Wilson intervals: never trust a bare percentage

"Our eval passes 92% of cases." On how many cases? Twelve. Then the honest
statement is not 92% — it is the Wilson score interval, which for 11
successes out of 12 at 95% confidence is **(0.646, 0.985)**. The same 92% on
1,200 cases is (0.900, 0.931): a claim you can lean on versus a rumor with
good lighting.

```python
def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a pass rate. Never trust a bare percentage.

    A "92% pass rate" on n=12 is (0.65, 0.99); on n=1200 it is (0.90, 0.94).
    The interval, not the point estimate, goes into the CI gate.
    """
```

The formula: with $\hat{p} = k/n$ and $z = 1.96$, the interval center is
$(\hat{p} + z^2/2n)/(1 + z^2/n)$ and the half-width is
$z\sqrt{\hat{p}(1-\hat{p})/n + z^2/4n^2}/(1 + z^2/n)$. For $k=11, n=12$:
center ≈ 0.816, half-width ≈ 0.170, interval (0.646, 0.985). The
implementation above must reproduce exactly these numbers — the test suite
pins them, because a statistics function whose prose and code disagree is a
textbook bug, the kind this book exists to prevent.

The CI gate uses the **lower bound** by default. A merge that clears the gate
on a point estimate but fails it on the lower bound is a merge that got
lucky on a small sample. Luck is not a release criterion.

### Disagreement routes to a human

Two judges, one case, different verdicts. What does the machine do? Nothing
clever. It does not average (averaging a pass and a fail is a shrug with
arithmetic). It does not pick the "better" judge (that is the disagreement
wearing a costume). It routes to a human:

```python
def adjudicate(case_id: str, verdicts: Sequence[JudgeVerdict]) -> JudgeVerdict | HumanReviewTicket:
    """Two judges disagree → the record goes to a human. The machine never
    breaks its own tie: picking a winner between disagreeing judges is how
    you launder one judge's error into a "consensus"."""
```

The `HumanReviewTicket` carries the case, the judges, and their verdicts.
The human's verdict re-enters through the same `ScoreResult` shape — the
pipeline does not have a special "human said so" path that bypasses grading
discipline. And the disagreed case contributes *no* score until the human
rules: the suite test asserts `report.results == []` for a fully-disagreed
case, because scoring it either way would be fabricating a consensus.

## 15.5 Cost-per-verified-success: the metric that keeps evals honest about money

An eval that ignores cost grades a system nobody can afford to run. LLM
judges cost money per call; a nightly suite with a thousand judge-scored
cases at four cents a call is a forty-dollar nightly opinion, and opinions
that expensive get skipped, then stale, then decorative.

The metric is exactly what it says:

```python
    def cost_per_verified_success(self, verified_successes: int) -> float:
        """Dollars per success the graders actually verified.

        Zero verified successes → infinite cost, reported as such. An eval
        with no verified successes has no price-performance; it has a bill.
        """
```

Dollars in, *verified* successes out — not attempted cases, not judge calls,
verified successes. And zero verified successes is infinite cost, not zero
cost: dividing by zero here would claim the eval was free, which is the
most expensive lie in the building.

The metric belongs in the CI gate alongside the pass rate. The desk's gate
says: Wilson lower bound on the thesis pass rate ≥ 0.90 **and**
cost-per-verified-signal ≤ \$0.05. A brilliant judge that costs a dollar a
call fails the gate — not because it is wrong, but because a gate the team
cannot afford is a gate the team will disable, and a disabled gate is Chapter
11's kill switch with the wires cut.

The cost discipline is also architectural: `EvalSuite.run` takes a
`judge_on` parameter — the case ids the expensive judges score. Everything
else gets deterministic grades only. Judge calls are budgeted, not
sprinkled. The default posture of the harness is *cheap*; expense requires
an explicit list.

There is a design exercise worth doing before any judge is wired in: the
eval budget spreadsheet. List every grader and judge, its per-case cost,
the number of cases it scores, and the run frequency. Multiply it out. The
desk's first draft of the nightly suite cost \$412 per night — discovered
on paper, before a single judge call was made, because the spreadsheet
existed. The final design costs under \$9: deterministic graders score all
400 thesis cases (free), the judge scores a budgeted 60 (the newest and the
most disputed), and the full-judge sweep runs weekly, not nightly. An eval
budget computed after deployment is an apology; computed before, it is
architecture. The `CostLedger` is the spreadsheet made executable — the
numbers it accumulates should match the spreadsheet within rounding, and
when they don't, either the spreadsheet or the harness is lying.

## 15.6 Code-task evals, SWE-bench style: the agent never sees the tests

Coding agents (Chapter 13's strategy-code-editing research agent) need their
own eval discipline, and the field has converged on the SWE-bench shape. Each
task instance carries:

- **fail-to-pass** tests: fail before the patch, must pass after. These are
  the bug, formalized.
- **pass-to-pass** tests: pass before *and* after. These are the regression
  guard — the fix is not allowed to break what worked.
- **forbidden paths**: the test files themselves. The agent gets the repo
  and the problem statement. It never gets the tests.

```python
def grade_code_task(task: CodeTask, result: CodeTaskResult) -> ScoreResult:
    """Resolved = all fail_to_pass now pass, all pass_to_pass still pass,
    and the patch never touched the tests."""
```

The forbidden-paths check deserves emphasis because it is the easiest one
to skip and the most important one to keep. An agent that "resolves" a task
by editing the tests has not fixed the bug; it has fixed the *measurement*
of the bug. That is the eval-harness version of the threshold-splitting from
Chapter 1 — the system routing around the constraint instead of satisfying
it. The grader treats a patch touching forbidden paths as a failure with the
reason recorded, not as a low score: like the synthetic-bar citation, it is
a validity failure.

Resolve rate — fraction of tasks resolved — is the headline metric, gated
with Wilson intervals like everything else. The AlphaForge research agent's
gate: resolve rate lower bound ≥ 0.5 on the strategy-repair set before its
patches are allowed into the sandbox queue. Below that, its patches are
suggestions a human reads; above that, they are candidates the sandbox runs.

## 15.7 Retrieval evals: recall@k is not groundedness

The evidence pipeline (Chapter 9) routes queries to historical-price SQL or
news-sentiment APIs. Its evals need two numbers, and confusing them is the
standard failure:

**Recall@k** measures the retriever: of the documents relevant to the query,
what fraction appear in the top-k retrieved? Necessary, not sufficient. A
system can retrieve perfectly and still hallucinate — that failure lives
downstream, in generation.

**Groundedness** measures the answer: of the factual claims the agent
asserted, what fraction trace to a span that was *actually retrieved*? Two
ways to fail, both dishonesty: the claim cites nothing
(`supporting_span_id is None`), or it cites a span the retriever never
returned — a fabricated citation. The metric does not distinguish, and
neither do we.

The claim ledger is Chapter 9's evidence spine applied to text: every claim
points at its supporting span, and the eval checks the pointers resolve.
This is the same discipline as the REAL/SYNTHETIC bar labels — provenance
all the way down, because an agent whose citations do not resolve is an
agent whose evidence does not exist.

One intersection to note, prose-only: whether access-control filtering
happens at index time or query time (the Chapter 6/9 boundary) changes what
recall@k *means* — a retriever that cannot see tenant B's documents will
score lower on cross-tenant queries, and that is correct behavior being
measured as poor retrieval. Eval the retriever within a tenant, or annotate
the golden set with the visibility rules. No new code; just the kind of
footnote that saves a team a month.

## 15.8 Eval-driven development: the gate that blocks the merge

Everything in this chapter converges on one practice: evals run on every
commit, and regressions block the merge. The `EvalSuite`/`EvalReport` pair
makes it executable — `check_gate` raises `RegressionError` or
`CostGateExceededError`, and a raised exception is a blocked merge. "We will
fix the eval later" is how unverified systems ship; the gate exists to make
later *now*.

Three rules keep the gate honest over time:

1. **The gate measures the lower bound.** Wilson lower, kappa threshold,
   cost ceiling — the pessimistic reading. Optimistic gates pass everything
   and protect nothing. And the counting unit is the *case*, not the grade:
   a case succeeds only if every grader and judge that scored it passed it.
   Counting each (case, grader) pair as an independent trial inflates n,
   breaks the binomial independence the Wilson interval assumes, and
   manufactures a tight interval that clears the gate dishonestly.
2. **Baselines are committed, not remembered.** The threshold lives in the
   repo next to the code it gates. A baseline that lives in someone's head
   gets renegotiated every quarter.
3. **Golden sets rotate.** Contamination is a matter of when, not if.
   Versioned datasets, pinned hashes, archived runs — Chapter 9's retention
   discipline, applied to the ruler itself.

The gate is also a social instrument, and it needs tending like one. The
desk runs a monthly eval review with exactly three agenda items. First, the
thresholds: does the committed pass-rate floor still match what the
business needs, or has the team been quietly negotiating with the gate?
Thresholds move only by written decision, never by drift. Second, the
golden set: which cases were added, which were retired, and did any
retirement coincide suspiciously with a failing run? The frozen-dataset
hash makes silent retirement impossible — the pin changes, the change is
reviewed. Third, the disagreements: the human-review tickets from
`adjudicate` are read aloud, briefly. A pattern in the disagreements —
the judges keep splitting on the same kind of case — is the most valuable
signal the eval system produces. It means the rubric is ambiguous where it
matters, and the fix is a better rubric, not a louder judge.

Skip the review and the gate decays. Thresholds get "temporarily" lowered
for a release and never restored. The golden set accumulates cases the
agent already passes — survivorship bias wearing a lab coat. The tickets
pile up unread. None of this is a tooling failure. It is what happens when
the team stops treating the eval system as production infrastructure and
starts treating it as ceremony. Chapter 1's lesson about human oversight
degrading into ritual applies to evals too: a gate nobody tends is a ritual
with a YAML file.

This is the book's method, stated plainly: the same adversarial posture the
tests take toward the code, the evals take toward the agent. The test suite
in `test_evaluator.py` (49 tests) attacks the harness the way the harness
attacks the agent — tampered datasets, self-disagreeing graders, disagreeing
judges, blown cost budgets, fabricated citations, test-touching patches.
Each test names the failure it prevents, because unnamed failures get
ignored.

## 15.9 Handoff: the graders are built; now the temporal protocol they score

This chapter built the machinery that decides whether a score means
anything: frozen golden sets that detect tampering, deterministic graders
that reproduce their own scores or refuse, judges whose agreement is
measured in kappa rather than vibes, pass rates reported as Wilson
intervals, disagreements routed to humans, and a cost-per-verified-success
gate that keeps the whole apparatus affordable enough to actually run.

But graders score *cases*, and cases are timeless. A trading strategy is not
a set of cases — it is a sequence of decisions through time, and time is
where the characteristic frauds live: the signal that peeked at tomorrow's
bars, the backtest that trained on its own test set, the walk-forward with
no embargo between folds. No grader in this chapter can catch those, because
no grader in this chapter knows what "before" means.

Chapter 16 gives the machinery a timeline. It folds history into
train/validate/test segments separated by embargo gaps, proves the
no-lookahead invariant (a signal decided on bar $t$ cannot execute before
bar $t{+}1$'s open — the Meridian temporal rule, enforced by construction),
and scores each fold with the graders built here. The machinery you just
read is the instrument; the next chapter is the procedure that keeps the
instrument honest about time.

*Figure: the eval pipeline — golden set → graders + budgeted judges → agreement stats → CI gate (one-line reference; full spec in `figs/ch15-figspec.md`).*
