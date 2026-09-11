"""Isolation drills for Chapter 6: every test is an attack that must fail.

Each test plays the adversary: forge a token, tamper with scopes, cross
tenant boundaries, replay after revocation. Green means the attack failed.
"""

import pytest

from tenant import (
    AuditLog,
    QuotaExceeded,
    RateLimiter,
    ScopeDenied,
    TenantMismatch,
    TenantNamespace,
    TenantRevoked,
    TenantStore,
    TokenExpired,
    TokenInvalid,
    UnknownTenant,
    guarded,
    mask_token,
    require_tenant,
    submit_as,
)


class FakeClock:
    def __init__(self, start=1_000_000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(clock):
    s = TenantStore(secret=b"test-secret-32-bytes-long!!", clock=clock)
    s.register("harbor", "Harbor Momentum Desk")
    s.register("beacon", "Beacon Dividend Desk")
    return s


# -- issuance & verification -------------------------------------------------

def test_issue_verify_roundtrip(store):
    session = store.issue("harbor", scopes=("read", "submit"))
    verified = store.verify(session.token)
    assert verified.tenant_id == "harbor"
    assert verified.scopes == frozenset({"read", "submit"})
    assert verified.allows("read") and verified.allows("submit")
    assert not verified.allows("admin")


def test_forged_signature_rejected(store):
    token = store.issue("harbor").token
    forged = token[:-1] + ("0" if token[-1] != "0" else "1")
    with pytest.raises(TokenInvalid):
        store.verify(forged)


def test_tampered_tenant_id_rejected(store):
    # Attack: take harbor's token, rewrite the tenant segment to beacon,
    # keep the signature. Must fail: the signature covers the tenant id.
    token = store.issue("harbor", scopes=("read", "submit")).token
    parts = token.split(".")
    parts[1] = "beacon"
    with pytest.raises(TokenInvalid):
        store.verify(".".join(parts))


def test_tampered_scopes_rejected(store):
    # Attack: a read-only session edits its own token to claim "submit".
    # Privilege escalation must fail at the signature check.
    token = store.issue("harbor", scopes=("read",)).token
    parts = token.split(".")
    parts[4] = "submit"
    with pytest.raises(TokenInvalid):
        store.verify(".".join(parts))


def test_truncated_token_rejected(store):
    token = store.issue("harbor").token
    with pytest.raises(TokenInvalid):
        store.verify(token.rsplit(".", 1)[0])  # signature chopped off
    with pytest.raises(TokenInvalid):
        store.verify("not-a-token-at-all")


def test_expired_token_rejected(store, clock):
    session = store.issue("harbor", ttl_seconds=60.0)
    clock.advance(61.0)
    with pytest.raises(TokenExpired):
        store.verify(session.token)


def test_unknown_tenant_issue_rejected(store):
    with pytest.raises(UnknownTenant):
        store.issue("nosuchdesk")


def test_revoked_tenant_fails_closed(store):
    session = store.issue("harbor", scopes=("read", "submit"))
    store.revoke("harbor")
    # Previously valid token now fails: verification is per-call, and
    # revocation is checked on every call, not just at issuance.
    with pytest.raises(TenantRevoked):
        store.verify(session.token)
    with pytest.raises(TenantRevoked):
        store.issue("harbor")


# -- bearer semantics: the nonce buys uniqueness, not replay protection --------

def test_same_second_tokens_are_unique(store):
    # Two tokens minted in the same clock tick must not be identical
    # strings -- that is the nonce's entire job.
    a = store.issue("harbor")
    b = store.issue("harbor")
    assert a.token != b.token


def test_token_is_bearer_replayable_until_expiry(store):
    # Honest documentation in test form: nothing in verify() tracks used
    # tokens, so a stolen token replays until its TTL expires. The
    # defenses are a short TTL and TLS in transit -- not the nonce.
    session = store.issue("harbor")
    assert store.verify(session.token).tenant_id == "harbor"
    assert store.verify(session.token).tenant_id == "harbor"  # replay: valid


def test_mask_token_redacts_signature_and_nonce(store):
    token = store.issue("harbor").token
    masked = mask_token(token)
    sig = token.rsplit(".", 1)[1]
    assert sig not in masked
    assert token not in masked
    assert "harbor" in masked  # tenant stays: debuggable, not secret
    assert mask_token("garbage") == "<malformed-token>"


# -- scopes -------------------------------------------------------------------

def test_read_only_token_cannot_submit(store):
    session = store.issue("harbor", scopes=("read",))
    with pytest.raises(ScopeDenied):
        require_tenant(store, session.token, "submit")
    # ...including through the action-plane binding.
    with pytest.raises(ScopeDenied):
        submit_as(session.token, store, {"tenant_id": "harbor"}, lambda s, o: o)


def test_scope_implication_submit_implies_read(store):
    session = store.issue("harbor", scopes=("submit",))
    verified = require_tenant(store, session.token, "read")
    assert verified.tenant_id == "harbor"


def test_unknown_scope_rejected_at_issuance(store):
    with pytest.raises(ValueError):
        store.issue("harbor", scopes=("root",))


# -- namespaces ----------------------------------------------------------------

def test_cross_tenant_read_returns_nothing(store):
    ns = TenantNamespace(store)
    a = store.issue("harbor", scopes=("read", "submit"))
    b = store.issue("beacon", scopes=("read", "submit"))
    ns.write(a.token, "positions", {"NVDA": 100})
    assert ns.read(b.token, "positions") is None  # not an error: simply absent
    assert b and ns.keys(b.token) == []
    assert ns.read(a.token, "positions") == {"NVDA": 100}


def test_namespace_write_reverifies_every_call(store):
    ns = TenantNamespace(store)
    a = store.issue("harbor", scopes=("read", "submit"))
    ns.write(a.token, "k", "v")
    store.revoke("harbor")
    with pytest.raises(TenantRevoked):
        ns.write(a.token, "k2", "v2")  # no cached trust


def test_namespace_write_requires_submit_scope(store):
    ns = TenantNamespace(store)
    reader = store.issue("harbor", scopes=("read",))
    with pytest.raises(ScopeDenied):
        ns.write(reader.token, "positions", {})
    # ...but the read-only session can still read its own partition.
    assert ns.read(reader.token, "positions") is None


def test_admin_may_inspect_but_never_write(store):
    ns = TenantNamespace(store)
    a = store.issue("harbor", scopes=("read", "submit"))
    ops = store.issue("harbor", scopes=("admin",))
    ns.write(a.token, "positions", {"NVDA": 100})
    assert ns.admin_read(ops.token, "harbor", "positions") == {"NVDA": 100}
    non_admin = store.issue("beacon", scopes=("read", "submit"))
    with pytest.raises(ScopeDenied):
        ns.admin_read(non_admin.token, "harbor", "positions")


# -- action-plane binding -------------------------------------------------------

def test_cross_tenant_order_submission_blocked(store):
    a = store.issue("harbor", scopes=("read", "submit"))
    calls = []
    order_for_beacon = {"tenant_id": "beacon", "symbol": "NVDA", "qty": 10}
    with pytest.raises(TenantMismatch):
        submit_as(a.token, store, order_for_beacon,
                  lambda session, order: calls.append(order))
    assert calls == []  # the submit function was never reached


def test_matching_tenant_order_passes(store):
    a = store.issue("harbor", scopes=("read", "submit"))
    order = {"tenant_id": "harbor", "symbol": "NVDA", "qty": 10}
    assert submit_as(a.token, store, order,
                     lambda session, o: ("filled", session.tenant_id, o)) == (
        "filled",
        "harbor",
        order,
    )


def test_submit_routes_capability_to_tenant_credentials(store):
    # The authority check is only half the binding. The capability -- whose
    # broker credentials actually execute the order -- must follow the
    # *verified session*, not a module-level singleton client. A singleton
    # underneath would silently trade against the wrong account even with
    # the TenantMismatch check green.
    creds = {"harbor": "paper-key-harbor", "beacon": "paper-key-beacon"}
    calls = []

    def submit_fn(session, order):
        # The executor resolves the tenant's own credentials from the
        # verified session -- in production, a TenantNamespace of secrets.
        calls.append((session.tenant_id, creds[session.tenant_id], order["symbol"]))
        return "submitted"

    a = store.issue("harbor", scopes=("read", "submit"))
    b = store.issue("beacon", scopes=("read", "submit"))
    submit_as(a.token, store, {"tenant_id": "harbor", "symbol": "NVDA"}, submit_fn)
    submit_as(b.token, store, {"tenant_id": "beacon", "symbol": "AAPL"}, submit_fn)
    assert calls == [
        ("harbor", "paper-key-harbor", "NVDA"),
        ("beacon", "paper-key-beacon", "AAPL"),
    ]


def test_submit_as_reverifies_before_delegating(store):
    # No cached trust at the binding either: a session revoked after
    # issuance is refused before submit_fn is ever reached.
    a = store.issue("harbor", scopes=("read", "submit"))
    store.revoke("harbor")
    with pytest.raises(TenantRevoked):
        submit_as(a.token, store, {"tenant_id": "harbor"}, lambda s, o: "x")


def test_even_admin_cannot_spend_another_tenants_authority(store):
    # Binding is binding: incident-response inspection (admin_read) is
    # allowed, but no session may submit orders as another tenant.
    ops = store.issue("harbor", scopes=("admin",))
    with pytest.raises(TenantMismatch):
        submit_as(ops.token, store, {"tenant_id": "beacon"}, lambda s, o: o)


def test_guarded_decorator_enforces_scope(store):
    @guarded(store, "submit")
    def place(session, order):
        return (session.tenant_id, order)

    submitter = store.issue("harbor", scopes=("submit",))
    assert place(submitter.token, {"symbol": "NVDA"}) == ("harbor", {"symbol": "NVDA"})
    reader = store.issue("harbor", scopes=("read",))
    with pytest.raises(ScopeDenied):
        place(reader.token, {"symbol": "NVDA"})


# -- quotas ----------------------------------------------------------------------

def test_quota_exceeded_per_tenant(store, clock):
    store.register("sprinter", "Sprint Desk", quota_per_minute=2)
    limiter = RateLimiter(store, clock=clock)
    a = store.issue("harbor", scopes=("submit",))
    b = store.issue("beacon", scopes=("submit",))
    s = store.issue("sprinter", scopes=("submit",))
    # The limit comes from the tenant's own record, never from the caller:
    # sprinter's quota is 2, harbor's and beacon's is the default 60.
    limiter.check(s)
    limiter.check(s)
    with pytest.raises(QuotaExceeded):
        limiter.check(s)
    # Other tenants are unaffected: quotas are per-tenant, not global.
    limiter.check(a)
    limiter.check(b)
    # ...and sprinter recovers when the window slides past.
    clock.advance(61.0)
    limiter.check(s)


def test_quota_comes_from_tenant_record_not_caller(store, clock):
    # A caller that could choose its own limit could choose infinity.
    store.register("tight", "Tight Desk", quota_per_minute=1)
    limiter = RateLimiter(store, clock=clock)
    t = store.issue("tight", scopes=("submit",))
    limiter.check(t)
    with pytest.raises(QuotaExceeded):
        limiter.check(t)


# -- audit partitioning ------------------------------------------------------------

def test_audit_log_partitioned(store):
    log = AuditLog()
    a = store.issue("harbor", scopes=("read", "submit"))
    b = store.issue("beacon", scopes=("read",))
    log.append(a, "order.submitted", "NVDA x100")
    log.append(a, "order.filled", "NVDA x100 @ 187.20")
    log.append(b, "signal.evaluated", "momentum=0.62")
    harbor_trail = log.read(a)
    beacon_trail = log.read(b)
    assert [e["event"] for e in harbor_trail] == ["order.submitted", "order.filled"]
    assert [e["event"] for e in beacon_trail] == ["signal.evaluated"]
    assert all(e["tenant_id"] == "harbor" for e in harbor_trail)
