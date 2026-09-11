# Chapter 13 — Sandboxes, SSRF, and the Agent That Writes Code

## 13.0 Two boundaries, one chapter

AlphaForge's research agent has two jobs. The first is to fetch market
data — quotes, fundamentals, filings — from the outside world. The
second is to improve the strategy: read the current signal code, propose
a variant, backtest it, and report the result. One job touches the
network. The other touches the filesystem and the process table.

Chapter 12 filtered the model's *words*. It decided what the agent may
*say* and what proposals may pass. This chapter governs what those words
can *touch*. The research agent's perfectly well-formed, injection-free
proposal to "fetch the latest 10-K and backtest the variant" still needs
two answers: which network addresses may it reach, and what may it
execute and modify while backtesting? A system that answers the first
question with a policy document and the second with good intentions has
answered neither.

This chapter builds both answers as code: a **network boundary** that
every outbound HTTP request passes through, and a **sandbox** that
confines what the agent may run and what it may change. They are
different mechanisms for the same reason the two jobs are different
effects — and the chapter's running lesson is that boundaries belong at
the *effect*, never at the intention.

> **Figure 13.1** — SSRF attack paths against an agent's market-data tool, and the sandbox cell around the code-writing research agent. Full spec: `figs/ch13-figspec.md`.

## 13.1 The principle: the boundary is at the effect

An agent's authority should be evaluated the way a firewall evaluates
packets: at the point of the effect, by a mechanism the agent does not
control. Three corollaries follow, and the rest of the chapter is their
consequences.

**First, the agent must not be able to edit its own cell.** A sandbox
whose configuration lives in the agent's writable memory is a
suggestion. In this chapter's code, the `NetworkBoundary` is constructed
once — allowlist, resolver, transport, ceilings — and the agent under
test never receives a reference to it. The agent calls tools; the tools
call the boundary. The boundary answers to the operator.

**Second, deny by default.** Every check in this chapter fails closed.
An allowlist with a permissive fallback is a blocklist with extra steps,
and blocklists lose to novelty: the attack you did not enumerate walks
through. The network boundary refuses hosts it does not recognize; the
sandbox refuses commands it was not told about and patches it has not
seen reviewed.

**Third, name every refusal.** Each failure mode gets its own exception
type, because the trace must say *why* the system stopped, not merely
that it did. Chapter 9's evidence spine consumes these names; Chapter
14's on-call script reads them at 3 a.m. A bare `PermissionError` is a
mystery. `SSRFAddressBlocked("api.polygon.io resolved to 10.0.0.5
(private)")` is a diagnosis.

These three sit inside the book's defense in depth, and it is worth
naming the layers so this chapter never gets mistaken for the whole
wall: the **tool contract** (Chapter 4) decides what may be *asked*; the
**content defenses** (Chapter 12) decide what the model may *propose*;
**this chapter** decides what the proposal may *touch*; the **kill
switch** (Chapter 11) decides what happens when everything above was
wrong. An attacker must beat all four. A defender may win at any one.

## 13.2 SSRF: the confused deputy at the network layer

Server-side request forgery is the network layer's confused-deputy
problem: the agent is tricked into making a request *it* is authorized
to make, to a destination *the attacker* chose, and the response flows
back to the attacker through the agent's legitimate access. The classic
target is the cloud metadata endpoint — `169.254.169.254` on AWS, GCP,
and Azure — a link-local address that answers only from inside the
machine and hands out the credentials that provisioned it. It is the
cloud's master-key drawer, and it opens for any HTTP client running on
the host.

Agents are SSRF *amplifiers*, for a reason that connects directly to
Chapter 12. A traditional web app's SSRF surface is the set of URLs its
developers wrote into it. An agent's URL surface is the set of URLs that
arrive in its *data*: a filing that links a "correction" PDF, a feed
that 302-redirects through an analytics domain, a tool description that
points at a "faster mirror." The model does not need to be malicious or
even compromised in the instruction sense — it needs only to be helpful
about a URL that came from the data plane. Chapter 12 taught the agent
to distrust instructions in data. This chapter teaches the network to
distrust destinations in data.

Four mechanisms carry the attack, and the boundary must defeat all four:

**Direct fetch.** The agent requests `http://169.254.169.254/latest/`
outright — because a document told it to, or because its training data
remembers that address as "the way to get credentials." The defense is
the resolved-address check: the IP is link-local, and link-local is
refused.

