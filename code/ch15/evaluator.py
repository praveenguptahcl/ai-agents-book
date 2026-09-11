"""Evaluators: deterministic grades and LLM judges — the grading machinery.

Chapter 15 of *AI Agents: Systems, Safety, and Practice*.

This module is the GRADING MACHINERY. Walk-forward methodology (which folds
the timeline, enforces embargoes, and proves no-lookahead) is Chapter 16,
which imports these graders to score its folds. PSR/DSR multiplicity control
is Chapter 17, which consumes scored results. Nothing here knows about time.

Design rules (the book's standing invariants, applied to grading):
  - A grader that cannot reproduce its own score is a rumor, not a grade.
    Deterministic graders are seeded; unseeded randomness is refused.
  - A judge that disagrees with itself gets no vote. Disagreement between
    judges routes to a human — the machine never breaks its own tie.
  - An eval that ignores cost grades a system nobody can afford to run.
    Cost-per-verified-success is a first-class metric in the CI gate.
  - Golden sets are frozen: content-hash pinned, mutation detected, tamper
    refused. Train-on-test contamination is a validity failure, not a win.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Errors: every failure mode gets a name, because unnamed failures get ignored
# ---------------------------------------------------------------------------

class EvalError(Exception):
    """Base class for evaluator failures."""


class DatasetTamperedError(EvalError):
    """A frozen golden set no longer matches its pinned hash."""


class NondeterministicGraderError(EvalError):
    """A grader claimed determinism but produced two different scores."""


class UnseededGraderError(EvalError):
    """A grader that requires a seed was constructed without one."""


class JudgeDisagreementError(EvalError):
    """Judges disagree; the record is routed to human review."""


class CostGateExceededError(EvalError):
    """Cost-per-verified-success exceeded the CI gate threshold."""


class RegressionError(EvalError):
    """An eval metric regressed below its committed baseline."""


# ---------------------------------------------------------------------------
# Frozen golden sets: the ground truth is pinned, or it is not ground truth
# ---------------------------------------------------------------------------

def _canonical(obj: Any) -> str:
    """Canonical JSON rendering for hashing: sorted keys, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvalCase:
    """One golden case: inputs, the expected answer, and provenance."""
    case_id: str
    inputs: Mapping[str, Any]
    expected: Mapping[str, Any]
    # Where this case came from: curation is part of validity.
    source: str = ""
    # "REAL" (human-curated / production-sampled) or "SYNTHETIC" (generated).
    provenance: str = "REAL"

    def fingerprint(self) -> str:
        # source and provenance are IN the hash: a "helpful" relabeling
        # of a case's provenance after pinning is tampering, and the
        # frozen-dataset verification must fail loudly on it. The
        # book's provenance invariant (REAL/SYNTHETIC on everything the
        # agent is graded on) is only auditable if the labels are pinned.
        return content_hash({"id": self.case_id,
                             "inputs": dict(self.inputs),
                             "expected": dict(self.expected),
                             "source": self.source,
                             "provenance": self.provenance})


class FrozenDataset:
    """A golden set pinned by content hash. Mutation is detected, not debated.

    Chapter 9's EvalDataset stores curated *events*; this class is the
    *grading* view of the same discipline: the cases the judges score are
    frozen at scoring time. The dataset hash is computed at load; every read
    path re-verifies. If a case changes after pinning — an edit, a merge
    gone wrong, a "helpful" cleanup — verification fails loudly.
    """

    def __init__(self, name: str, cases: Sequence[EvalCase]) -> None:
        self._name = name
        self._cases: dict[str, EvalCase] = {c.case_id: c for c in cases}
        if len(self._cases) != len(cases):
            raise EvalError(f"duplicate case_id in dataset {name!r}")
        self._pinned_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        fps = sorted(c.fingerprint() for c in self._cases.values())
        return content_hash({"dataset": self._name, "cases": fps})

    @property
    def name(self) -> str:
        return self._name

    @property
    def pinned_hash(self) -> str:
        return self._pinned_hash

    def verify(self) -> None:
        """Fail closed: the dataset no longer matches its pinned hash."""
        if self._compute_hash() != self._pinned_hash:
            raise DatasetTamperedError(
                f"dataset {self._name!r} mutated after pinning "
                f"(expected {self._pinned_hash[:12]}...)")

    def get(self, case_id: str) -> EvalCase:
        self.verify()
        try:
            return self._cases[case_id]
        except KeyError:
            raise EvalError(f"unknown case {case_id!r} in {self._name!r}") from None

    def case_ids(self) -> list[str]:
        self.verify()
        return sorted(self._cases)

    def __len__(self) -> int:
        return len(self._cases)


