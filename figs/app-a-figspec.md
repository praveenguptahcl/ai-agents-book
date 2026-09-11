# Figure spec — Appendix A: The A2A 1.0 Protocol validator

One-line chapter reference: the A2A trust boundary — what the card claims, what the validator checks, and what stays with the human.

## FIG-A1 — The three-layer protocol stack (spec §1.3)

- Panel: three horizontal layers. Bottom: "Canonical data model (proto)" — Task, Message, AgentCard, Part, Artifact, Extension. Middle: "Abstract operations" — Send Message, Stream Message, Get Task, List Tasks, Cancel Task, Get Agent Card. Top: "Protocol bindings" — JSON-RPC (PascalCase methods), gRPC, HTTP+JSON REST.
- Annotation: "The validator in this appendix checks the bottom layer. Bindings are transport; semantics live in the model."
- Alt text: Three stacked boxes labeled data model, operations, and bindings, showing A2A v1.0.0's layered architecture.

## FIG-A2 — The lifecycle with teeth (spec §4.1.3 + book rule)

- Panel: state machine diagram of the nine TaskState values. Nodes: submitted, working, input-required, auth-required in the active cluster; completed, failed, canceled, rejected as terminal nodes with no outgoing edges (drawn with a heavy border); unspecified grayed out and crossed. Edges per ALLOWED_TRANSITIONS. Two red dashed edges struck through: completed → working ("resurrection refused") and submitted → completed ("skip refused").
- Caption data: terminal states are absorbing; the transition table is the book's rule, labeled as such.
- Alt text: A2A task state machine with terminal states absorbing and two illegal transitions crossed out in red.

## FIG-A3 — The auth decision (spec §4.5)

- Panel: flowchart of validate_request_auth. Diamond 1: "Card declares schemes?" No → warning, "open agent: treat every response as untrusted." Yes → Diamond 2: "Credential presented?" No → reject (auth.missing_credential). Yes → Diamond 3: "Scheme declared?" No → reject (auth.undeclared_scheme). Yes → Diamond 4: "Verified?" No → reject (auth.unverified_credential) — this box highlighted: "presented ≠ verified." Yes → accept.
- Alt text: Four-diamond flowchart for A2A request authentication ending in one accept and three rejections.

## FIG-A4 — Capability vs authority (the house coinage)

- Panel: two columns. Left, "The card claims (capability)": skill list, declared schemes, signatures. Right, "Your side decides (authority)": contract validation, verified credentials, output review, human judgment on the counterparty. A thick vertical line between them labeled "the boundary this appendix patrols." A thin arrow crosses it labeled "validated shape, not trust."
- Alt text: Two-column diagram separating capability claims from authority decisions with the validator on the boundary.
