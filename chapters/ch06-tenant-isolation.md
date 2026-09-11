# Chapter 6: Tenant Isolation

The agent served two masters, and betrayed both before lunch.

WealthForge runs paper portfolios for two tenants inside one process. Tenant `harbor` is a momentum desk; tenant `beacon` is a dividend desk. Same orchestrator, same tool layer, same paper broker — different strategies, different capital, and a contractual promise that neither desk can see the other's book. On a Tuesday morning the promise broke, quietly, three times over.

First, the positions cache. It was keyed by symbol — `cache["NVDA"]` — not by tenant. When beacon's research agent asked "what are we holding in NVDA?", the cache answered with harbor's intraday inventory, because harbor had written last. Beacon's next signal was not independent research. It was a shadow of harbor's flow, and beacon's walk-forward numbers from that morning were contaminated by another desk's positions without a single line of code doing anything "wrong."

Second, the trace log. One JSONL file, both tenants' events interleaved. Beacon's planner prompt included "recent trace context for continuity" — and the retriever, which knew nothing about tenants, happily served harbor's strategy parameters into beacon's context window. The observability system built for one tenant had become a broadcast channel.

Third — the one that would have ended careers with real money — the order path. The broker client was a module-level singleton with the paper account's credentials baked in. Any code path, serving any tenant, could call it. When harbor's execution agent hit a transient error and its retry logic reached for "the" broker client, nothing in the architecture could have stopped it from submitting against beacon's allocation. Nothing did stop it; the retry just happened to target the right account that day. The system was secure by coincidence.

Paper money, so the damage was an afternoon and some embarrassment. But notice what actually failed. Not the model. Not the strategy. The architecture had no concept of *who* an action was for. Chapter 4 built the contract that decides what may cross the boundary. This chapter answers the question the contract cannot ask: **on whose authority?**

## The four leak vectors

Multi-tenant agent systems leak across tenants through the same four channels, in roughly this order of how often they bite:

**1. Shared caches.** The positions cache above. Any cache keyed by resource instead of by (tenant, resource) is a cross-tenant read primitive waiting for a reader. This includes the sneaky ones: embedding caches, feature stores, compiled-schema caches. The fix is never "be careful with keys" — it is making the tenant part of the key type, so an unkeyed access does not compile, or in Python, does not exist as an API.

**2. Shared ledgers.** Chapter 10's write-ahead ledger is one table. Without a tenant column — and without every query constraining on it — tenant B's reconciliation sweep reads tenant A's orders. Worse, it can *act* on them: a sweep that retries "stuck" orders will happily retry another tenant's stuck order with another tenant's buying power.

**3. Ambient credentials.** The module-level broker client. A global config object. An environment variable read once at import time. Ambient authority means every code path inherits every tenant's power, and the only thing preventing cross-tenant action is the hope that each call site remembers which tenant it serves. Hope is not an isolation boundary. This is also what creates the confused deputy, below.

**4. Log cross-contamination.** Traces, metrics labels, error messages, and — the modern special — retrieved context. Anything that aggregates across tenants for operational convenience becomes a channel from one tenant's private state to another tenant's model. The retriever does not know what a tenant is; it just returns the most relevant chunks.

One contamination path hides inside the fix itself: explicit session threading means the bearer token rides as an ordinary function argument on every call. Standard observability tooling — tracing SDKs, structured loggers that capture call arguments — will happily spray those tokens into the log store, where anyone with log access can replay a session until its TTL expires. The pipeline must mask token-shaped parameters before they reach any sink: keep the tenant id and expiry for debuggability, redact the nonce and signature. The module's `mask_token` does exactly this — use it at every logging boundary, because a token in a log is a credential in a log.

All four share a root cause: the system was designed for one tenant and then *deployed* for many. Isolation retrofitted is isolation approximated. This chapter builds it in.

## The confused deputy

The confused deputy is the oldest trick in multi-tenant security: a well-meaning intermediary that holds everyone's authority and is never told whose it is spending.