# ---------------------------------------------------------------------------
# Graders: deterministic, seeded, reproducible — or refused
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoreResult:
    """One graded case. Designed so Chapter 16 can import graders for folds."""
    case_id: str
    passed: bool
    score: float                      # 0.0 .. 1.0
    grader: str
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "passed": self.passed,
                "score": self.score, "grader": self.grader,
                "detail": dict(self.detail)}


class DeterministicGrader:
    """Base class for graders that must reproduce their own scores.

    Subclasses implement ``_grade(case, prediction)``. The base class
    enforces the discipline:
      - construction requires an explicit seed (UnseededGraderError),
      - ``grade`` runs twice and the scores must agree
        (NondeterministicGraderError) — the self-check is the point.
    """

    def __init__(self, name: str, seed: int | None = None) -> None:
        if seed is None:
            raise UnseededGraderError(
                f"grader {name!r} requires an explicit seed; "
                "unseeded randomness is not a grade")
        self._name = name
        self._seed = seed

    @property
    def name(self) -> str:
        return self._name

    def _rng(self) -> random.Random:
        # Fresh RNG per grade call: order of grading must not matter.
        return random.Random(self._seed)

    def _grade(self, case: EvalCase, prediction: Mapping[str, Any],
               rng: random.Random) -> ScoreResult:  # pragma: no cover
        raise NotImplementedError

    def grade(self, case: EvalCase,
              prediction: Mapping[str, Any]) -> ScoreResult:
        first = self._grade(case, prediction, self._rng())
        second = self._grade(case, prediction, self._rng())
        if (first.passed, first.score) != (second.passed, second.score):
            raise NondeterministicGraderError(
                f"grader {self._name!r} disagreed with itself on "
                f"{case.case_id!r}: {first.score} vs {second.score}")
        return first


class ExactMatchGrader(DeterministicGrader):
    """The simplest honest grader: the prediction must equal the expected."""

    def _grade(self, case: EvalCase, prediction: Mapping[str, Any],
               rng: random.Random) -> ScoreResult:
        ok = dict(prediction) == dict(case.expected)
        return ScoreResult(case_id=case.case_id, passed=ok,
                           score=1.0 if ok else 0.0, grader=self._name,
                           detail={"compared_keys": sorted(case.expected)})


class RealBarsOnlyGrader(DeterministicGrader):
    """The trading-thesis grader from the chapter's quant thread.

    A trading thesis cites market bars. Any cited bar not labeled REAL is a
    validity failure — a thesis grounded in synthetic data presented as
    history is fabrication, not analysis. (AlphaForge invariant: every bar
    labeled REAL or SYNTHETIC; paper-trading honesty, Ch 2's Verify.)
    """

    def _grade(self, case: EvalCase, prediction: Mapping[str, Any],
               rng: random.Random) -> ScoreResult:
        cited = prediction.get("cited_bars", [])
        bad = [b for b in cited
               if not isinstance(b, Mapping) or b.get("label") != "REAL"]
        ok = not bad
        return ScoreResult(
            case_id=case.case_id, passed=ok,
            score=1.0 if ok else 0.0, grader=self._name,
            detail={"cited": len(cited), "non_real_citations": len(bad)})


# ---------------------------------------------------------------------------
# LLM-as-judge with agreement statistics: judges are measured, not trusted
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JudgeVerdict:
    case_id: str
    judge: str
    passed: bool
    score: float
    rationale: str


