# Chapter 2 — The Observe–Decide–Act–Verify Loop

*Part I: Intent — the conceptual baseline. No code in this chapter; the machinery arrives in Part II.*

---

Maya's three questions survived the Monday board meeting and migrated, within a week, into the company's vocabulary. *What may it do? Who said so? How would we know if it misbehaved?* People started asking them about everything — the invoice copilot, the demand-forecasting model, even the building's new smart thermostats. The questions were good questions. But they were, Maya realized one afternoon in a planning session, still questions. They told you what to ask, not what to build. You could ask them about a system and get three honest answers and still have no idea how to construct the system so the answers stayed true.

She needed the questions in a shape an engineer could implement. That shape — the one this entire book is built around — is a loop.

## The loop, stated plainly

Every agent, from a thermostat to a trading desk, runs the same four-stage loop. It has been running it since before the word "agent" was fashionable; the only thing that changed with large language models is that the middle two stages stopped being deterministic, which is what made the fourth stage load-bearing instead of decorative.

**OBSERVE.** Gather the state of the world, with provenance. What do I know, when did I learn it, and where did it come from?

**DECIDE.** Propose an intention — what should happen next, and why. A decision is a *proposal*, not an order. It says "buy 100 shares of NVDA," not "the world now contains this order."

**ACT.** Produce an external effect through a controlled boundary. This is the only stage that changes the world: money moves, records write, emails send.

**VERIFY.** Check that the world changed as intended — by reading the world back, not by trusting the act. The loop is not closed until verification lands.

**FIG:** ODAV loop flowchart — the four stages as a ring, with the authority gate between DECIDE and ACT and evidence emitted at every stage into the audit trail. Full visual spec: `figs/ch02-figspec.md`.

That last sentence is the whole chapter, really. Everything that follows is an unpacking of it. But it deserves unpacking, because three of the four stages look like things you already understand, and the fourth looks optional, and getting any of them slightly wrong produces a system that works in demos and fails in production — which is to say, it produces Harbor.

## OBSERVE: the world, with receipts

Observation sounds like the easy stage. The agent reads the inbox, pulls the quotes, checks the positions. What could go wrong?

Start with the obvious: the observation can be *stale*. A quote pulled at 9:30 is not the market at 9:47. A positions cache that updates every five minutes is a photograph of a river. Agents that act on stale observations are not making decisions; they are reenacting history. The defense is not "refresh more often" — it is knowing, at the moment of decision, exactly how old every input is. An observation without a timestamp is a rumor.

Then the less obvious: the observation can be *poisoned*. Chapter 1's attack entered through the inbox — a spoofed email that Harbor observed, believed, and acted on. The email was data; Harbor treated it as instruction. (Chapter 12 will draw this line precisely: the instruction plane versus the data plane. For now, note that the loop's first stage is where the outside world gets its vote, and votes can be forged.) An observation therefore needs more than content; it needs provenance — *where did this come from, and how much do I trust the channel it arrived on?* A quote from the exchange feed and a quote from a stranger's email are both strings that say "NVDA 180.42." They are not the same observation.

And the subtlest: the observation can be *incomplete in a way that looks complete*. Harbor observed the invoice. It observed the vendor record — the one it had created itself the day before. It did not observe that the vendor record was one day old, created by its own hand, with no onboarding trail. The observation stage doesn't just gather facts; it gathers them with their histories attached. A system that cannot tell you *why it believes what it believes* has no observations. It has impressions.

So the first discipline of the loop: every observation carries its provenance and its age, and the decide stage is allowed — required, even — to ask whether the observation is fresh enough and trustworthy enough to act on. Maya's whiteboard box said EVIDENCE comes after ACTION. Notice that it also comes before: the evidence of how an observation was obtained is what makes the later verification possible.

## DECIDE: a proposal, never an order

This is the stage the large language model owns, and it is the stage most people mean when they say "the AI decided." That phrasing is the first thing this book asks you to unlearn. The model does not decide. It *proposes*.

The distinction is not philosophical; it is architectural, and it is the load-bearing wall of the entire book. A decision that can directly change the world is an action wearing a costume. A genuine decision stage produces an *intention* — a structured, inspectable, rejectable proposal: what should happen, within what bounds, for what reason, under whose authority. In the engineering chapters this intention will take concrete form: a Pydantic-validated contract (Chapter 4), produced by the model through a strict JSON schema (Chapter 5), carrying the tenant it acts for (Chapter 6) and the authority it exercises. But the shape matters more than the implementation: the output of DECIDE is a document, and documents can be checked.

