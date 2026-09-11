"""Tenant isolation for the AlphaForge / WealthForge agent team.

One agent process serves many paper-trading tenants. Every tenant's data,
orders, and audit trail must be unreachable from every other tenant's
session -- not by convention, by construction.

The mechanism:

1. **Tenant-bound session tokens.** ``TenantStore.issue`` mints an
   HMAC-signed token binding (tenant_id, scopes, expiry). The signature
   makes forgery computationally infeasible; ``TenantStore.verify``
   re-checks the signature, expiry, and revocation on *every* use. There
   is no cached trust: a token verified a minute ago is verified again
   now, so revocation takes effect on the very next call.
2. **Explicit session threading.** There are no ambient credentials. Every
   tool call and ledger write takes the session (or raw token) as an
   argument and passes it through ``require_tenant`` first. A function
   that cannot see the session cannot act for the tenant -- this is what
   defeats the confused deputy.
3. **Per-tenant namespaces.** Ledgers, config, and secrets live in
   partitions keyed by (tenant_id, key). The namespace re-verifies the
   caller's token on every read and write, and a read for key K by tenant
   B can never observe tenant A's value for K.
4. **Least-privilege scopes.** A ``read`` token can inspect; only a
   ``submit`` token can place orders; ``admin`` may inspect other
   tenants' partitions for incident response but can never write to them.
   Scopes are inside the signed payload, so they cannot be upgraded by
   editing the token.
5. **Quotas and partitioned audit.** Per-tenant rate limits stop one
   tenant's runaway loop from starving the others; the audit log tags
   every entry with the *verified* tenant_id and a session can only read
   its own partition.

Why HMAC tokens and not JWT? This is a first-party session token: the
issuer and the verifier are the same process. HMAC-SHA256 with a single
hardcoded algorithm has no ``alg`` header to tamper with, which removes
an entire class of JWT bugs (algorithm confusion), and it needs no
dependency. If these tokens ever cross an organizational boundary, switch
to a proper JWT or Macaroon design -- the ``verify`` choke point is the
one place you would change.

Stdlib only: hmac, hashlib, secrets, time, re, functools, dataclasses.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Errors: every isolation failure raises a TenantError subclass, so callers
# can catch the family without enumerating every way isolation can break.
# ---------------------------------------------------------------------------

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


class TenantStore:
    """Issues and verifies tenant-bound session tokens.

    ``secret`` must be at least 16 bytes; generate it with
    ``secrets.token_bytes(32)`` and load it from the environment, never
    from source. ``clock`` is injectable so tests can drive expiry without
    sleeping.
    """

    def __init__(self, secret: bytes, clock=time.time):
        if len(secret) < 16:
            raise ValueError(
                "secret must be at least 16 bytes; "
                "generate with secrets.token_bytes(32)"
            )
        self._secret = secret
        self._clock = clock
        self._tenants: dict[str, Tenant] = {}

    # -- registration ---------------------------------------------------

    def register(
        self, tenant_id: str, name: str, quota_per_minute: int = 60
    ) -> Tenant:
        if not _TENANT_ID_RE.match(tenant_id):
            raise ValueError(
                f"tenant_id {tenant_id!r} must match [a-z0-9][a-z0-9_-]{{0,62}}"
            )
        tenant = Tenant(
            tenant_id=tenant_id, name=name, quota_per_minute=quota_per_minute
        )
        self._tenants[tenant_id] = tenant
        return tenant

    def get(self, tenant_id: str) -> Tenant:
        tenant = self._tenants.get(tenant_id)
        if tenant is None:
            raise UnknownTenant(f"no such tenant: {tenant_id!r}")
        return tenant

    def revoke(self, tenant_id: str) -> None:
        tenant = self.get(tenant_id)
        self._tenants[tenant_id] = Tenant(
            tenant_id=tenant.tenant_id,
            name=tenant.name,
            quota_per_minute=tenant.quota_per_minute,
            revoked=True,
        )

    # -- issuance ---------------------------------------------------------

    def _sign(self, payload: str) -> str:
        return hmac.new(
            self._secret, payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()

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


def require_tenant(store: TenantStore, token_or_session, action: str) -> TenantSession:
    """The single choke point. Verify the token, then check the scope.

    Every tool call and every ledger write passes through here. There is
    deliberately no "trusted internal caller" bypass: the bypass is where
    the confused deputy lives.
    """
    session = store.verify(token_or_session)
    if not session.allows(action):
        raise ScopeDenied(
            f"tenant {session.tenant_id!r} with scopes "
            f"{sorted(session.scopes)} may not perform {action!r}"
        )
    return session


def guarded(store: TenantStore, action: str):
    """Decorator form of ``require_tenant``: the wrapped function's first
    argument must be a session token (or verified session) authorized for
    ``action``. The verified session is what the function receives."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(session_or_token, *args, **kwargs):
            session = require_tenant(store, session_or_token, action)
            return fn(session, *args, **kwargs)
        return wrapper
    return decorator


