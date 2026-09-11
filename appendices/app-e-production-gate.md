# Appendix E — Agent Production Standard v1.0, Executable

*The front-matter one-pager made into a certification gate. CI fails until all nine gates are demonstrated.*

Every chapter of this book ends with a mechanism and a test. This appendix is the mechanism for the whole book: nine checks that compress Parts I–VI into the smallest set of questions a production review can ask, and — crucially — code that *asks them of your system*, not of your slide deck.

The difference between a standard and a gate is enforcement. A standard says "systems should have an incident owner." A gate fails the build when the incident owner is unnamed. `production_gate.py` is the gate. It takes an **evidence bundle** — a dict mapping artifact keys to artifact content — and returns a `GateReport` whose `ships` property is `True` only when all nine gates pass.

The skeleton is deliberately small. The whole gate is one file, stdlib only, because the thing that certifies your production system must not itself be a supply-chain risk:

```python
@dataclass
class GateResult:
    """The verdict for one gate: pass, or exactly what is missing."""

    name: str
    chapter: str  # the book chapter whose machinery satisfies this gate
    passed: bool
    missing: List[str] = field(default_factory=list)
    remediation: str = ""

    def checklist_line(self) -> str:
        mark = "[x]" if self.passed else "[ ]"
        detail = "demonstrated" if self.passed else "MISSING: " + "; ".join(self.missing)
        return f"{mark} {self.name}: {detail}"


@dataclass
class GateReport:
    """The full certification verdict. ships is False unless ALL gates pass."""

    results: List[GateResult]

    @property
    def ships(self) -> bool:
        return all(r.passed for r in self.results)

    def failures(self) -> List[GateResult]:
        return [r for r in self.results if not r.passed]
```

## The nine gates

Each gate is a pure function from the evidence bundle to a `GateResult`. The `chapter` field anchors every gate to the machinery that satisfies it — the gate never invents requirements the book didn't teach. The nine, with their anchors:

1. **Identity** (Ch 3, Ch 6) — the identity document: service name, version, owner, and the *named* tenant-isolation mechanism. A system that cannot say whose data it may touch has no business touching data.
2. **Authority** (Ch 6, Ch 18) — the authority policy: principals, their scopes, and default-deny. An absent policy is not a permissive policy; the gate treats "no policy" as failure, and "policy without default-deny" as failure too.
3. **Contracts** (Ch 4) — validated input/output schemas for every tool the agent can call. No schema, no call.
4. **Threat model** (Ch 12) — named threats, each with a mitigation and an *honest residual*. A threat model that admits no residual is marketing, and the gate rejects it.
5. **Eval thresholds** (Ch 15) — the frozen golden suite, numeric bars (κ, Wilson lower bound, cost-per-verified-success), and the regression gate wired into CI. Opinions don't ship; numbers do.
6. **Rollback** (Ch 11, Ch 14) — the way back, as concrete steps, *drilled*: the gate demands the drill date. A runbook nobody has rehearsed is a rumor, not a control.
7. **Logging** (Ch 9) — the tamper-evident evidence spine: hash-chained records, named sink, retention ≥ 30 days.
8. **Escalation** (Ch 19) — risk tiers with a named approver and channel per tier. "Someone will look at it" is not a tier.
9. **Incident owner** (Ch 14) — one named human, reachable, with the runbook in hand. Accountability that can't be paged is decoration.

The authority gate shows the pattern the other eight follow — demand the artifact, inspect its content, fail on placeholders:

```python
def check_authority(evidence: Dict[str, Any]) -> GateResult:
    """Gate 2 — AUTHORITY (Ch 6, Ch 18). Who may do what, under which scopes?
    Default-deny is mandatory: an absent policy is not a permissive one."""
    artifact = evidence.get("authority")
    missing: List[str] = []
    if not isinstance(artifact, dict):
        missing.append("'authority' artifact absent: produce the authority policy")
    else:
        missing += _missing_str(artifact, "policy_doc")
        if artifact.get("default_deny") is not True:
            missing.append("'default_deny' must be True: deny-by-default is mandatory")
        principals = artifact.get("principals")
        if not isinstance(principals, list) or not principals:
            missing.append("'principals' must be a non-empty list")
        else:
            for i, p in enumerate(principals):
                if not isinstance(p, dict) or not p.get("name") or not p.get("scopes"):
                    missing.append(f"principals[{i}] must name the principal and its scopes")
    return _gate(
        "authority", "Ch 6, Ch 18", missing=missing,
        remediation="Produce the authority policy: principals, their scopes, and "
                    "default-deny (Ch 6). Wrappers must enforce it (Ch 18).",
    )
```

Notice what the gate does *not* do: it does not read your policy document and judge its wisdom. It checks that the document exists, that default-deny is asserted, and that every principal carries scopes. The gate is a floor, not a ceiling — it catches the systems that never wrote the document, which is where most production failures actually begin.

## The evidence-demand discipline