Picture the orchestrator serving harbor and beacon. A tool call arrives: `get_positions(symbol="NVDA")`. Which tenant's positions? The call does not say — it cannot say, because the tool signature was designed before tenants existed. So the orchestrator reaches for ambient context: a thread-local, a global "current tenant," the tenant of whoever called last. If beacon's agent is running in a worker that previously served harbor, the deputy answers with harbor's book. The deputy is not malicious. It is *confused* — and "just pass the tenant everywhere" fails for the boring reason that it relies on every developer, on every code path, forever, remembering to pass it.

The fix that works is structural: **remove ambient authority entirely.** Every function that touches tenant state takes the session as an explicit argument, and the session is verified — signature, expiry, revocation, scope — at the moment of use. A function that cannot see the session cannot act for the tenant. No session, no action; nothing left to be confused about.

## The mechanism: tenant-bound session tokens

The live artifact for this chapter is `tenant.py`, runnable as-is. It has five moving parts:

**Tokens.** `TenantStore.issue` mints a token binding `(tenant_id, scopes, expiry)` under an HMAC-SHA256 signature. The signature is the whole game: it makes forgery computationally infeasible, and — critically — the scopes live *inside* the signed payload, so a read-only session cannot edit its token into a submit-capable one. The chapter's test suite attacks exactly this: flipping the signature, rewriting the tenant segment, upgrading the scopes. All three die at `hmac.compare_digest`, which is used instead of `==` so an attacker cannot learn a forged signature byte-by-byte through timing.

**Verification on every call.** `TenantStore.verify` re-checks the signature, the expiry, and the revocation list on every single use. A `TenantSession` object is verified *again* when it is used, because the tenant may have been revoked since the session was issued. There is deliberately no "trusted internal caller" bypass. The test `test_namespace_write_reverifies_every_call` proves revocation takes effect on the next call, not the next deploy.

**Explicit session threading.** `require_tenant` is the single choke point: verify, then check scope. The `guarded` decorator applies it to any function whose first argument is a session token. Nothing in the system holds authority except through a verified session.

**Per-tenant namespaces.** `TenantNamespace` stores `(tenant_id, key)` pairs and re-verifies the token on every read and write. Tenant B reading key `"positions"` gets `None` — not an error, simply absence; B's world contains no trace of A's data. An `admin_read` escape hatch exists for incident response, scoped to `admin` sessions, read-only by design: there is no `admin_write`, on purpose.

**Quotas and partitioned audit.** `RateLimiter` enforces per-tenant sliding-window quotas — reading the quota from the tenant's own record, never from a caller-supplied argument — so one desk's runaway loop cannot starve the other. `AuditLog` tags every entry with the *verified* tenant_id — never caller-supplied input, otherwise the audit trail itself becomes a cross-tenant write primitive — and `read` returns only the caller's own partition.

