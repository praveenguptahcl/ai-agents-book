# Figure spec — Chapter 18: Securing Enterprise Frameworks

## Figure 18.1 — The adapter as a decorator (UML-style sequence)

**Type:** vertical sequence diagram, top to bottom.

**Participants (left to right):**
1. Framework (LangChain/LlamaIndex/AG2-style agent loop)
2. FrameworkAdapter.call()
3. Registry + Contract (Pydantic)
4. Session verifier (Ch 6 seam)
5. Approval tickets
6. Legacy function
7. Output reviewer (Ch 12 seam)
8. Evidence sink

**Flow:**
1. Framework → Adapter: `call(session, "dump_positions", raw_args)`.
2. Adapter → Registry: lookup "dump_positions". Miss → red `UnwrappedToolRefused` arrow back; the framework never reaches the legacy function.
3. Adapter → Session verifier: `verify(session, tool)`. Crash or denial → red `ScopeDenied` arrow back. Annotate: "authority before shape."
4. Adapter → Contract: `model_validate(raw_args)`. Failure → red `ContractViolation` arrow back. Annotate: "the legacy function never sees unvalidated input."
5. Adapter → Approval tickets: risk is WRITE/IRREVERSIBLE → consume ticket bound to args digest. None → amber `ApprovalRequired` arrow back (a pause, not a failure — the human may still approve).
6. Adapter → Legacy function: `adapt(bound)` translates the validated model into the legacy calling convention, then dispatch. Exception → wrapped `ToolExecutionError`.
7. Legacy function → Output reviewer: rendered output scanned. Flag → red `OutputBlocked` arrow; the planner never sees it.
8. Adapter → Evidence sink: `EvidenceRecord` on EVERY path (allowed / refused:unregistered / refused:scope / refused:contract / refused:approval / refused:output). Annotate: "refusals are evidence too."

**Styling:** the five checks as numbered gate icons (1–5) across the adapter's lifeline; refused paths in red, the approval pause in amber, the allowed path in green. A bracket on the left labeled "the framework sees a tool; the inside sees a trust boundary."

**Caption:** "The adapter's five checks, in order: registration, authority, contract, approval, output review. Every path — allowed or refused — emits an evidence record."