class LLMJudge:
    """A judge whose verdicts are scored, not trusted.

    ``judge_fn`` is the injected decision procedure. In production it is a
    pinned-model call (fixed model version, temperature 0, the Ch 5 strict
    schema); in tests it is a deterministic stub. The machinery around it —
    agreement stats, disagreement routing — is what this chapter owns.
    """

    def __init__(self, name: str,
                 judge_fn: Callable[[EvalCase, Mapping[str, Any]], JudgeVerdict],
                 cost_per_call: float = 0.0) -> None:
        self._name = name
        self._judge_fn = judge_fn
        self._cost_per_call = cost_per_call
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def judge(self, case: EvalCase,
              prediction: Mapping[str, Any]) -> JudgeVerdict:
        verdict = self._judge_fn(case, prediction)
        self.calls += 1
        return verdict

    @property
    def total_cost(self) -> float:
        return self.calls * self._cost_per_call


def cohens_kappa(a: Sequence[int], b: Sequence[int]) -> float:
    """Cohen's kappa for two raters on categorical labels (e.g. pass/fail).

    Raw agreement overstates reliability: two judges that both say "pass"
    95% of the time agree 90% of the time by chance alone. Kappa subtracts
    chance agreement. The chapter works this by hand once; this is the
    implementation the hand-computation must match.
    """
    if len(a) != len(b) or not a:
        raise EvalError("kappa needs two non-empty, equal-length rating lists")
    n = len(a)
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    labels = sorted(set(a) | set(b))
    expected = sum((sum(1 for x in a if x == l) / n) *
                   (sum(1 for y in b if y == l) / n) for l in labels)
    if expected == 1.0:
        return 1.0  # perfect agreement on a single label: no disagreement
    return (observed - expected) / (1.0 - expected)


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a pass rate. Never trust a bare percentage.

    A "92% pass rate" on n=12 is (0.65, 0.99); on n=1200 it is (0.90, 0.94).
    The interval, not the point estimate, goes into the CI gate.
    """
    if n <= 0:
        raise EvalError("wilson_interval needs n > 0")
    if not 0 <= successes <= n:
        raise EvalError("successes must be within [0, n]")
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


@dataclass(frozen=True)
class HumanReviewTicket:
    """A disagreement the machine refused to resolve itself."""
    case_id: str
    judges: tuple[str, ...]
    verdicts: tuple[bool, ...]
    reason: str


def adjudicate(case_id: str, verdicts: Sequence[JudgeVerdict]) -> JudgeVerdict | HumanReviewTicket:
    """Two judges disagree → the record goes to a human. The machine never
    breaks its own tie: picking a winner between disagreeing judges is how
    you launder one judge's error into a "consensus"."""
    if not verdicts:
        raise EvalError("adjudicate needs at least one verdict")
    if all(v.passed == verdicts[0].passed for v in verdicts):
        return verdicts[0]
    return HumanReviewTicket(
        case_id=case_id,
        judges=tuple(v.judge for v in verdicts),
        verdicts=tuple(v.passed for v in verdicts),
        reason="judges disagree; routed to human review")


# ---------------------------------------------------------------------------
# Cost-per-verified-success: the metric that keeps evals honest about money
# ---------------------------------------------------------------------------

class CostLedger:
    """Every eval call that costs money is recorded. The CI gate reads this."""

    def __init__(self) -> None:
        self._entries: list[tuple[str, float]] = []

    def record(self, label: str, cost: float) -> None:
        if cost < 0:
            raise EvalError("cost cannot be negative")
        self._entries.append((label, cost))

    @property
    def total(self) -> float:
        return sum(c for _, c in self._entries)

    def cost_per_verified_success(self, verified_successes: int) -> float:
        """Dollars per success the graders actually verified.

        Zero verified successes → infinite cost, reported as such. An eval
        with no verified successes has no price-performance; it has a bill.
        """
        if verified_successes <= 0:
            return math.inf
        return self.total / verified_successes


# ---------------------------------------------------------------------------
# Retrieval evals: recall@k is not groundedness
# ---------------------------------------------------------------------------

