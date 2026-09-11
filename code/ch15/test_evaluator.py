"""Adversarial tests for Chapter 15's grading machinery.

Each test names the failure it prevents. The suite is organized as
attacks on the eval system itself — because an eval harness that can be
fooled, muted, or gamed is worse than no harness: it manufactures
confidence.
"""

import math

import pytest

from evaluator import (
    Claim,
    CodeTask,
    CodeTaskResult,
    CostGateExceededError,
    CostLedger,
    DatasetTamperedError,
    DeterministicGrader,
    EvalCase,
    EvalReport,
    EvalSuite,
    ExactMatchGrader,
    FrozenDataset,
    GateThreshold,
    HumanReviewTicket,
    JudgeVerdict,
    LLMJudge,
    NondeterministicGraderError,
    RealBarsOnlyGrader,
    RegressionError,
    ScoreResult,
    UnseededGraderError,
    adjudicate,
    cohens_kappa,
    content_hash,
    grade_code_task,
    groundedness,
    recall_at_k,
    resolve_rate,
    wilson_interval,
)


def _case(cid="c1", expected=None):
    return EvalCase(case_id=cid, inputs={"q": "x"},
                    expected=expected or {"a": 1}, source="test")


# ---------------------------------------------------------------------------
# Frozen golden sets
# ---------------------------------------------------------------------------

def test_frozen_dataset_verifies_clean():
    ds = FrozenDataset("g", [_case("a"), _case("b")])
    ds.verify()  # must not raise
    assert ds.case_ids() == ["a", "b"]
    assert len(ds) == 2


def test_frozen_dataset_detects_mutation():
    ds = FrozenDataset("g", [_case("a")])
    # Simulate post-pinning tampering: swap in an edited case object.
    tampered = EvalCase(case_id="a", inputs={"q": "x"},
                        expected={"a": 999}, source="test")
    ds._cases["a"] = tampered
    with pytest.raises(DatasetTamperedError):
        ds.verify()


def test_frozen_dataset_detects_added_case():
    ds = FrozenDataset("g", [_case("a")])
    ds._cases["b"] = _case("b")
    with pytest.raises(DatasetTamperedError):
        ds.get("a")


def test_frozen_dataset_rejects_duplicate_ids():
    with pytest.raises(Exception):
        FrozenDataset("g", [_case("a"), _case("a")])


def test_frozen_dataset_unknown_case_is_an_error():
    ds = FrozenDataset("g", [_case("a")])
    with pytest.raises(Exception):
        ds.get("nope")


def test_content_hash_is_stable():
    assert content_hash({"b": 2, "a": 1}) == content_hash({"a": 1, "b": 2})


# ---------------------------------------------------------------------------
# Deterministic graders
# ---------------------------------------------------------------------------

def test_exact_match_grader_passes_and_fails():
    g = ExactMatchGrader("exact", seed=7)
    assert g.grade(_case(expected={"a": 1}), {"a": 1}).passed
    assert not g.grade(_case(expected={"a": 1}), {"a": 2}).passed


def test_grader_is_deterministic_across_calls():
    # Same seed, same inputs → the grade() self-check passes and the
    # returned scores are identical. Determinism is asserted, not assumed.
    g = ExactMatchGrader("exact", seed=42)
    r1 = g.grade(_case(expected={"a": 1}), {"a": 1})
    r2 = g.grade(_case(expected={"a": 1}), {"a": 1})
    assert (r1.passed, r1.score) == (r2.passed, r2.score)


def test_unseeded_grader_is_refused():
    with pytest.raises(UnseededGraderError):
        ExactMatchGrader("exact", seed=None)


def test_self_disagreeing_grader_is_caught():
    class FlipFlop(DeterministicGrader):
        def __init__(self):
            super().__init__("flipflop", seed=1)
            self.calls = 0

        def _grade(self, case, prediction, rng):
            self.calls += 1
            s = 1.0 if self.calls % 2 else 0.0
            return ScoreResult(case.case_id, s == 1.0, s, self.name)

    with pytest.raises(NondeterministicGraderError):
        FlipFlop().grade(_case(), {"a": 1})