class TenantNamespace:
    """Per-tenant key/value partition for ledgers, config, and secrets.

    Keys are stored as (tenant_id, key) pairs, and every read and write
    re-verifies the caller's token against the store. There is no fast
    path that skips the check, because the fast path is where leaks are
    born. (Production note: if per-call HMAC becomes measurable, cache
    *verified sessions* briefly -- never cache the decision to skip
    verification.)
    """

    def __init__(self, store: TenantStore):
        self._store = store
        self._data: dict[tuple[str, str], object] = {}

    def write(self, session_or_token, key: str, value: object) -> None:
        # Mutation is a write-class action: only a "submit"-scoped session
        # may change shared state. A read-only research session can look
        # but never alter the ledger it reads.
        session = require_tenant(self._store, session_or_token, "submit")
        self._data[(session.tenant_id, key)] = value

    def read(self, session_or_token, key: str):
        session = require_tenant(self._store, session_or_token, "read")
        return self._data.get((session.tenant_id, key))

    def keys(self, session_or_token) -> list[str]:
        session = require_tenant(self._store, session_or_token, "read")
        return sorted(k for (t, k) in self._data if t == session.tenant_id)

    def admin_read(self, session_or_token, tenant_id: str, key: str):
        """The scoped escape hatch: an admin session may inspect another
        tenant's partition during incident response. It may never write
        to it -- there is no admin_write, on purpose."""
        require_tenant(self._store, session_or_token, "admin")
        return self._data.get((tenant_id, key))


class RateLimiter:
    """Per-tenant sliding-window quota. One tenant's runaway loop must not
    starve the others sharing the process.

    The quota comes from the tenant's own record (``quota_per_minute``),
    never from a caller-supplied argument: a caller that chooses its own
    limit is a caller that can choose infinity.
    """

    def __init__(self, store: TenantStore, clock=time.time):
        self._store = store
        self._clock = clock
        self._hits: dict[str, list[float]] = {}

    def check(self, session: TenantSession, window_seconds: float = 60.0) -> None:
        limit = self._store.get(session.tenant_id).quota_per_minute
        now = self._clock()
        hits = [
            t for t in self._hits.get(session.tenant_id, [])
            if now - t < window_seconds
        ]
        if len(hits) >= limit:
            raise QuotaExceeded(
                f"tenant {session.tenant_id!r}: {limit} actions per "
                f"{window_seconds:g}s exceeded"
            )
        hits.append(now)
        self._hits[session.tenant_id] = hits


class AuditLog:
    """Append-only, partitioned by tenant. The partition key comes from the
    *verified* session, never from caller-supplied input -- otherwise the
    audit trail itself becomes a cross-tenant write primitive."""

    def __init__(self, clock=time.time):
        self._clock = clock
        self._entries: list[dict] = []

    def append(self, session: TenantSession, event: str, detail: str = "") -> None:
        self._entries.append(
            {
                "ts": self._clock(),
                "tenant_id": session.tenant_id,
                "event": event,
                "detail": detail,
            }
        )

    def read(self, session: TenantSession) -> list[dict]:
        return [e for e in self._entries if e["tenant_id"] == session.tenant_id]


def mask_token(token: str) -> str:
    """Render a token safe for logs.

    Explicit session threading means the bearer token rides as an ordinary
    function argument on every call. A tracing SDK or structured logger
    that captures call arguments would spray those tokens into the log
    store -- and a token in a log is a credential in a log, replayable
    until its TTL expires. Mask token-shaped parameters before they reach
    any observability sink: keep the version, tenant, and expiry (useful
    for debugging), redact the nonce and signature.
    """
    parts = token.split(".")
    if len(parts) != 7:
        return "<malformed-token>"
    ver, tenant_id, iat, exp, _scopes, _nonce, _sig = parts
    return f"{ver}.{tenant_id}.{iat}.{exp}.<redacted>"


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