def recall_at_k(retrieved_ids: Sequence[str], relevant_ids: Sequence[str],
                k: int) -> float:
    """Fraction of relevant docs present in the top-k retrieved.

    Retrieval quality — necessary, not sufficient. A system can retrieve
    perfectly and still hallucinate; that failure is groundedness, below.
    """
    if k <= 0:
        raise EvalError("k must be positive")
    if not relevant_ids:
        raise EvalError("recall needs at least one relevant id")
    topk = set(retrieved_ids[:k])
    hit = sum(1 for r in relevant_ids if r in topk)
    return hit / len(relevant_ids)


@dataclass(frozen=True)
class Claim:
    """One factual claim in an answer, traced to a retrieved span.

    The claim ledger (Ch 9's evidence spine, applied to text): every claim
    the agent asserts must point at the span that supports it. A claim with
    no span is not a claim; it is a guess wearing a citation's clothes.
    """
    text: str
    supporting_span_id: str | None  # None = asserted without evidence


def groundedness(claims: Sequence[Claim],
                 retrieved_span_ids: Sequence[str]) -> float:
    """Fraction of claims traceable to a span that was actually retrieved.

    Two ways to fail: the claim cites nothing (supporting_span_id is None),
    or it cites a span the retriever never returned (a fabricated citation).
    Both are dishonesty; the metric does not distinguish, and neither do we.
    """
    if not claims:
        raise EvalError("groundedness needs at least one claim")
    retrieved = set(retrieved_span_ids)
    good = sum(1 for c in claims
               if c.supporting_span_id is not None
               and c.supporting_span_id in retrieved)
    return good / len(claims)


# ---------------------------------------------------------------------------
# SWE-bench-style code-task evals: the agent never sees the tests
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CodeTask:
    """One code-repair instance: fail-to-pass and pass-to-pass test ids.

    The discipline, from SWE-bench: the agent gets the repo and the problem
    statement. It never gets the test list. fail_to_pass must fail before the
    patch and pass after; pass_to_pass must pass before AND after (no
    regressions smuggled in with the fix).
    """
    task_id: str
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...]
    # Paths the agent's patch may not touch (the test files themselves).
    forbidden_paths: tuple[str, ...] = ("tests/",)


@dataclass(frozen=True)
class CodeTaskResult:
    task_id: str
    patch_touches_forbidden: bool
    test_outcomes: Mapping[str, bool]  # test id -> passed


def grade_code_task(task: CodeTask, result: CodeTaskResult) -> ScoreResult:
    """Resolved = all fail_to_pass now pass, all pass_to_pass still pass,
    and the patch never touched the tests."""
    if result.patch_touches_forbidden:
        return ScoreResult(task.task_id, False, 0.0, "code_task",
                           {"reason": "patch touched forbidden paths"})
    f2p = all(result.test_outcomes.get(t, False) for t in task.fail_to_pass)
    p2p = all(result.test_outcomes.get(t, False) for t in task.pass_to_pass)
    ok = f2p and p2p
    return ScoreResult(task.task_id, ok, 1.0 if ok else 0.0, "code_task",
                       {"fail_to_pass_ok": f2p, "pass_to_pass_ok": p2p,
                        "resolved": ok})


def resolve_rate(results: Sequence[ScoreResult]) -> float:
    if not results:
        raise EvalError("resolve_rate needs at least one result")
    return sum(1 for r in results if r.passed) / len(results)


# ---------------------------------------------------------------------------
# Eval runs and the CI gate: evals run on every commit; regressions block
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GateThreshold:
    metric: str
    # Floors and ceilings are different promises and get different names:
    # a cost budget is a ceiling ("maximum"), never a "minimum" that reads
    # as one. The gate maps each metric to its semantic field and refuses
    # a threshold that names the wrong one.
    minimum: float | None = None
    maximum: float | None = None
    # Wilson lower bound (honest) or point estimate (lazy)? The gate is
    # honest by default: the LOWER bound of the interval must clear.
    use_wilson_lower: bool = True


