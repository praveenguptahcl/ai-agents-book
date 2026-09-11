"""Kill switches and hard risk limits for the AlphaForge / WealthForge agent team.

The kill switch is infrastructure, not agent logic. It sits OUTSIDE the
agent's authority — between the decision plane and the broker — and it
fails CLOSED. If the supervisor process dies, the heartbeat goes stale,
or an operator engages a kill level, the executor cannot submit. No
cooperation from the agent is required, because none is asked for.

Four levels, in escalating order:

  1. PAUSE_INTENTS — no new submits. Open orders keep working; cancel,
     reconcile and reads are unaffected.
  2. CANCEL_OPEN   — level 1, plus every open order is cancelled once,
     at engagement time.
  3. FLATTEN_HALT  — level 2, plus all positions are flattened. Engaged
     automatically by RiskMonitor on a hard risk-limit breach (default:
     3% daily drawdown). Only a human admin can re-arm afterwards.
  4. FULL_STOP      — level 3, plus the broker API keys are revoked and
     every state-changing effect is frozen. Requires TWO distinct
     VERIFIED operator sessions to engage, and TWO distinct admins to
     lift — always, regardless of who engaged it.

Even at FULL_STOP, reconcile() and reads are allowed: freezing is not
the same as resolving. An unknown order is still resolved against broker
truth — it is just never re-submitted.

The dead-man's heartbeat: the submit path must pass the gate, which
requires a FRESH heartbeat from the supervisor process. A stale or
missing heartbeat refuses the submit. Loss of the heartbeat kills
trading — never the other way around. The switch boots armed-by-default:
before the first beat, every submit is refused.

The gate has TWO positions, and both matter. The caller checks
``check("submit")`` BEFORE any ledger mutation, so a refused submit
leaves no phantom row. But a check-then-call is a TOCTOU race: the kill
can engage in the gap between the check and the wire. So the kill
switch also WRAPS the broker client (``guarded()``) and re-checks at
the last possible instant — immediately before the broker is touched.
The early check keeps the ledger honest; the late check keeps the
broker honest. Reconcile reads (``lookup``) are never gated.

Verified operator identities: ``engage()`` and ``disarm()`` accept ONLY
``OperatorSession`` objects — HMAC-signed credentials issued by the
``OperatorRegistry`` and re-verified (signature, expiry, registration,
role, revocation) on every use, the same discipline as the Ch 6 tenant
tokens. Raw credential strings are rejected outright: accepting
``["admin-ruth", "admin-sam"]`` as a list of strings is API theater — a
single attacker with execution-plane access can type any two names.
``issue()`` is the trusted bootstrap's tool; in production, sessions are
minted at the ingress gateway behind real authentication, and the
registry here is the stand-in for that gateway.

Scoped kills: a kill can target ``scope=("tenant", tid)`` or
``scope=("strategy", sid)`` instead of the whole firm — halting every
desk because one dividend-capture agent looped is too blunt. A global
kill (``scope=None``) still applies to everything; scoped kills compose
with it. Effects (cancel/flatten/revoke) receive the scope so the wired
functions can target precisely.

Re-arm policy: disarming requires strictly greater authority than the
engager(s), plus a written reason appended to the audit log — EXCEPT
that a FULL_STOP always requires two distinct admins to lift, no matter
who engaged it. Two rank-1 operators engaging a full stop does NOT let
a single rank-2 risk officer lift it. The audit log is append-only and
exported for the evidence ledger (Ch 14) and compliance reporting
(Ch 19).

Stdlib only.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum


class KillLevel(IntEnum):
    NONE = 0
    PAUSE_INTENTS = 1
    CANCEL_OPEN = 2
    FLATTEN_HALT = 3
    FULL_STOP = 4


ROLE_RANK = {"operator": 1, "risk_officer": 2, "admin": 3}

#: Identity under which the automated risk monitor engages kills.
SYSTEM_ACTOR = "risk-monitor"

#: Version tag for operator session tokens.
_SESSION_VERSION = "os1"


class HaltedError(Exception):
    """A submit or state-changing effect was refused by the kill switch."""


class HeartbeatStale(HaltedError):
    """The supervisor heartbeat is missing or older than the window.

    A subclass of HaltedError: callers treat it the same way (do not
    submit), but operators can distinguish "killed" from "supervisor dead".
    """


class KillAuthError(Exception):
    """Bad kill-switch authority: unknown operator, insufficient rank,
    missing second credential, raw (unverified) identity, or missing
    written reason."""


# ---------------------------------------------------------------------------
# Verified operator identities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OperatorSession:
    """A cryptographically bound operator identity.

    Same discipline as the Ch 6 tenant tokens: the (operator_id, role,
    expiry) payload is HMAC-signed, and the session is re-verified on
    every use — never trusted on its word, because the operator may have
    been revoked or demoted since it was issued.
    """

    token: str
    operator_id: str
    role: str
    issued_at: float
    expires_at: float


class OperatorRegistry:
    """Issues and verifies operator sessions. The stand-in for the
    production ingress gateway: ``issue()`` is the trusted bootstrap's
    tool, ``verify()`` is the enforcement point that runs on every
    engage/disarm call."""

    def __init__(self, operators: dict[str, str], secret: bytes, clock=None):
        unknown_roles = set(operators.values()) - set(ROLE_RANK)
        if unknown_roles:
            raise ValueError(f"unknown roles: {sorted(unknown_roles)}")
        if len(secret) < 16:
            raise ValueError("secret must be at least 16 bytes")
        self._operators = dict(operators)
        self._secret = secret
        self._clock = clock or time.time
        self._revoked: set[str] = set()

    def _sign(self, payload: str) -> str:
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()

    def issue(self, operator_id: str, ttl_seconds: float = 3600.0) -> OperatorSession:
        """Mint a session for a registered operator. Trusted bootstrap
        only — in production this happens at the ingress gateway behind
        real authentication."""
        try:
            role = self._operators[operator_id]
        except KeyError:
            raise KillAuthError(f"unknown operator: {operator_id!r}") from None
        if operator_id in self._revoked:
            raise KillAuthError(f"operator {operator_id!r} is revoked")
        now = self._clock()
        iat, exp = int(now), int(now + ttl_seconds)
        nonce = secrets.token_hex(8)  # uniqueness only, not replay protection
        payload = f"{_SESSION_VERSION}.{operator_id}.{role}.{iat}.{exp}.{nonce}"
        return OperatorSession(
            token=f"{payload}.{self._sign(payload)}",
            operator_id=operator_id,
            role=role,
            issued_at=float(iat),
            expires_at=float(exp),
        )

    def verify(self, token_or_session) -> OperatorSession:
        """Re-verify from the token bytes on every use. Raw strings are
        rejected: an unverified name is not an identity."""
        if isinstance(token_or_session, OperatorSession):
            token = token_or_session.token
        elif isinstance(token_or_session, str):
            raise KillAuthError(
                "operator identities must be verified OperatorSession objects; "
                f"raw credential string {token_or_session!r} rejected — a list "
                "of names is not two-person control"
            )
        else:
            raise KillAuthError(f"not an operator session: {token_or_session!r}")
        parts = token.split(".")
        if len(parts) != 7 or parts[0] != _SESSION_VERSION:
            raise KillAuthError("malformed operator session")
        _, operator_id, role, iat_s, exp_s, _nonce, sig = parts
        if not hmac.compare_digest(self._sign(".".join(parts[:6])), sig):
            raise KillAuthError("bad operator session signature")
        try:
            iat, exp = int(iat_s), int(exp_s)
        except ValueError:
            raise KillAuthError("bad operator session timestamps") from None
        if self._clock() > exp:
            raise KillAuthError(f"operator session for {operator_id!r} expired")
        current_role = self._operators.get(operator_id)
        if current_role is None:
            raise KillAuthError(f"unknown operator: {operator_id!r}")
        if operator_id in self._revoked:
            raise KillAuthError(f"operator {operator_id!r} is revoked")
        if role != current_role:
            # Demoted since issuance: the old session dies with the old rank.
            raise KillAuthError(
                f"operator {operator_id!r} role changed since session issued "
                f"({role!r} -> {current_role!r}); re-authenticate"
            )
        return OperatorSession(token, operator_id, role, float(iat), float(exp))

    def revoke(self, operator_id: str) -> None:
        """Revoke takes effect on the very next verify — no cached trust."""
        if operator_id not in self._operators:
            raise KillAuthError(f"unknown operator: {operator_id!r}")
        self._revoked.add(operator_id)

    def rank(self, operator_id: str) -> int:
        try:
            return ROLE_RANK[self._operators[operator_id]]
        except KeyError:
            raise KillAuthError(f"unknown operator: {operator_id!r}") from None

    def __contains__(self, operator_id: str) -> bool:
        return operator_id in self._operators and operator_id not in self._revoked


def _check_scope(scope) -> None:
    if scope is None:
        return
    if (
        isinstance(scope, tuple)
        and len(scope) == 2
        and scope[0] in ("tenant", "strategy")
        and isinstance(scope[1], str)
        and scope[1]
    ):
        return
    raise KillAuthError(
        f"bad kill scope {scope!r}: must be None, ('tenant', id) or ('strategy', id)"
    )


# ---------------------------------------------------------------------------
# The kill switch
# ---------------------------------------------------------------------------


class KillSwitch:
    """The stop button that does not ask the agent for permission.

    ``check()`` is the gate. ``guarded()`` wraps the broker client so the
    gate is consulted again at send time (the TOCTOU fix). ``engage()``
    and ``disarm()`` take verified ``OperatorSession`` objects only.
    """

    def __init__(
        self,
        registry: OperatorRegistry,
        heartbeat_window_s: float = 30.0,
        clock=None,
        cancel_open_fn=None,
        flatten_fn=None,
        revoke_keys_fn=None,
    ):
        self._registry = registry
        self._window = float(heartbeat_window_s)
        self._clock = clock or time.monotonic
        self._cancel_open_fn = cancel_open_fn
        self._flatten_fn = flatten_fn
        self._revoke_keys_fn = revoke_keys_fn
        # Armed kills: one record per scope. A global record (scope None)
        # applies to every action; a scoped record applies only to actions
        # carrying the same scope.
        self._kills: list[dict] = []
        self._last_beat: float | None = None
        self._audit: list[dict] = []

    # -- introspection -------------------------------------------------
    def _record_for(self, scope):
        for rec in self._kills:
            if rec["scope"] == scope:
                return rec
        return None

    @property
    def level(self) -> KillLevel:
        """Highest armed level across all scopes."""
        return self.level_for()

    def level_for(self, scope=None) -> KillLevel:
        """Highest armed level governing this scope.

        A global kill (scope None) governs every action. A scoped kill
        governs only actions carrying the same scope — it never leaks
        into unscoped actions or other tenants' actions.
        """
        if scope is None:
            levels = [rec["level"] for rec in self._kills if rec["scope"] is None]
        else:
            levels = [
                rec["level"]
                for rec in self._kills
                if rec["scope"] is None or rec["scope"] == scope
            ]
        return max(levels, default=KillLevel.NONE)

    @property
    def armed(self) -> bool:
        return bool(self._kills)

    def armed_scopes(self) -> list:
        """Which scopes currently have kills armed (None = global)."""
        return [rec["scope"] for rec in self._kills]

    def audit(self) -> list[dict]:
        """Append-only record of every engage/disarm. Export this to the
        evidence ledger (Ch 14); auditors read it in Ch 19."""
        return [dict(entry) for entry in self._audit]

    # -- heartbeat ------------------------------------------------------
    def beat(self) -> None:
        """Fresh heartbeat from the supervisor process. Beats are not
        audited — at one beat per few seconds the log would be noise;
        what matters (stale refusals) surfaces in the executor's logs."""
        self._last_beat = self._clock()

    def _heartbeat_fresh(self) -> bool:
        return (
            self._last_beat is not None
            and (self._clock() - self._last_beat) <= self._window
        )

    # -- the gate --------------------------------------------------------
    def check(self, action: str, scope=None) -> None:
        """Gate every effect. Actions: 'submit', 'cancel', 'reconcile', 'read'.

        ``scope`` is the action's scope — ("tenant", id) or ("strategy",
        id). A global kill applies to every action; a scoped kill applies
        only to actions carrying the same scope.

        reconcile/read always pass — freezing is not resolving. cancel
        passes at levels 1-3 (it is the cleanup mechanism) and freezes
        only at FULL_STOP. submit requires no armed kill AND a fresh
        heartbeat, checked in that order.
        """
        _check_scope(scope)
        level = self.level_for(scope)
        if action in ("read", "reconcile"):
            return None
        if action == "cancel":
            if level >= KillLevel.FULL_STOP:
                raise HaltedError(
                    f"cancel refused: {level.name} armed: "
                    f"{self._describe_applicable(scope)}"
                )
            return None
        if action == "submit":
            if level >= KillLevel.PAUSE_INTENTS:
                raise HaltedError(
                    f"submit refused: kill {level.name} armed: "
                    f"{self._describe_applicable(scope)}"
                )
            if not self._heartbeat_fresh():
                raise HeartbeatStale(
                    "submit refused: supervisor heartbeat stale or missing "
                    f"(window {self._window}s) — trading stays dead until "
                    "the supervisor beats again"
                )
            return None
        raise KillAuthError(f"unknown action: {action!r}")

    def _describe_applicable(self, scope) -> str:
        if scope is None:
            recs = [rec for rec in self._kills if rec["scope"] is None]
        else:
            recs = [
                rec
                for rec in self._kills
                if rec["scope"] is None or rec["scope"] == scope
            ]
        return "; ".join(
            f"{rec['level'].name} by {rec['engaged_by']} "
            f"(scope={rec['scope']!r}): {rec['reason']}"
            for rec in recs
        )

    # -- wrapping the client: the TOCTOU fix ------------------------------
    def guarded(self, broker):
        """Wrap the broker client so the gate is consulted at send time.

        A ``check()`` before the ledger write keeps refused submits out of
        the ledger — but between that check and the wire call, the kill
        can engage. This wrapper re-checks ``submit`` at the last possible
        instant, immediately before the broker is touched. ``lookup`` is
        read-only truth and is never gated, even at FULL_STOP.
        """
        return GuardedBroker(self, broker)

    # -- engaging ----------------------------------------------------------
    def engage(
        self,
        level: KillLevel | int,
        sessions: list[OperatorSession],
        reason: str,
        scope=None,
    ) -> dict:
        """Arm a kill level. Level 4 needs two DISTINCT verified operator
        sessions — never raw strings. ``scope`` narrows the kill to one
        tenant or strategy; None means the whole firm.

        Side effects (cancel opens, flatten, revoke keys) run once per
        (scope, effect), in escalating order, and their outcomes land in
        the audit log. A failed effect does NOT disarm the kill — the
        state arms regardless, because a kill switch that fails to arm
        when the broker's cancel endpoint flaps is worse than useless.
        Effect functions receive the scope so they can target precisely.
        """
        level = KillLevel(level)
        if level == KillLevel.NONE:
            raise KillAuthError("engage requires a kill level 1-4")
        if not reason or not reason.strip():
            raise KillAuthError("engaging a kill requires a written reason")
        _check_scope(scope)
        verified = [self._registry.verify(s) for s in sessions]  # raises on raw strings
        ids = [s.operator_id for s in verified]
        if len(set(ids)) != len(ids):
            raise KillAuthError("duplicate operator sessions are not two people")
        if not verified:
            raise KillAuthError("at least one verified operator session is required")
        ranks = [ROLE_RANK[s.role] for s in verified]
        if level == KillLevel.FULL_STOP and len(verified) < 2:
            raise KillAuthError(
                "FULL_STOP requires two distinct VERIFIED operator sessions"
            )
        existing = self._record_for(scope)
        if existing is not None and level <= existing["level"]:
            raise KillAuthError(
                f"kill already armed at {existing['level'].name} for scope {scope!r}: "
                "disarm before changing level"
            )
        # PRODUCTION HARDENING (one line): restrict heavy levels, e.g.
        #   if level >= KillLevel.FLATTEN_HALT and max(ranks) < ROLE_RANK["risk_officer"]:
        #       raise KillAuthError("FLATTEN_HALT and above require risk_officer+")

        effects_done: set[str] = set() if existing is None else set(existing["effects_done"])
        effects = []
        if level >= KillLevel.CANCEL_OPEN and "cancel_open" not in effects_done:
            effects.append(
                ("cancel_open", self._run_effect("cancel_open", self._cancel_open_fn, scope, effects_done))
            )
        if level >= KillLevel.FLATTEN_HALT and "flatten" not in effects_done:
            effects.append(
                ("flatten", self._run_effect("flatten", self._flatten_fn, scope, effects_done))
            )
        if level == KillLevel.FULL_STOP and "revoke_keys" not in effects_done:
            effects.append(
                ("revoke_keys", self._run_effect("revoke_keys", self._revoke_keys_fn, scope, effects_done))
            )

        record = {
            "level": level,
            "scope": scope,
            "engaged_by": ids,
            "engager_rank": max(ranks),
            "reason": reason.strip(),
            "effects_done": effects_done,
        }
        if existing is not None:
            self._kills.remove(existing)
        self._kills.append(record)
        self._audit.append(
            {
                "ts": _utcnow_iso(),
                "event": "engage",
                "level": level.name,
                "scope": None if scope is None else list(scope),
                "by": list(ids),
                "reason": record["reason"],
                "effects": [
                    {"name": name, "ok": ok, "detail": detail}
                    for name, (ok, detail) in effects
                ],
            }
        )
        return {
            "level": level,
            "scope": scope,
            "effects": {name: detail for name, (_, detail) in effects},
        }

    def _run_effect(self, name: str, fn, scope, effects_done: set) -> tuple[bool, str]:
        effects_done.add(name)
        if fn is None:
            return True, "no-op (no function wired)"
        try:
            detail = fn(scope)
            return True, str(detail) if detail is not None else "ok"
        except Exception as exc:  # noqa: BLE001 — the kill arms regardless
            return False, f"FAILED: {type(exc).__name__}: {exc}"

    # -- re-arming -----------------------------------------------------------
    def disarm(
        self,
        session: OperatorSession,
        reason: str,
        second_session: OperatorSession | None = None,
        scope=None,
    ) -> dict:
        """Lift the kill for one scope (None = the global kill).

        A FULL_STOP always requires two distinct VERIFIED admins to lift —
        regardless of who engaged it. Otherwise, lifting requires strictly
        greater authority than the engager(s), plus a written reason. The
        reason is appended to the audit log verbatim — "looks fine now" is
        a career-limiting entry.
        """
        _check_scope(scope)
        record = self._record_for(scope)
        if record is None:
            armed = self.armed_scopes()
            raise KillAuthError(
                f"no kill is armed for scope {scope!r}"
                + (f" (armed scopes: {armed})" if armed else "")
            )
        if not reason or not reason.strip():
            raise KillAuthError("re-arming requires a written reason")
        me = self._registry.verify(session)
        if record["level"] >= KillLevel.FULL_STOP:
            # ALWAYS two admins — even if two rank-1 operators engaged it.
            # A single risk officer can never lift a full stop.
            if second_session is None:
                raise KillAuthError(
                    "lifting a FULL_STOP requires two distinct verified admins"
                )
            other = self._registry.verify(second_session)
            if other.operator_id == me.operator_id:
                raise KillAuthError("two distinct admins are required, not one twice")
            if ROLE_RANK[me.role] < ROLE_RANK["admin"] or ROLE_RANK[other.role] < ROLE_RANK["admin"]:
                raise KillAuthError("both lifters must hold admin rank")
            lifted_by = [me.operator_id, other.operator_id]
        else:
            if ROLE_RANK[me.role] <= record["engager_rank"]:
                raise KillAuthError(
                    f"re-arm requires authority strictly above rank {record['engager_rank']} "
                    f"(kill engaged by {record['engaged_by']}); {me.operator_id} holds rank "
                    f"{ROLE_RANK[me.role]}"
                )
            lifted_by = [me.operator_id]
        entry = {
            "ts": _utcnow_iso(),
            "event": "disarm",
            "level": record["level"].name,
            "scope": None if scope is None else list(scope),
            "by": lifted_by,
            "reason": reason.strip(),
            "previous_engagers": list(record["engaged_by"]),
        }
        self._kills.remove(record)
        self._audit.append(entry)
        return {"armed": self.armed, "audit_entry": entry}