def test_grader_rng_is_fresh_per_call():
    # Grading order must not matter: two graders with the same seed grade
    # identically even when interleaved.
    g1, g2 = ExactMatchGrader("e", seed=3), ExactMatchGrader("e", seed=3)
    r1 = g1.grade(_case("x", {"a": 1}), {"a": 1})
    g2.grade(_case("y", {"a": 2}), {"a": 9})  # interleave a different case
    r2 = g1.grade(_case("x", {"a": 1}), {"a": 1})
    assert (r1.passed, r1.score) == (r2.passed, r2.score)


# ---------------------------------------------------------------------------
# The trading-thesis grader: REAL bars only
# ---------------------------------------------------------------------------

def test_real_bars_only_grader_accepts_real():
    g = RealBarsOnlyGrader("realbars", seed=1)
    pred = {"cited_bars": [{"ts": "t1", "label": "REAL"},
                           {"ts": "t2", "label": "REAL"}]}
    assert g.grade(_case(), pred).passed


def test_real_bars_only_grader_rejects_synthetic():
    # A thesis grounded in synthetic bars presented as history is
    # fabrication — the grader fails it, loudly.
    g = RealBarsOnlyGrader("realbars", seed=1)
    pred = {"cited_bars": [{"ts": "t1", "label": "REAL"},
                           {"ts": "t2", "label": "SYNTHETIC"}]}
    r = g.grade(_case(), pred)
    assert not r.passed
    assert r.detail["non_real_citations"] == 1


def test_real_bars_only_grader_rejects_unlabeled():
    g = RealBarsOnlyGrader("realbars", seed=1)
    pred = {"cited_bars": [{"ts": "t1"}]}  # no label at all
    assert not g.grade(_case(), pred).passed


# ---------------------------------------------------------------------------
# Agreement statistics: kappa and Wilson, worked fixtures
# ---------------------------------------------------------------------------

def test_kappa_perfect_agreement():
    assert cohens_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == pytest.approx(1.0)


def test_kappa_known_fixture():
    # Hand-worked in the chapter: a=[1,1,1,0,0], b=[1,1,0,0,0].
    # observed = 4/5 = 0.8; expected = (3/5)(2/5) + (2/5)(3/5) = 0.48;
    # kappa = (0.8 - 0.48) / (1 - 0.48) = 8/13.
    assert cohens_kappa([1, 1, 1, 0, 0], [1, 1, 0, 0, 0]) == pytest.approx(8 / 13)


def test_kappa_chance_agreement_is_zero():
    # Both judges say "pass" 50% independently → kappa ≈ 0, not 0.5.
    a = [1, 1, 0, 0] * 25
    b = [1, 0, 1, 0] * 25
    assert cohens_kappa(a, b) == pytest.approx(0.0, abs=1e-9)


def test_kappa_single_label_degenerate():
    # Both raters, one label, full agreement → defined as 1.0, not NaN.
    assert cohens_kappa([1, 1, 1], [1, 1, 1]) == 1.0


def test_kappa_rejects_mismatched_lengths():
    with pytest.raises(Exception):
        cohens_kappa([1, 0], [1])


def test_wilson_interval_tightens_with_n():
    lo12, hi12 = wilson_interval(11, 12)
    lo1200, hi1200 = wilson_interval(1100, 1200)
    assert (hi12 - lo12) > (hi1200 - lo1200)  # more data, tighter truth
    assert lo12 < 11 / 12 < hi12
    assert lo1200 < 1100 / 1200 < hi1200


def test_wilson_interval_never_trusts_bare_percentage():
    # "92% on n=12" is (0.65, 0.99) — the interval tells the real story.
    lo, hi = wilson_interval(11, 12)
    assert lo == pytest.approx(0.646, abs=0.01)
    assert hi == pytest.approx(0.985, abs=0.01)


def test_wilson_rejects_bad_inputs():
    with pytest.raises(Exception):
        wilson_interval(5, 0)
    with pytest.raises(Exception):
        wilson_interval(13, 12)


# ---------------------------------------------------------------------------
# Judges: disagreement routes to a human
# ---------------------------------------------------------------------------

def _stub_judge(name, verdict):
    def fn(case, pred):
        return JudgeVerdict(case.case_id, name, verdict, 1.0 if verdict else 0.0,
                            f"{name} says {verdict}")
    return LLMJudge(name, fn, cost_per_call=0.02)