@dataclass
class EvalReport:
    suite: str
    results: list[ScoreResult]
    ledger: CostLedger

    @property
    def successes(self) -> int:
        # CASE-level aggregation: one case, one trial. A case succeeds
        # only if ALL of its evaluations pass (every grader, every
        # judge). Counting each (case, grader) pair as an independent
        # trial would inflate n, violate the binomial independence the
        # Wilson interval assumes, and manufacture a tight interval
        # that clears the gate dishonestly.
        if not self.results:
            return 0
        cases = {r.case_id for r in self.results}
        return sum(1 for cid in cases
                   if all(r.passed for r in self.results
                           if r.case_id == cid))

    @property
    def pass_rate(self) -> float:
        cases = {r.case_id for r in self.results}
        if not cases:
            return 0.0
        return self.successes / len(cases)

    def check_gate(self, thresholds: Sequence[GateThreshold]) -> None:
        """The CI gate. A regression or a blown cost budget blocks the merge.

        Raises RegressionError / CostGateExceededError — the merge does not
        proceed on an exception. "We'll fix the eval later" is how
        unverified systems ship.
        """
        cases = {r.case_id for r in self.results}
        lo, _ = wilson_interval(self.successes, len(cases)) \
            if cases else (0.0, 0.0)
        for t in thresholds:
            if t.metric == "pass_rate":
                if t.minimum is None:
                    raise EvalError("pass_rate gate requires a minimum")
                value = lo if t.use_wilson_lower else self.pass_rate
                if value < t.minimum:
                    raise RegressionError(
                        f"gate {t.metric}: {value:.3f} < {t.minimum:.3f}")
            elif t.metric == "cost_per_verified_success":
                if t.maximum is None:
                    raise EvalError(
                        "cost_per_verified_success gate requires a maximum")
                cpvs = self.ledger.cost_per_verified_success(self.successes)
                if cpvs > t.maximum:
                    raise CostGateExceededError(
                        f"gate {t.metric}: ${cpvs:.4f} > ${t.maximum:.4f}")
            else:
                raise EvalError(f"unknown gate metric {t.metric!r}")


class EvalSuite:
    """Runs graders + judges over a frozen dataset and produces a report.

    Chapter 16 imports this shape: walk_forward scores each fold with the
    same graders and merges the ScoreResults. The interface contract is
    ``grade_case(case, prediction) -> ScoreResult`` on graders and
    ``dataset.verify()`` before any scoring begins.
    """

    def __init__(self, name: str, dataset: FrozenDataset,
                 ledger: CostLedger | None = None) -> None:
        self._name = name
        self._dataset = dataset
        self._graders: list[DeterministicGrader] = []
        self._judges: list[LLMJudge] = []
        self._ledger = ledger or CostLedger()

    def add_grader(self, grader: DeterministicGrader) -> "EvalSuite":
        self._graders.append(grader)
        return self

    def add_judge(self, judge: LLMJudge) -> "EvalSuite":
        self._judges.append(judge)
        return self

    def run(self, predictions: Mapping[str, Mapping[str, Any]],
            judge_on: Sequence[str] | None = None) -> EvalReport:
        """Score every case with every grader; judges score the subset asked.

        ``judge_on``: case ids the (expensive) judges score. Everything else
        gets deterministic grades only — this is the cost discipline made
        executable: judge calls are budgeted, not sprinkled.
        """
        self._dataset.verify()
        results: list[ScoreResult] = []
        judge_ids = set(judge_on or [])
        for cid in self._dataset.case_ids():
            case = self._dataset.get(cid)
            pred = predictions.get(cid, {})
            for g in self._graders:
                results.append(g.grade(case, pred))
            if cid in judge_ids:
                verdicts = [j.judge(case, pred) for j in self._judges]
                self._ledger.record(f"judge:{cid}",
                                    sum(j._cost_per_call for j in self._judges))
                outcome = adjudicate(cid, verdicts)
                if isinstance(outcome, HumanReviewTicket):
                    # Routed, not scored: a human's verdict lands later and
                    # re-enters through the same ScoreResult shape.
                    continue
                results.append(ScoreResult(
                    case_id=cid, passed=outcome.passed, score=outcome.score,
                    grader=f"judge:{outcome.judge}",
                    detail={"rationale": outcome.rationale}))
        return EvalReport(suite=self._name, results=results, ledger=self._ledger)