class GuardedBroker:
    """The kill switch wrapped around the actual broker client.

    The caller's early ``check("submit")`` (before the ledger write) keeps
    refused submits out of the ledger — but the kill can engage in the gap
    between that check and the wire call. This wrapper closes the TOCTOU
    window: the gate is consulted at the last possible instant, immediately
    before the broker is touched. ``lookup`` is read-only truth-seeking
    and is never gated, even at FULL_STOP.
    """

    def __init__(self, killswitch: KillSwitch, broker):
        self._kill = killswitch
        self._broker = broker

    def __call__(self, order: dict, timeout=None):
        self._kill.check("submit")  # at send time — the TOCTOU fix
        return self._broker(order, timeout)

    def lookup(self, key: str):
        return self._broker.lookup(key)  # reconcile reads: never gated


class RiskMonitor:
    """Hard risk limits that engage the kill switch WITHOUT asking anyone.

    Tracks the equity peak and engages FLATTEN_HALT the moment the
    drawdown breaches the limit (default 3% — the WealthForge desk rule).
    It engages as SYSTEM_ACTOR at risk-officer rank, which means only a
    human admin can re-arm afterwards: the machine that stopped you does
    not get to restart you on its own say-so.

    The monitor holds a verified operator session for the system actor,
    issued by the registry at construction (in production, the
    supervisor's identity is minted at the ingress gateway).

    Reset the peak at each session open in production; here the peak is
    tracked since construction so the drill is deterministic.
    """

    def __init__(self, registry: OperatorRegistry, max_daily_drawdown: float = 0.03):
        if not 0 < max_daily_drawdown < 1:
            raise ValueError("max_daily_drawdown must be a fraction in (0, 1)")
        self._limit = float(max_daily_drawdown)
        self._actor = registry.issue(SYSTEM_ACTOR)
        self._peak: float | None = None
        self._equity: float | None = None

    def record_equity(self, value: float) -> None:
        value = float(value)
        self._equity = value
        if self._peak is None or value > self._peak:
            self._peak = value

    def drawdown(self) -> float:
        if not self._peak:
            return 0.0
        return max(0.0, (self._peak - self._equity) / self._peak)

    def check(self, killswitch: KillSwitch) -> bool:
        """Returns True if this call engaged the kill."""
        dd = self.drawdown()
        # Compare against the GLOBAL level only: a tenant-scoped kill must
        # not suppress the firm-wide automatic halt.
        if dd >= self._limit and killswitch.level_for() < KillLevel.FLATTEN_HALT:
            killswitch.engage(
                KillLevel.FLATTEN_HALT,
                [self._actor],
                f"hard risk limit breached: drawdown {dd:.2%} >= limit {self._limit:.2%}",
            )
            return True
        return False


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