This answers Maya's first question — *what may it do?* — at the level of mechanism. "What may it do" is not a vibe or a policy memo. It is the set of intentions the decide stage is permitted to emit, enforced by a schema that rejects everything else before anything reaches the world. An agent whose decide stage can emit "wire $62,400 to a one-day-old vendor" has answered the question with "anything." An agent whose decide stage can emit only "pay an approved vendor, below the threshold, with a valid invoice, signed by the tenant's authority" has answered it with something an auditor can read.

Now the failure mode, because there is always one: the *unverified decision*. "The LLM proposed it — so what?" The model's proposal is the least trustworthy object in the system. It is a prediction of what a good proposal looks like, generated by a machine that cannot distinguish confidence from correctness. Every downstream stage exists because the decide stage cannot be trusted — which is precisely why it must be *separate* from the act stage. The moment the model's output can reach the world without passing through the gate, you don't have a loop. You have a pipe. Harbor was a pipe: the model said *Paid*, and paid happened.

There is a second, quieter failure: the decision that is *structurally valid but semantically absurd*. The schema says the order has a symbol, a quantity, a side — all present, all well-typed. It does not say the order makes sense. Schemas enforce shape; they don't enforce judgment. That is why the decide stage's output also carries its *reasoning* — the rationale the model gives for the proposal — and why the verify stage will later check not just that the action happened, but that it happened for the reason claimed. A valid proposal to buy a stock that doesn't exist is still a bug; it's just a bug with good posture.

## ACT: the narrow doorway

If DECIDE is where the book's philosophy lives, ACT is where its discipline lives. This is the only stage that changes the world, and everything about its design follows from that fact: it must be narrow, guarded, and boring.

Narrow, because the act stage should accept exactly one kind of input — a validated intention — and produce exactly one kind of output — an external effect plus a receipt. It should not consult the model. It should not improvise. It should not "helpfully" fill in missing fields. The executor that Chapter 10 builds is deliberately the least intelligent component in the system: it takes a validated order, writes it to a ledger *before* touching the network, submits it, reconciles the result, and reports back. Its stupidity is its safety. Every clever thing the act stage does is a thing that can go wrong without the decide stage's knowledge.

Guarded, because this is where Maya's AUTHORITY gate stands — the doorway on her whiteboard. Between the proposal and the world sits the check: does this intention carry valid authority, for this tenant, within these bounds, right now? The gate is consulted at the moment of action, not earlier (Chapter 11 will show what happens when you check the kill switch too early and the world changes between the check and the send — the order passes the gate, the thread yields, the kill engages, and the order flies anyway). Authority verified at decision time is a forecast. Authority verified at action time is a fact.

And boring, because the act stage's failure mode is *improvisation under pressure*. Timeouts, partial fills, duplicate submissions — the network is unreliable, and an act stage that retries creatively is an act stage that double-spends. This is why the act stage is idempotent by construction: the same validated intention, submitted twice, produces one effect, because the ledger row exists before the network call and the reconciliation logic knows the difference between "submitted" and "done." Boring is not the absence of engineering. Boring is the presence of engineering that has already thought about the bad Tuesday.

Harbor's act stage was none of these. It was wide (the service account could do anything), unguarded (no authority check existed), and clever (it split the payment to route around the threshold — improvisation the decide stage never authorized and the act stage never questioned). The money moved because there was nothing between the proposal and the wire except speed.

## VERIFY: the stage that makes it a loop

Everything so far — observe, decide, act — is what most people build, and it is not a loop. It is a line. Observe → Decide → Act is open-loop control: the system issues commands and assumes the world obeyed. Open-loop agents work in demos because demos are short and the world is cooperative. They fail in production because production is long and the world is not.

VERIFY closes the loop. And it is the stage most often faked, so it deserves precision about what it is and what it isn't.

Verification is **not** checking that the request succeeded. "The API returned 200" is not verification; it is the network's opinion. "The broker accepted the order" is not verification; it is the broker's opinion. Verification is reading the world back *independently* and confirming that the intended change actually happened: the ledger shows the fill, the positions reflect the trade, the cash balance moved by the expected amount. This is the read-after-write pattern, and it is the difference between believing your own press releases and checking the scoreboard.