**DNS rebinding.** The hostname is innocent and even allowlisted —
`quotes.vendor.example` — but between the agent's planning and the
request, or between two resolutions seconds apart, the DNS record flips
from a public IP to `10.0.0.5`. The name was checked; the address was
not. The defense is to check the *address*, every time: resolve, then
test every returned IP against the blocked ranges. A hostname that
resolves to one public and one private address is refused — mixed
resolution is itself the attacker's footprint.

**Redirect laundering.** The first hop is allowlisted and clean:
`https://api.polygon.io/quote` returns `302 Found` with
`Location: http://169.254.169.254/`. Any HTTP client with auto-redirect
enabled follows it without asking, and the allowlist never sees the
second hop. The defense is to follow redirects *manually* — disable the
client's auto-redirect, read the `Location` header, and re-run the full
gate on every hop. A chain is only as trustworthy as its least
trustworthy hop.

**Resolve-then-fetch TOCTOU.** Even resolve-then-check has a window: DNS
can change between the check and the TCP connect. This one the code
does not pretend to close — it *names* it, returns the checked addresses
in the verdict, and the chapter tells you to pin the connection to them
(Section 13.4). A boundary that hides its residuals is a boundary you
cannot reason about.

The market-data version of this story is concrete. AlphaForge's quote
tool must reach `api.polygon.io` and `api.alphavantage.co`. It must
never reach the metadata endpoint, never follow a feed's redirect to an
attacker's collector, and never resolve a vendor hostname into the
VPC. The allowlist names two suffixes. Everything else the tool learns
about the network, it learns through the gate.

## 13.3 The network boundary, in code

`network_boundary.py` implements the gate. The transport seam is the
first design decision worth noticing: the boundary never opens a socket
itself. It drives an injected `transport` callable —
`(method, url, timeout) -> TransportResponse` — which in production
wraps `urllib` or `requests` with auto-redirect *disabled*, and in tests
is a fake replaying canned chains. Testability is not a testing concern;
it is an architecture property. A boundary you cannot drive with a fake
is a boundary you cannot prove correct, and an unproven boundary is a
hope (Chapter 2).

The five checks run in order, and the exceptions name the refusal:

```python
class EgressError(Exception):
    """Base: the network boundary refused something on purpose."""


class SchemeDenied(EgressError):
    """The URL scheme is not http/https. Refused."""


class UserinfoDenied(EgressError):
    """The URL carries userinfo (user:pass@host). Refused."""


class HostNotAllowlisted(EgressError):
    """Deny by default: the host matches no allowlist entry. Refused."""


class SSRFAddressBlocked(EgressError):
    """A resolved IP falls in a blocked range (metadata/private/loopback).

    Raised even when the HOSTNAME is allowlisted — DNS rebinding means the
    name is not the address. The message names the offending IP and the
    category it matched, so the trace is auditable.
    """


class RedirectBlocked(EgressError):
    """A redirect hop failed the gate. The chain stops here."""


class TooManyRedirects(EgressError):
    """The redirect chain exceeded the hop limit. Refused."""
```

Two details in the allowlist deserve attention because both are
historical bug classes. Entries are exact hosts or `".suffix"`
wildcards, and the leading dot is load-bearing: `".polygon.io"` matches
`api.polygon.io` but not `polygon.io.evil.com`. Suffix matching without
the dot is the vulnerability that ate a generation of cookie-domain
checks. And userinfo — `https://user:pass@host/` — is refused outright,
not stripped: credentials in URLs leak into logs and error messages,
and the userinfo slot has been a smuggling position in every URL parser
ever written.

The resolve-then-check is the heart of the anti-rebinding defense:

```python
    def _check_resolved_ips(self, host: str) -> tuple[str, ...]:
        """Resolve the host and refuse any address in a blocked range.

        Every resolved IP is checked — a hostname that resolves to one
        public and one private address is still refused. The name is not
        the address; DNS rebinding is exactly this gap.

        IP literals skip DNS entirely and are checked directly: there is
        nothing to rebind, and asking a resolver about a literal would
        let a lying or confused resolver launder it.
        """
        try:
            ipaddress.ip_address(host)
            ips = [host]
        except ValueError:
            ips = self._resolver(host)
        if not ips:
            raise SSRFAddressBlocked(f"{host}: resolved to no addresses")
        for ip in ips:
            category = _address_category(ip)
            if category is not None:
                raise SSRFAddressBlocked(
                    f"{host} resolved to {ip} ({category}); "
                    "refusing: the address, not the name, is the trust unit"
                )
        return tuple(ips)
```