The most important test in `test_production_gate.py` is not any of the nine negative fixtures — it is the forgery suite. A certification gate that accepts claims is a rubber stamp, and every chapter of this book has argued that rubber stamps are the failure mode. So the suite submits systems that *claim* each gate with placeholder artifacts: an identity with `"version": ""`, an authority policy with `default_deny: False`, a threat model whose residual is an empty string, eval thresholds with `kappa_min: "high"`, a rollback runbook never drilled, logging with seven days of retention, an escalation tier whose approver is blank, an incident owner with no runbook. Every forgery fails — and fails *only* its own gate, so the report points the engineer at exactly one fix.

The runner itself is four lines, and it is the line your CI calls:

```python
def run_standard(evidence: Dict[str, Any]) -> GateReport:
    """Run all nine gates over the evidence bundle. CI calls this; the build
    fails unless report.ships is True."""
    return GateReport(results=[gate(evidence) for gate in GATES])
```

Wire it into CI as a hard gate: collect the evidence bundle from the system's configuration and documentation sources at build time, run the standard, and fail the pipeline unless `report.ships` is true. Print `report.render()` into the build log — it produces the checklist the one-pager promises, with each failure's remediation attached, so the path from red to green is never a mystery:

```
Agent Production Standard v1.0 — certification
[x] identity: demonstrated
[ ] authority: MISSING: 'default_deny' must be True: deny-by-default is mandatory
...
VERDICT: NO SHIP — 1 gate(s) undemonstrated.
  -> authority: Produce the authority policy: principals, their scopes, and default-deny (Ch 6). Wrappers must enforce it (Ch 18).
```

## Where the evidence bundle comes from

The gate's most common objection is practical: "we have all of this, but it's scattered." That is exactly what the evidence bundle is for — it is the *index* of your production-readiness artifacts, and building it is the first certification exercise. In a real repository, the mapping looks like this:

- `identity` ← `docs/identity.md` plus the deployment config that binds the tenant-isolation mechanism (Ch 6). If the mechanism is named in a design doc but not in the deployment config, the gate is telling you something true: the isolation is aspirational.
- `authority` ← `policies/authority.md` rendered from the same policy-as-code the wrappers enforce (Ch 18). The gate checks the *rendered* policy, not the source — what ships is what is checked.
- `contracts` ← generated from the Pydantic models themselves (Ch 4): `Model.model_json_schema()` for every registered tool. This is the one gate where the evidence should be machine-generated from the code, so the gate can never drift from the implementation.
- `threat_model` ← `docs/threat-model.md`, reviewed quarterly; the gate checks the `last_reviewed` field the same way the rollback gate checks `last_drilled` — a threat model from two years ago is a history document.
- `eval_thresholds` ← `evals/config.yaml` plus the CI job definition that enforces the regression gate (Ch 15). The gate demands both: thresholds without enforcement are intentions.
- `rollback` ← `runbooks/rollback.md`, and the drill date comes from the incident log, not from someone's memory.
- `logging` ← the evidence-spine deployment config (Ch 9): sink, hash algorithm, retention. This one the gate could verify *live* — query the sink for the hash chain head — and a mature deployment should.
- `escalation` ← `policies/escalation.md` (Ch 19), cross-checked against the on-call rotation so the named approver is someone who actually carries the pager.
- `incident_owner` ← the on-call rotation's current entry (Ch 14), resolved at build time. A named owner who left the company three months ago fails the human test even if the field is filled — which is why the contact must resolve, not merely exist.

Build the bundle in CI from these sources and the certification becomes continuous: every commit re-runs the nine gates against the current artifacts, and a rotting runbook fails the build the week it rots, not the quarter the auditor finds it.

## Running a production review with the one-pager

The front-matter one-pager is the same nine gates in checklist form — the thing you print, pin to the wall, and walk through in a production review. The discipline of the review is the discipline of the code: for each gate, the system owner must *produce the artifact*, not describe it. "Show me the evidence spine config" beats "we have logging" the way a test beats a promise. When a gate fails, the remediation names the exact document to write — the review ends with a work list, not a feeling.

*Figure: the nine-gate certification wall — all nine gates as a single printable checklist, each with its artifact and chapter anchor, feeding the `ships` traffic light (one-line reference; full spec in `figs/app-e-figspec.md`).*

The Standard is versioned (`STANDARD_VERSION = "1.0"`, pinned in a test) because standards drift. When the book's second edition adds a gate — and it will, because the threat landscape will — the version bump forces every certified system to re-certify against the new bar. Certification is a timestamp, not a tattoo.

## What the Standard does not do

It does not replace the chapters. A system can pass all nine gates and still be a bad product, an unprofitable desk, or an agent nobody wants to use — the Standard certifies *production readiness*, not quality, taste, or profitability. It does not audit the contents of your threat model for completeness, your eval suite for coverage, or your contracts for correctness; those are Ch 12, Ch 15, and Ch 4 reviews, and they need human experts. What it guarantees is structural: that the artifacts those reviews require *exist*, are *named*, and are *current enough to be checked*. That is a smaller claim than "this system is safe," and it is the reason the claim is executable.