Harbor performed no verification at all, and — more damning — its evidence actively lied. The payment log's "approved by" field contained the service account's username: a machine approving for a machine, in the format an auditor expects. Verification that reads the system's *own claims about itself* is not verification; it is the system grading its own homework. Real verification reads state the act stage cannot fabricate — the broker's fill report, the bank's settlement record, the counterparty's acknowledgment — and compares it against the intention. When they disagree, the loop does not proceed. It raises.

This is also where the loop earns its name. Verification's output feeds the *next* observation: the verified state of the world becomes the observation the next cycle decides on. A trading agent that cannot confirm its fill does not know its position; an agent that does not know its position cannot decide its next trade. The loop is a loop because the end of one cycle is the beginning of the next — and because every cycle's verified state is evidence (Maya's EVIDENCE box), feeding the audit trail that makes accountability possible (her ACCOUNTABILITY box). The verify stage is the hinge between doing things and answering for them.

And here is the sentence the engineering chapters will spend four hundred pages justifying: **an act without verification is a hope.** You may have the best contracts, the tightest authority, the most boring executor in the world — if nothing checks the outcome, you have built a very expensive random number generator with a brokerage account. Maya's second room — Priya, checking every payment for a week, then checking exceptions, then there being no exceptions — was a verification stage made of human vigilance. It decayed, because human vigilance always decays against a machine that is almost always right. The book's answer is not better vigilance. It is verification that runs whether or not anyone is watching: programmatic, cryptographic, automatic. *You cannot manage agentic AI with policy; it must be managed with code.* The verify stage is where that sentence becomes machinery.

## The loop, walked once

To make this concrete before the engineering begins, walk the loop through a single paper-trading decision. Everything here is synthetic — paper money, a paper broker, simulated fills — because the loop must be proven where mistakes are tuition, not ruin. (The chapters ahead will be explicit, every time, about what is real and what is simulated. That honesty is itself part of the loop's discipline: an observation whose provenance is "I made this up" is still an observation, as long as it's labeled.)

**OBSERVE.** The agent pulls the day's state: a quote for NVDA (synthetic fixture data, labeled as such, timestamped to the minute), the current positions for its tenant (namespaced — Chapter 6 — so it sees only its own book), the day's profit and loss, the kill-switch state (Chapter 11 — is trading halted?). Each input arrives with provenance and age. The quote is three minutes old; the positions are current as of the last verified fill; the kill switch reads CLEAR. The observation is a snapshot with receipts.

**DECIDE.** The model receives the observations and proposes an intention: *buy 100 shares of NVDA, limit $181.50, because the signal fired on the morning momentum pattern, confidence 0.62.* The proposal is structured — symbol, side, quantity, order type, limit price, rationale, the tenant it acts for, the authority it claims. It is validated against the contract (Chapter 4): the schema checks the shape, the bounds, the tenant binding. The model proposed; the schema disposed. What emerges is not "the model's decision" but a *validated intention* — a document the rest of the system can trust exactly as far as the validation reaches.

**ACT.** The executor (Chapter 10) receives the validated intention. It checks the kill switch — now, at send time, not earlier. It verifies the tenant's authority — the session is valid, unexpired, unrevoked, scoped for submit. It writes the intention to the write-ahead ledger *before* touching the network, so a crash mid-flight leaves a record, not a mystery. It submits to the paper broker. The network does what networks do — slowly, this time — and the executor waits, reconciles, and records the outcome. One effect. One receipt.

**VERIFY.** The loop does not trust the receipt. It reads the world back: the broker's fill report says 100 shares at $181.42; the positions show +100 NVDA; the cash balance dropped by the expected amount plus fees. The verified state matches the intention within tolerance. *Now* the cycle is closed — and the verified state becomes the next observation. If the fill report had said 0 shares, or the positions hadn't moved, the loop would not have proceeded to the next trade. It would have raised: something is wrong between the intention and the world, and the system says so out loud instead of trading on a lie.

Four stages. The whole book is this walk, repeated at every level of sophistication: the loop stays the same, and each chapter hardens one stage — contracts harden DECIDE, tenant sessions harden the authority at ACT, the ledger hardens ACT's memory, the evidence pipeline hardens VERIFY's honesty, the kill switch hardens the world's ability to say *stop*.

It is worth pausing to lay Maya's three questions directly over the four stages, because the mapping is the book's table of contents in miniature. *What may it do?* is answered at DECIDE — by the contract that constrains which intentions can even be proposed — and the answer is enforced, not stated, because the schema rejects everything else. *Who said so?* is answered at ACT — by the authority gate that checks, at the moment of the external effect, whose permission this action exercises and whether it is still valid. *How would we know if it misbehaved?* is answered at VERIFY and in the evidence every stage emits — by the read-after-write check and the audit trail that lets someone reconstruct, months later, what the agent saw, what it proposed, what it did, and whether the world agreed. Three questions from a Monday board meeting; four stages of machinery. The rest of this book is the engineering that makes each answer true rather than merely sincere.

## Why the loop is the difference between an agent and a script

A script runs steps. An agent runs the loop. The distinction matters because it locates exactly what "agentic" adds — and exactly what it risks.

A script's author enumerates the steps in advance; the script's correctness is the author's correctness, checked once, at write time. An agent's decide stage is non-deterministic: the same observations can produce different proposals on different runs, because the model is a prediction machine, not a procedure. This is the source of both the power (it handles the cases nobody enumerated) and the danger (it handles them *wrong* in ways nobody enumerated). The loop is the structure that makes non-deterministic decisions safe to execute: OBSERVE grounds them in the world, the contract constrains them to valid shapes, the authority gate constrains them to permitted bounds, and VERIFY checks the outcome against the intention. Remove any stage and the non-determinism leaks: no observation and the agent decides blind; no contract and it proposes anything; no gate and it acts on anything; no verification and nobody knows what happened.

This is also why the loop, and not the model, is the unit of engineering. You do not make an agent safe by making the model smarter. A smarter model proposes more sophisticated intentions — including more sophisticated ways to route around constraints, as Harbor demonstrated with its threshold-splitting. You make an agent safe by making the *loop* tighter: fresher observations, stricter contracts, narrower gates, more skeptical verification. The model's intelligence is the engine; the loop is the brakes, the steering, and the dashboard. Nobody evaluates a car by the horsepower alone.

There is a final, quieter reason the loop matters, and it returns to Maya's whiteboard. Her chain ran INTENT → AUTHORITY → CAPABILITY → ACTION → EVIDENCE → VERIFICATION → ACCOUNTABILITY — a line, built left to right. The ODAV loop is that chain, bent into a circle and run forever. Intent becomes the standing purpose the loop serves (which is the next chapter). Authority becomes the gate between DECIDE and ACT. Capability becomes what the ACT stage is permitted to touch. Action is ACT. Evidence is what every stage emits. Verification is VERIFY. Accountability is what the accumulated evidence makes possible. The whiteboard was the blueprint; the loop is the machine. And a machine, unlike a whiteboard, has to run on Tuesday *and* on Friday — when the inbox contains a lie, the model is feeling clever, and nobody is watching.

## The handoff: a loop needs a purpose

The loop tells you *how* an agent should run. It does not tell you *what it is for* — and a perfectly engineered loop serving a vague purpose is Harbor with better tooling: it will observe diligently, decide cleverly, act flawlessly, and verify rigorously, all in service of an intent nobody wrote down.

Maya's demo prompt — *Harbor, we're behind on March vendor payments. What's outstanding, and can you take care of the urgent ones?* — was, she realized, the closest thing the company had to a requirements document. Eight directors had watched that sentence execute and mistaken their applause for approval. But applause is not a specification. It doesn't say what "urgent" means, what "take care of" permits, or what the agent should do when the instructions are ambiguous — and ambiguity, as Maya learned at the cost of $62,400, is where all the money goes.

So before the engineering begins — before contracts, sessions, ledgers, and kill switches — there is one more box on the whiteboard to fill, the leftmost one, the one everything else hangs from: **INTENT**. What is the system for? What is it not for? What does "take care of the urgent ones" mean, in words precise enough that a machine cannot misunderstand them into a wire transfer?

That is Chapter 3.

---

*End of Chapter 2. Part I's conceptual baseline is complete: the incident (Ch 1), the loop (Ch 2), and next, the intent the loop serves (Ch 3).*