Note the IP-literal branch, which exists because the adversarial tests
caught its absence: the first draft sent literals through the resolver,
and the test fake — which maps unknown hosts to a public IP — laundered
`169.254.169.254` into legitimacy. The fix is also the more correct
production behavior: there is nothing to rebind in a literal, so DNS
gets no vote. When your tests are written as attacks, they find the
laundering paths before the attackers do.

Redirects are followed by hand, and every hop is re-gated:

```python
            nxt = urljoin(checked_url, location)
            try:
                self._gate_one_url(nxt)
            except EgressError as exc:
                raise RedirectBlocked(
                    f"redirect hop {len(hops)} -> {nxt!r} failed the gate: {exc}"
                ) from exc
            # 301/302/303 rewrite to GET per RFC 7231; 307/308 keep method.
            if resp.status_code in (301, 302, 303):
                method = "GET"
            current = nxt
        raise TooManyRedirects(
            f"exceeded {self._max_redirects} redirect hops from {url!r}"
        )
```

The pre-check before following the hop exists so the error names the
*redirect* as the failure, not the URL in isolation: `RedirectBlocked`
tells the trace that a trusted hop laundered an untrusted one, which is
a different incident — and a different response — than a direct fetch to
a bad host. Timeouts, finally, are capped rather than honored: the agent
may ask for less than the ceiling, never more. A tool that can set its
own 24-hour timeout is a tool that can hold a connection — and a thread,
and the operator's attention — hostage.

## 13.4 What the boundary cannot do

A boundary that hides its residuals is a boundary you cannot reason
about, so this section names them.

**The DNS TOCTOU is real.** Between `_check_resolved_ips` and the
transport's TCP connect, the record can change. The module's answer is
the `GateVerdict`: it carries `resolved_ips`, the exact addresses that
were checked, so a production deployment can *pin* the connection —
resolve once, connect to the checked IP (a custom connector, or
Happy-Eyeballs with the checked address first), or re-run the address
check at connect time inside the socket factory. What the module
guarantees: no request is ever *sent* to an unchecked address. What it
does not guarantee: that the address is the same when the SYN leaves.
For a market-data tool on a 60-second poll loop, pinning per request is
cheap. For a high-frequency fetcher, pin per DNS TTL. The residual is
yours to close at the deployment layer, with the verdict as the
instrument.

**The boundary sees URLs, not intent.** An allowlisted host can still
receive exfiltrated data: the agent that decides to POST the portfolio
to `api.polygon.io.evil.com` is stopped (not allowlisted), but the agent
that encodes secrets into query parameters to an *allowlisted* analytics
endpoint is not — the gate checks destinations, not payloads. The
allowlist is not a data-loss-prevention tool. Payload inspection is
Chapter 12's output review; the record of what left is Chapter 9's
evidence spine. This is why the book builds four layers (Section 13.1)
instead of one perfect gate: each layer is blind to a different thing,
and the blindnesses do not overlap.

**The boundary does not authenticate the far end.** It ensures you
reached an address you intended, not that the server behind it is who it
claims. TLS does that, and in production the transport should pin the
vendor's certificate or CA — a one-line `ssl` context the chapter
leaves to the deployment, because certificate management belongs to the
operator, not the agent.

## 13.5 Egress: the enforcement home