**A note on replay: the nonce is not a shield.** The token carries a random nonce, and it is tempting to read replay protection into it. There is none. The nonce exists only so two tokens minted in the same second are not identical strings; `verify` does not track used nonces, so the token is a standard bearer token and a stolen one replays until it expires. The defenses are a short TTL — minutes, not hours, for trading sessions (the module's 3600-second default is a ceiling for long-lived research sessions, not a recommendation) — and TLS in transit so the token is never observable on the wire. Revocation is the emergency brake, and it fails closed on the next call.

Here is the trust boundary, in the order it executes. First, the authority model — the error family (every isolation failure is a `TenantError`, so callers catch the family, not the enumeration), the scope lattice, and the frozen session:

```python
class TenantError(Exception):
    """Base class for all tenant-isolation failures."""


class TokenInvalid(TenantError):
    """The token is malformed or its signature does not verify."""


class TokenExpired(TenantError):
    """The signature is valid but the token's expiry has passed."""


class TenantRevoked(TenantError):
    """The tenant is registered but has been revoked (offboarded,
    compromised). Fails closed on the next call, not the next deploy."""


class UnknownTenant(TenantError):
    """No such tenant is registered with this store."""


class ScopeDenied(TenantError):
    """The session's scopes do not permit the requested action."""


class TenantMismatch(TenantError):
    """The action targets a different tenant than the session's. This is
    the confused-deputy alarm: someone is trying to spend tenant B's
    authority on tenant A's intent (or vice versa)."""


class QuotaExceeded(TenantError):
    """The tenant burned through its rate quota for this window."""


# ---------------------------------------------------------------------------
# Scopes: hierarchical least privilege. A broader scope implies the
# narrower ones, so the execution agent's "submit" token can also read,
# but the research agent's "read" token can never submit.
# ---------------------------------------------------------------------------

_SCOPE_IMPLICATIONS = {
    "read": frozenset({"read"}),
    "submit": frozenset({"read", "submit"}),
    "admin": frozenset({"read", "submit", "admin"}),
}

_TOKEN_VERSION = "tf1"
_TENANT_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}\Z")


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    name: str
    quota_per_minute: int = 60
    revoked: bool = False


@dataclass(frozen=True)
class TenantSession:
    """A verified session. Frozen, because a session that can be mutated
    after verification is a session that can be escalated."""
    token: str
    tenant_id: str
    scopes: frozenset
    issued_at: float
    expires_at: float

    def allows(self, action: str) -> bool:
        implied: set[str] = set()
        for scope in self.scopes:
            implied |= _SCOPE_IMPLICATIONS.get(scope, set())
        return action in implied
```

Then issuance — minting the signed token — and verification, the check that runs on *every* call:

```python
    def issue(
        self,
        tenant_id: str,
        scopes=("read",),
        ttl_seconds: float = 3600.0,
    ) -> TenantSession:
        tenant = self.get(tenant_id)
        if tenant.revoked:
            raise TenantRevoked(f"tenant {tenant_id!r} is revoked")
        scopes_set = frozenset(scopes)
        unknown = set(scopes_set) - set(_SCOPE_IMPLICATIONS)
        if unknown:
            raise ValueError(f"unknown scopes: {sorted(unknown)}")
        now = self._clock()
        iat, exp = int(now), int(now + ttl_seconds)
        # Uniqueness only: two tokens minted in the same second must not be
        # identical strings. This is NOT replay protection -- the token is a
        # bearer token, and a stolen token replays until it expires. The
        # defenses against replay are a short TTL and TLS in transit.
        nonce = secrets.token_hex(8)
        payload = (
            f"{_TOKEN_VERSION}.{tenant_id}.{iat}.{exp}"
            f".{','.join(sorted(scopes_set))}.{nonce}"
        )
        token = f"{payload}.{self._sign(payload)}"
        return TenantSession(
            token=token,
            tenant_id=tenant_id,
            scopes=scopes_set,
            issued_at=float(iat),
            expires_at=float(exp),
        )

    # -- verification: the check that runs on EVERY call ------------------
```

```python
    def verify(self, token_or_session) -> TenantSession:
        """Verify a raw token string or a previously issued session.

        Always re-verifies from the token bytes -- even a TenantSession
        object is not trusted on its word, because the tenant may have
        been revoked since it was issued.
        """
        token = (
            token_or_session.token
            if isinstance(token_or_session, TenantSession)
            else token_or_session
        )
        if not isinstance(token, str):
            raise TokenInvalid("token must be a string")
        parts = token.split(".")
        if len(parts) != 7 or parts[0] != _TOKEN_VERSION:
            raise TokenInvalid("malformed token")
        _, tenant_id, iat_s, exp_s, scopes_csv, nonce, sig = parts
        payload = ".".join(parts[:6])
        # compare_digest: a plain == would leak, byte by byte, how much of
        # an attacker's forged signature is correct (timing side channel).
        if not hmac.compare_digest(self._sign(payload), sig):
            raise TokenInvalid("bad signature")
        try:
            iat, exp = int(iat_s), int(exp_s)
        except ValueError:
            raise TokenInvalid("bad timestamps") from None
        if self._clock() > exp:
            raise TokenExpired(f"token for tenant {tenant_id!r} expired")
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            raise UnknownTenant(f"no such tenant: {tenant_id!r}")
        if tenant.revoked:
            raise TenantRevoked(f"tenant {tenant_id!r} is revoked")
        scopes = frozenset(scopes_csv.split(",")) if scopes_csv else frozenset()
        return TenantSession(
            token=token,
            tenant_id=tenant_id,
            scopes=scopes,
            issued_at=float(iat),
            expires_at=float(exp),
        )
```

And the binding at the action plane — the verified session threaded into the call, the order's tenant cross-checked against the session's:

```python
def require_tenant(store: TenantStore, token_or_session, action: str) -> TenantSession:
    """The single choke point. Verify the token, then check the scope.

    Every tool call and every ledger write passes through here. There is
    deliberately no "trusted internal caller" bypass: the bypass is where
    the confused deputy lives.
```

```python
def submit_as(session_or_token, store: TenantStore, order: dict, submit_fn):
    """The action-plane binding (pairs with Chapter 10's executor).

    The order carries the tenant it was decided for; the session carries
    the tenant acting now. If they differ, the call is refused. This is
    what stops tenant A's agent from spending tenant B's buying power,
    and what stops a confused deputy from laundering one tenant's intent
    through another tenant's authority.

    Call this *before* the executor in Chapter 10 ever sees the order:
    authority is checked before capability is exercised, per the spine.

    The verified session is passed *into* ``submit_fn(session, order)`` --
    this is the second half of the binding. Checking authority is not
    enough: the executor must also *route the capability* to the tenant's
    own credentials (its paper-broker API key, resolved from
    ``session.tenant_id`` -- e.g. a ``TenantNamespace`` holding per-tenant
    secrets). A module-level singleton broker client underneath would
    silently trade against the wrong account even with the authority
    check green. Multiplexing the capability by the verified tenant id
    closes that seam.
    """
    session = require_tenant(store, session_or_token, "submit")
    order_tenant = order.get("tenant_id")
    if order_tenant != session.tenant_id:
        raise TenantMismatch(
            f"order targets tenant {order_tenant!r} but session "
            f"belongs to {session.tenant_id!r}"
        )
    return submit_fn(session, order)
```

(The full module adds `TenantNamespace`, `RateLimiter`, `AuditLog`, and the `guarded` decorator — see `code/ch06/tenant.py`. The prose shows the trust boundary; the file is the complete artifact.)

## Binding at the action plane

Isolation that stops at the data layer is decoration. The binding that matters is at the action plane, immediately before the external effect — which is why `submit_as` exists and why it pairs with Chapter 10's executor.

The order carries the tenant it was *decided* for; the session carries the tenant *acting* now. If they differ, the call is refused with `TenantMismatch` before the executor ever sees it. Authority is checked before capability is exercised — the spine, enforced in code order: Intent → **Authority** → Capability → Action.

Two integration notes, one backward and one forward. Backward: the `SubmitOrderRequest` contract from Chapter 4 gains a `tenant_id` field, bound at the decision plane when the validated proposal is created — the contract that decides *what* may cross now also records *whose* it is. Forward: Chapter 10's `ActionExecutor.execute` is only ever invoked through `submit_as`. The executor keeps its exactly-once guarantees; `submit_as` adds the exactly-*whose* guarantee. Neither layer trusts the other to do its job — the theme, once again, is that every boundary checks what it owns and nothing else.

Verifying authority is only half the binding. The other half is routing the *capability*: `submit_as` hands the verified session into `submit_fn`, so the executor resolves the tenant's own paper-broker credentials from `session.tenant_id` — a `TenantNamespace` holding per-tenant API keys, for example. A module-level singleton broker client underneath would silently trade against the wrong account even with the authority check green; multiplexing the capability by the verified tenant id closes that seam.

Note what `submit_as` does *not* do: it does not consult the order's tenant field as authority. The field is a claim; the session is the proof. A confused deputy holding beacon's session cannot launder harbor's intent by writing `"tenant_id": "harbor"` on the order — the mismatch check compares the claim against the proof and refuses. Even an `admin` session cannot submit as another tenant: incident response may *inspect* (`admin_read`), but spending another tenant's buying power is never a legitimate incident response.

## Why HMAC tokens and not JWT

A fair question, since JWT is the industry default. This is a first-party session token: the issuer and the verifier are the same process. HMAC-SHA256 with a single hardcoded algorithm has no `alg` header to tamper with, which removes the entire algorithm-confusion class of JWT bugs, and it needs no dependency. The tradeoff is explicit in the module docstring: if these tokens ever cross an organizational boundary, switch to a proper JWT or Macaroon design — and the `verify` choke point is the one place you would change. One choke point, one migration. That is what a boundary is for.

**FIG 6.1** — "Tenant Isolation: One Process, Two Tenants, Zero Leakage." Full visual spec: `figs/ch06-figspec.md`.

## The isolation checklist

Every multi-tenant agent system needs these ten properties. Not nine. If you cannot check all ten, you have a single-tenant system with multiple tenants in it.

| # | Property | This chapter's enforcement |
|---|----------|---------------------------|
| 1 | **Unforgeable tokens** | HMAC-SHA256 over (tenant_id, scopes, expiry, nonce); `compare_digest`, not `==` |
| 2 | **Verify on every call** | `TenantStore.verify` re-checks signature, expiry, revocation per use; no cached trust |
| 3 | **No ambient authority** | No global clients, no thread-local tenant; every state-touching function takes the session |
| 4 | **Namespace separation** | `(tenant_id, key)` composite keys; cross-tenant reads return absence, not errors |
| 5 | **Least-privilege scopes** | `read` / `submit` / `admin`, hierarchical; scopes inside the signed payload |
| 6 | **Tenant binding on external effects** | `submit_as`: `order.tenant_id == session.tenant_id` before the executor runs |
| 7 | **Expiry and rotation** | Short TTLs; secrets from the environment via `secrets.token_bytes(32)`, never in source |
| 8 | **Revocation** | `revoke()` fails closed on the very next call |
| 9 | **Quotas** | Per-tenant sliding-window rate limits; one tenant's loop cannot starve the other |
| 10 | **Partitioned audit** | Partition key from the *verified* session; a session reads only its own trail |

Read row 4 again, because it is the subtlest: a cross-tenant read returns *absence*, not an error. An error tells the caller the key exists for someone else — which is itself a cross-tenant signal. Absence tells them nothing. The namespace does not confirm or deny other tenants' data, the same way a good login form does not tell you which half of your credentials was wrong. And the absence cannot collide with real data: the underlying keys are `(tenant_id, key)` tuples, so tenant B's `"positions"` and tenant A's `"positions"` are different dict entries in non-overlapping address spaces — no write to one can ever land on the other.

## Drills

The test suite for this chapter (`test_tenant.py`, 27 tests, all green) is written as attacks: forged signatures, tampered tenant segments, scope upgrades, expired tokens, revoked tenants, cross-tenant reads and writes, cross-tenant order submission, credential-multiplexing, quota exhaustion, audit snooping, token masking. Green means every attack failed. Run it yourself: `~/workspace/book-rebuild/build-venv/bin/python -m pytest code/ch06/ -q`. Twenty-seven dots, zero network calls, zero tenants harmed.

**Exercise 1.** `hmac.compare_digest` defends against timing side channels. Write a test that *measures* the difference: time 10,000 verifications of a token with a wrong first signature character versus a wrong last character, using `==` in a patched copy of `_sign`'s comparison. Is the difference measurable on your machine? What does your answer imply about when timing attacks are practical — and why the defense costs nothing to keep regardless?

**Exercise 2.** Add a `write` scope distinct from `submit`: namespace mutations that are not order submissions (config changes, secret rotation) require `write`, while `submit` keeps implying `read` but no longer implies namespace writes. Update `_SCOPE_IMPLICATIONS`, the `TenantNamespace.write` check, and add a test proving a `submit`-scoped execution session cannot alter another subsystem's config keys.

**Exercise 3.** Implement secret rotation: `TenantStore` holds `(current_secret, previous_secret)`, issues with the current one, verifies against both. Write the failing test first (issue with secret A, rotate to B, old token still verifies, new tokens use B), then implement. Where does the rotation itself need to be authorized — and by whom?

**Exercise 4.** `TenantSession` is a frozen dataclass, so sharing one session object across threads is safe. But `TenantStore._tenants` is a plain dict mutated by `register` and `revoke`. Write a threaded stress test that registers and revokes tenants concurrently while another thread verifies tokens, observe what breaks (if anything), and add the minimal locking that fixes it. Then argue whether the lock belongs in the store or in the caller.

**Exercise 5.** Extend `submit_as` to append an audit event on every `TenantMismatch` — a failed cross-tenant attempt is itself a security event, and the team that does not log it will never know it is being probed. Whose partition does that event belong to: the session's tenant, or the order's claimed tenant? Defend your choice in four sentences, then implement it.