def test_agreeing_judges_return_a_verdict():
    v = [JudgeVerdict("c1", "j1", True, 0.9, "ok"),
         JudgeVerdict("c1", "j2", True, 0.8, "ok")]
    out = adjudicate("c1", v)
    assert not isinstance(out, HumanReviewTicket)
    assert out.passed


def test_disagreeing_judges_route_to_human():
    # The machine never breaks its own tie.
    v = [JudgeVerdict("c1", "j1", True, 0.9, "ok"),
         JudgeVerdict("c1", "j2", False, 0.2, "no")]
    out = adjudicate("c1", v)
    assert isinstance(out, HumanReviewTicket)
    assert out.judges == ("j1", "j2")
    assert out.verdicts == (True, False)


def test_adjudicate_needs_a_verdict():
    with pytest.raises(Exception):
        adjudicate("c1", [])


def test_judge_cost_is_accounted():
    j = _stub_judge("j1", True)
    j.judge(_case(), {})
    j.judge(_case(), {})
    assert j.total_cost == pytest.approx(0.04)
    assert j.calls == 2


# ---------------------------------------------------------------------------
# Cost-per-verified-success
# ---------------------------------------------------------------------------

def test_cost_per_verified_success():
    ledger = CostLedger()
    ledger.record("judge:c1", 0.02)
    ledger.record("judge:c2", 0.02)
    assert ledger.cost_per_verified_success(2) == pytest.approx(0.02)
    assert ledger.total == pytest.approx(0.04)


def test_zero_verified_successes_is_infinite_cost():
    # No verified successes → no price-performance, just a bill.
    ledger = CostLedger()
    ledger.record("judge:c1", 0.02)
    assert ledger.cost_per_verified_success(0) == math.inf


def test_negative_cost_refused():
    with pytest.raises(Exception):
        CostLedger().record("x", -1.0)


# ---------------------------------------------------------------------------
# Retrieval evals: recall@k vs groundedness
# ---------------------------------------------------------------------------

def test_recall_at_k():
    assert recall_at_k(["d1", "d2", "d3"], ["d1", "d9"], 2) == pytest.approx(0.5)
    assert recall_at_k(["d1", "d9"], ["d1", "d9"], 2) == pytest.approx(1.0)


def test_recall_at_k_rejects_bad_k():
    with pytest.raises(Exception):
        recall_at_k(["d1"], ["d1"], 0)


def test_groundedness_all_claims_traced():
    claims = [Claim("revenue up", "s1"), Claim("margin flat", "s2")]
    assert groundedness(claims, ["s1", "s2", "s3"]) == pytest.approx(1.0)


def test_groundedness_uncited_claim_fails():
    # A claim with no supporting span is a guess in citation's clothes.
    claims = [Claim("revenue up", "s1"), Claim("CEO resigned", None)]
    assert groundedness(claims, ["s1"]) == pytest.approx(0.5)


def test_groundedness_fabricated_citation_fails():
    # Citing a span the retriever never returned is dishonesty.
    claims = [Claim("revenue up", "s1"), Claim("margin flat", "sX")]
    assert groundedness(claims, ["s1", "s2"]) == pytest.approx(0.5)


def test_groundedness_needs_claims():
    with pytest.raises(Exception):
        groundedness([], ["s1"])


# ---------------------------------------------------------------------------
# SWE-bench-style code-task evals
# ---------------------------------------------------------------------------

def _codetask():
    return CodeTask(task_id="t1", fail_to_pass=("test_a",),
                    pass_to_pass=("test_b", "test_c"))


def test_code_task_resolved():
    r = CodeTaskResult("t1", False, {"test_a": True, "test_b": True,
                                     "test_c": True})
    out = grade_code_task(_codetask(), r)
    assert out.passed and out.detail["resolved"]


def test_code_task_unfixed_fails():
    r = CodeTaskResult("t1", False, {"test_a": False, "test_b": True,
                                     "test_c": True})
    assert not grade_code_task(_codetask(), r).passed


def test_code_task_regression_fails():
    # The fix works but broke an existing test — not resolved.
    r = CodeTaskResult("t1", False, {"test_a": True, "test_b": True,
                                     "test_c": False})
    out = grade_code_task(_codetask(), r)
    assert not out.passed
    assert not out.detail["pass_to_pass_ok"]