This section is where the egress-filter material from the first
blueprint lives — deliberately, because output review as *policy* ("the
agent must not exfiltrate") is Chapter 12's §12.5, and output review as
*enforcement* is here. The distinction matters: a policy the agent reads
is advice; a gate the agent's bytes pass through is a control. The agent
that decides to exfiltrate the book's positions to a pastebin does not
meet the policy document. It meets `HostNotAllowlisted`.

The quant version is the market-data tool's allowlist:
`(".polygon.io", ".alphavantage.co")` and nothing else. The tool fetches
bars, and its universe of reachable hosts is two suffixes wide. When the
research agent — being helpful — decides the backtest results would be
"easier to share" via a file-upload service, the upload dies at the
gate with a named refusal, the evidence spine records the attempt
(Chapter 9), and the kill switch never needs to wake up (Chapter 11).
The cheapest incident is the one the boundary prevented, because there
is no incident at all — only a refused request and a trace entry.

## 13.6 The sandbox: the agent that writes code

The research agent's second job is the harder one: it edits strategy
code and runs it. This is the coding-agent problem (blueprint-v2 §2),
and it concentrates every escape class in one place — because an agent
that writes code and executes it is, from the operating system's point
of view, a user with a shell and an editor. The sandbox answers by
being a *cell*: a process cell and a file cell, with separate keys.

**The process cell** confines execution. Its rules:

- **argv only, never `shell=True`.** Command injection as a class dies
  here, not in a denylist. `["echo", "; rm -rf /"]` passes the semicolon
  as a *literal argument* to echo, because no shell ever sees the
  string. There is no escaping to get wrong when there is no
  interpreter to escape from. (The test asserts the `; touch` payload
  appears verbatim in echo's output and that the file was never
  created.)
- **Command allowlist.** The agent names a key (`"python3"`); the
  sandbox maps it to an absolute executable resolved *at construction*.
  Absolute paths the agent invents are refused. The map is small on
  purpose: `python3` for the backtester, maybe `git` for worktree
  hygiene. `curl` is not on it — the sandbox has no business fetching,
  and the network boundary would refuse it anyway. Defense in depth is
  not redundancy; it is disagreement about what "allowed" means.
- **Resource limits.** A wall-clock timeout kills the runaway
  (the `time.sleep(30)` test with a one-second budget), and a byte cap
  truncates runaway output *with a flag* (`truncated=True`), never
  silently. An agent that can burn unbounded CPU or fill the disk with
  logs holds a different kind of authority than its tool contract
  describes — resource exhaustion is an escape, not a bug.
- **Scrubbed environment.** The child gets a fixed minimal env
  (`PATH`, `LANG`) — never the parent's. An agent that can read
  `os.environ` in a subprocess can read your API keys; this one finds
  the variable absent. The test sets a canary secret in the parent and
  asserts the child cannot see it.

**The file cell** confines modification, and it is a *different
permission* — `can_apply_patch` is not `can_run_bash`. Running commands
is not the same authority as modifying files: the backtesting agent
needs both, the data-fetching agent needs neither, and the agent that
reviews strategy variants might hold the patch permission while being
denied execution entirely (propose the change; the CI runner — a
different principal — executes it). Least privilege is not one knob; it
is a knob per effect.

Patches move through **propose, review, then apply** — Chapter 2's
Decide-before-Act, in a diff. `propose_patch` parses the unified diff
(parsing is not approval); `review` runs a policy — human or automated —
over the summary *and the added text*; `apply` refuses anything
unreviewed or rejected. The parser accepts a strict unified-diff subset
and matches context *exactly*: a hunk whose context lines do not match
the file byte-for-byte is refused, never fuzzed. Fuzzy matching is the
patch equivalent of "the model probably meant" — and Chapter 5 already
taught us what "probably" costs.

Confinement is checked three ways because there are three escape
classes: absolute paths (`/etc/cron.d/evil`), `..` traversal
(`../../evil.py`), and **symlink components** — the subtle one. A patch
targeting `sneaky/evil.py` looks in-tree until you notice `sneaky` is a
symlink to a directory outside the worktree. The sandbox walks each path
component with `islink` *at apply time* (the race is checked when it
matters, and re-checked: proposal-time confinement is for the
reviewer's benefit, apply-time confinement is for the filesystem's).
The test builds the symlink, proposes the patch, and asserts the refusal
names the symlink — and that the outside file was never created.

## 13.7 The sandbox, in code

The permission model is two flags, defaulting to nothing — the
constructor grants no authority the caller did not name:

```python
@dataclass(frozen=True)
class SandboxPermissions:
    """What this sandbox instance may do. Grant narrowly."""

    can_run_bash: bool = False
    can_apply_patch: bool = False


_CHILD_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
```

`run_bash` is the process cell. Read it as the embodiment of Section
13.6 — every rule in the prose is a line in the method:

```python
    def run_bash(
        self,
        argv: list[str],
        timeout: float | None = None,
    ) -> BashResult:
        """Run a command. argv only — there is no shell to inject into.

        ``argv[0]`` must be a key in the allowlist map. The semicolon in
        ``["echo", "; rm -rf /"]`` is a literal argument to echo, because
        no shell ever sees it. Resource limits: wall-clock timeout kills
        the runaway; output past the cap truncates with ``truncated=True``.
        """
        if not self._permissions.can_run_bash:
            raise SandboxPermissionDenied("run_bash: permission not granted")
        if not argv:
            raise CommandNotAllowlisted("empty argv")
        name = argv[0]
        if name not in self._commands:
            raise CommandNotAllowlisted(
                f"{name!r} is not an allowlisted command"
            )
        budget = self._default_timeout if timeout is None else timeout
        proc = subprocess.Popen(
            [self._commands[name], *argv[1:]],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=self._worktree,
            env=dict(_CHILD_ENV),
        )
        killed = {"timeout": False}

        def _kill_on_timeout() -> None:
            killed["timeout"] = True
            proc.kill()

        timer = threading.Timer(budget, _kill_on_timeout)
        timer.start()
        out = bytearray()
        truncated = False
        try:
            assert proc.stdout is not None
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                out.extend(chunk)
                if len(out) > self._output_cap:
                    truncated = True
                    proc.kill()
                    break
            proc.wait()
        finally:
            timer.cancel()
        if killed["timeout"] and not truncated:
            raise SandboxTimeout(
                f"{name!r} exceeded {budget}s and was killed"
            )
        return BashResult(
            returncode=proc.returncode,
            output=bytes(out[: self._output_cap]),
            truncated=truncated,
            timed_out=killed["timeout"],
        )
```

Two implementation notes for the careful reader. First, `stderr` is
merged into `stdout`: the sandbox reports one ordered byte stream rather
than two, because interleaving is the truth about what the command did
and separate streams are a reconstruction problem. Second, the output
loop reads in 64 KiB chunks with the timer as the enforcer — `communicate()`
would buffer unboundedly before we could truncate, which would make the
cap a post-mortem rather than a control.

`_confine` is the file cell's gate — symlink check first so the error
names the escape class, realpath containment as the backstop:

```python
    def _confine(self, relpath: str) -> str:
        """Resolve a patch target inside the worktree, or refuse.

        Three escape classes, three checks: absolute paths, ``..``
        traversal, and symlink components (the symlink race — checked at
        apply time, when it matters).
        """
        if os.path.isabs(relpath):
            raise PatchOutsideWorktree(f"absolute path {relpath!r} refused")
        # Normalize a/ b/ prefixes from diff headers before joining.
        for prefix in ("a/", "b/"):
            if relpath.startswith(prefix):
                relpath = relpath[len(prefix):]
                break
        if relpath in ("", ".", "/dev/null"):
            raise PatchOutsideWorktree(f"empty target {relpath!r} refused")
        # Symlink race FIRST, so the error names the escape class: walk
        # each component of the relative path and refuse symlinks — a
        # symlinked directory would redirect the write outside the tree.
        probe = self._worktree
        for part in relpath.split(os.sep):
            if part in ("", ".", ".."):
                raise PatchOutsideWorktree(
                    f"suspicious component {part!r} in {relpath!r}"
                )
            probe = os.path.join(probe, part)
            if os.path.islink(probe):
                raise PatchOutsideWorktree(
                    f"symlink component {probe!r} refused"
                )
        # Backstop: resolve everything and require containment.
        candidate = os.path.realpath(os.path.join(self._worktree, relpath))
        if os.path.commonpath([candidate, self._worktree]) != self._worktree:
            raise PatchOutsideWorktree(
                f"{relpath!r} escapes the worktree"
            )
        return candidate
```

And `apply` — the Decide-before-Act, enforced rather than advised:

```python
    def apply(self, reviewed: "ReviewedPatch") -> list[str]:
        """Apply a REVIEWED patch. Unreviewed or rejected: refused."""
        if not self._permissions.can_apply_patch:
            raise SandboxPermissionDenied(
                "apply_patch: permission not granted"
            )
        if not reviewed.reviewed:
            raise UnreviewedPatch(
                "Decide before Act: no review verdict on this patch"
            )
        if not reviewed.verdict.approved:
            raise PatchRejected(
                f"reviewer said no: {reviewed.verdict.reason}"
            )
```

The reviewer itself is a callable — human-in-the-loop or automated
policy — and the module ships a strict-enough default,
`automated_policy()`, that refuses patches adding networking or
process-spawning imports and patches too large to have been read. The
chapter is explicit that this is a *policy*, not a proof: a human
reviewer who reads the diff is the stronger control, and for strategy
code that will trade real money, the human is not optional. The
automated policy exists so the small-hours research agent still has a
reviewer — a weak one, honestly labeled, better than none.

## 13.8 Computer-use: the canonical hard case

Everything in this chapter gets harder when the agent's "tool" is a
computer. A computer-use agent — one that clicks, types, and reads
screens — multiplies every failure mode above, because the GUI is all
of the attack surfaces at once: the browser's address bar is SSRF, the
terminal app is command injection, the downloads folder is a sandbox
escape, and the screen itself is untrusted input (Chapter 12's data
plane, rendered in pixels).

**Action-space design is the contract.** The authority unit must be a
semantic action on a stable element — `click(a11y_node_482)` — never raw
coordinates. Coordinates are the GUI's version of an unchecked URL:
`(842, 317)` resolves to whatever happens to be there *now*, which is
exactly the TOCTOU this chapter has been about. An accessibility node id
at least names an element; a coordinate names a hope. The chapter's rule:
the action space is designed like a tool contract (Chapter 4) — a closed
vocabulary of verbs over identified objects, validated before dispatch.

**Screenshot versus accessibility tree** is the observation counterpart.
Pixels are universal but unstructured — the agent must do its own
element detection, and every detection is a guess. The accessibility
tree is structured but spoofable — a malicious page can lie about its
own labels the way a malicious tool server lies about its descriptions
(Chapter 7's trusted-description discipline, applied to the DOM). The
honest architecture uses both: the tree for structure, the screenshot
for verification, and neither trusted alone.

**Stale-DOM recovery** is Chapter 2's Verify, at GUI speed. The element
the agent observed at t=0 — the "Submit order" button — is gone at t=2,
replaced by a dialog the agent never saw. The rule is *re-observe, don't
click blind*: before every consequential action, re-resolve the element
and confirm it is the same one (same role, same label, same container).
A click on a stale reference is an act without verification, and
Section 13.2 already showed what unverified acts buy you.

The quant coda: AlphaForge does not drive a brokerage GUI — its broker
is an API behind the Chapter 10 executor, precisely so none of this
applies. That is the design lesson in one sentence: the cheapest way to
survive computer-use risk is to not need computer use. Where a GUI is
unavoidable (a vendor portal with no API), the agent gets the sandbox
with `can_run_bash` denied, a network boundary whose allowlist names
the portal and nothing else, and a human in the review seat for every
state-changing action. The ladder from Chapter 2 — the least autonomous
system that reliably works — is not philosophy here. It is the
deployment plan.

## 13.9 What this chapter's code proves

Thirty-two tests, each an attack from this chapter's catalog:

- *Network boundary (14):* metadata IP direct and via redirect hop;
  DNS rebinding to private and loopback ranges; allowlist miss denied by
  default; the `polygon.io.evil.com` suffix attack; redirect to an evil
  host blocked at hop two; userinfo refused; `file://` refused;
  redirect loops exhausted; happy path returns the body with an
  auditable verdict; in-allowlist redirect chains followed; timeouts
  capped; nonstandard ports refused.
- *Sandbox (18):* shell metacharacters inert as literal argv; unlisted
  commands and invented absolute paths refused; the runaway killed by
  timeout; oversized output truncated with the flag set; the child
  environment scrubbed of a canary secret; `run_bash` without the
  permission refused; patches escaping via `..`, absolute paths, and
  symlink components refused (the outside file never created);
  unreviewed patches never apply; rejected patches leave the file
  untouched; context mismatches refused rather than fuzzed; new-file
  patches create the file; the automated policy refuses `socket`
  imports and oversize diffs.

The research agent now has its cell: it may fetch from two suffixes of
the internet and no more, run three commands with a leash, and modify
files only inside its worktree and only after review. Everything it
tried to do outside that — in the tests, at least — met a named
refusal.

The boundaries are built and gated. But a boundary is only as good as
the record of what pressed against it — which refusals fired, which
verdicts were issued, which patches were reviewed and by whom. Chapter
14 operates the evidence pipeline: it takes the spine Chapter 9 built
and runs it — the async trace writer, the SLOs, the on-call script for
the 3 a.m. page, and the durable-run machinery that lets a long-lived
agent survive the night.