def test_code_task_touching_tests_is_cheating():
    # The agent "fixed" the tests instead of the code.
    r = CodeTaskResult("t1", True, {"test_a": True, "test_b": True,
                                    "test_c": True})
    out = grade_code_task(_codetask(), r)
    assert not out.passed
    assert out.detail["reason"] == "patch touched forbidden paths"


def test_resolve_rate():
    rs = [ScoreResult("t1", True, 1.0, "code_task"),
          ScoreResult("t2", False, 0.0, "code_task")]
    assert resolve_rate(rs) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# The suite and the CI gate
# ---------------------------------------------------------------------------

def _suite(n_cases=4, n_pass=3):
    cases = [EvalCase(f"c{i}", {"q": i}, {"a": i}) for i in range(n_cases)]
    ds = FrozenDataset("s", cases)
    preds = {f"c{i}": {"a": i if i < n_pass else -1} for i in range(n_cases)}
    suite = EvalSuite("s", ds).add_grader(ExactMatchGrader("exact", seed=1))
    return suite, preds


def test_suite_runs_graders_over_frozen_dataset():
    suite, preds = _suite()
    report = suite.run(preds)
    assert report.successes == 3
    assert report.pass_rate == pytest.approx(0.75)


def test_suite_scores_judges_only_where_budgeted():
    suite, preds = _suite()
    suite.add_judge(_stub_judge("j1", True)).add_judge(_stub_judge("j2", True))
    report = suite.run(preds, judge_on=["c0"])
    judged = [r for r in report.results if r.grader.startswith("judge:")]
    assert len(judged) == 1  # only c0 got the expensive judges
    assert report.ledger.total == pytest.approx(0.04)


def test_gate_blocks_regression():
    suite, preds = _suite(n_cases=20, n_pass=10)  # 50% pass rate
    report = suite.run(preds)
    with pytest.raises(RegressionError):
        report.check_gate([GateThreshold("pass_rate", minimum=0.9)])


def test_gate_uses_wilson_lower_by_default():
    # 19/20 = 95% point estimate, but the Wilson lower bound (~0.76)
    # is what the honest gate checks.
    suite, preds = _suite(n_cases=20, n_pass=19)
    report = suite.run(preds)
    with pytest.raises(RegressionError):
        report.check_gate([GateThreshold("pass_rate", minimum=0.9)])


def test_gate_passes_a_real_improvement():
    suite, preds = _suite(n_cases=200, n_pass=190)
    report = suite.run(preds)
    report.check_gate([GateThreshold("pass_rate", minimum=0.9)])  # no raise


def test_gate_blocks_blown_cost_budget():
    suite, preds = _suite(n_cases=4, n_pass=1)
    suite.add_judge(_stub_judge("j1", False))
    report = suite.run(preds, judge_on=["c0", "c1", "c2", "c3"])
    # Judge verdicts all fail; the 1 grader success stands alone:
    # 1 verified success at $0.08 total → $0.08 per success > $0.05 budget.
    with pytest.raises(CostGateExceededError):
        report.check_gate([GateThreshold("cost_per_verified_success",
                                         minimum=0.05)])


def test_gate_rejects_unknown_metric():
    suite, preds = _suite()
    report = suite.run(preds)
    with pytest.raises(Exception):
        report.check_gate([GateThreshold("vibes", minimum=0.9)])


def test_suite_detects_tampered_dataset_before_scoring():
    suite, preds = _suite()
    suite._dataset._cases["c0"] = EvalCase("c0", {"q": 0}, {"a": -999})
    with pytest.raises(DatasetTamperedError):
        suite.run(preds)


def test_human_routed_cases_do_not_silently_score():
    # A disagreed case produces NO ScoreResult — the human's verdict
    # re-enters later. Silence here would be a fabricated consensus.
    cases = [EvalCase("c0", {"q": 0}, {"a": 0})]
    ds = FrozenDataset("s", cases)
    suite = (EvalSuite("s", ds)
             .add_judge(_stub_judge("j1", True))
             .add_judge(_stub_judge("j2", False)))
    report = suite.run({"c0": {"a": 0}}, judge_on=["c0"])
    assert report.results == []
