"""Chapter 3 — System intent: explicit, validated, immutable configuration.

Thesis: an agent whose purpose lives in a prompt paragraph has no intent —
it has a suggestion. This module loads the desk's mandate from a versioned
TOML file plus secrets from a ``.env`` file, validates everything
fail-closed with Pydantic v2, and freezes the result into an immutable
``SystemIntent`` carrying a content hash. If it isn't in the config, the
agent may not do it.

The split is deliberate and load-bearing:

- ``.env`` carries *secrets* (API key id/secret) — twelve-factor style,
  never committed, never logged, never hashed into the intent.
- ``intent.toml`` carries *policy* (universe, limits, mandates) —
  versioned, reviewed, diffable, and hashed, so "what was the system
  told to do?" is answerable months later from the audit trail (Ch 9).

Failure discipline: a missing file or missing secret raises ``ConfigError``
naming exactly what is absent. A malformed value raises Pydantic's
``ValidationError`` naming the exact key path. In both cases the process
refuses to start. Refusing to start is the safest action an agent
framework can take.

PAPER ONLY. No real money, no real keys, no real broker endpoints.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Vocabularies: closed sets shared with the rest of the book.
# ---------------------------------------------------------------------------

#: The firm has permissioned exactly these names for paper trading.
#: Matches code/ch04/schemas.py ALLOWED_SYMBOLS so the chapters agree.
#: A universe entry outside this set is caught at startup, not at 3am.
APPROVED_UNIVERSE: frozenset = frozenset(
    {"AAPL", "MSFT", "NVDA", "SPY", "QQQ", "AMD"}
)

#: Production broker hosts. A paper-trading intent that points at any of
#: these is not a misconfiguration — it is a loaded gun. Refuse it.
PRODUCTION_HOSTS: frozenset = frozenset(
    {
        "api.alpaca.markets",
        "api.live.trading",  # placeholder for the reader's own broker
    }
)

#: A paper endpoint must *say* it is paper. If the URL carries no paper /
#: sandbox / demo marker we refuse to guess — we would rather reject a
#: legitimate paper URL than trust a production one.
PAPER_MARKERS = ("paper", "sandbox", "demo", "sim")

#: Strategy ids are machine names, not prose. The allowlist is a closed
#: world: a strategy not named here may not run, no matter what the
#: planner claims it is called.
_STRATEGY_ID_RE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")

#: Desk names are machine names for the same reason.
_DESK_NAME_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")

#: Hard ceiling on leverage. Above 2x the desk is not trading, it is
#: gambling with the firm's balance sheet. Fail closed.
MAX_LEVERAGE_CEILING = 2.0


class ConfigError(Exception):
    """The intent could not be loaded: missing file, missing secret,
    malformed .env. The key or file that is wrong is always named."""


# ---------------------------------------------------------------------------
# .env parsing: secrets only, strict, no silent ambiguity.
# ---------------------------------------------------------------------------

def _parse_dotenv(path: str | Path) -> dict[str, str]:
    """Parse a minimal ``.env`` file into a dict.

    Supports ``KEY=value``, ``export KEY=value``, ``#`` comments, and
    single/double-quoted values. Rules are fail-closed: a duplicate key
    or a malformed line raises ``ConfigError`` instead of guessing.
    """
    p = Path(path)
    if not p.is_file():
        raise ConfigError(
            f".env file not found: {p}. Refusing to start without secrets."
        )
    values: dict[str, str] = {}
    for lineno, raw in enumerate(p.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            raise ConfigError(
                f"{p}:{lineno}: malformed line (no '='): {raw!r}"
            )
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ConfigError(
                f"{p}:{lineno}: bad key name {key!r} "
                "(expect UPPER_SNAKE_CASE)"
            )
        if (len(value) >= 2 and value[0] == value[-1]
                and value[0] in ("'", '"')):
            value = value[1:-1]
        if key in values:
            raise ConfigError(
                f"{p}:{lineno}: duplicate key {key!r} — "
                "ambiguity in secrets is a security smell"
            )
        values[key] = value
    return values


@dataclass(frozen=True)
class Secrets:
    """Paper-broker credentials. Frozen, never logged, never hashed.

    ``repr`` is redacted by hand because the default dataclass repr would
    print the secret into trace logs — the exact leak Ch 9 warns about.
    """

    api_key: str
    api_secret: str

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "Secrets(api_key='***', api_secret='***')"


REQUIRED_SECRETS = ("ALPHAFORGE_PAPER_API_KEY", "ALPHAFORGE_PAPER_API_SECRET")


def load_secrets(env_path: str | Path) -> Secrets:
    """Load and validate secrets from a ``.env`` file.

    Every required key must be present and non-empty. A missing secret
    is a startup refusal, not a default — there is no safe default
    credential.
    """
    values = _parse_dotenv(env_path)
    missing = [k for k in REQUIRED_SECRETS if not values.get(k)]
    if missing:
        raise ConfigError(
            f"missing required secret(s) in {env_path}: "
            f"{', '.join(missing)}. Refusing to start."
        )
    return Secrets(
        api_key=values["ALPHAFORGE_PAPER_API_KEY"],
        api_secret=values["ALPHAFORGE_PAPER_API_SECRET"],
    )


# ---------------------------------------------------------------------------
# Policy models: Pydantic v2, frozen, extra=forbid everywhere. A closed
# world — unknown keys are rejected, because an unknown key is either a
# typo for a real control or an attempt to smuggle one in.
# ---------------------------------------------------------------------------

class _FrozenBase(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}


class DeskConfig(_FrozenBase):
    """Who this intent is for and what data it may look at."""

    # NOTE: pydantic's pattern uses the Rust regex engine, which has no \Z;
    # $ (end of text, multi-line off) is the portable anchor here. The
    # Python-side _DESK_NAME_RE keeps \Z for fullmatch use elsewhere.
    name: str = Field(pattern=r"[a-z][a-z0-9_-]{0,63}$")
    data_mode: Literal["real", "synthetic"] = Field(
        description="Provenance mode for this run: every bar the system "
        "touches is labeled REAL or SYNTHETIC accordingly."
    )
    universe: list[str] = Field(min_length=1)

    @field_validator("universe")
    @classmethod
    def universe_must_be_approved(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip().upper() for s in v]
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("universe contains duplicate symbols")
        unknown = [s for s in cleaned if s not in APPROVED_UNIVERSE]
        if unknown:
            raise ValueError(
                f"unapproved symbol(s) in universe: {unknown}. "
                f"Approved: {sorted(APPROVED_UNIVERSE)}. "
                "Caught at startup, not at 3am."
            )
        return cleaned


class BrokerConfig(_FrozenBase):
    """Where orders go. Paper endpoints only — enforced, not hoped for."""

    base_url: str
    account: Literal["paper"] = "paper"

    @field_validator("base_url")
    @classmethod
    def must_be_a_paper_endpoint(cls, v: str) -> str:
        url = urlparse(v.strip())
        if url.scheme != "https":
            raise ValueError("broker base_url must use https")
        host = (url.hostname or "").lower()
        if not host:
            raise ValueError("broker base_url has no host")
        if host in PRODUCTION_HOSTS:
            raise ValueError(
                f"broker base_url points at production host {host!r}. "
                "This is a paper-trading intent. Refusing to start."
            )
        if not any(m in host for m in PAPER_MARKERS):
            raise ValueError(
                f"broker base_url host {host!r} carries no paper/sandbox/"
                "demo marker. We refuse to guess — point it at an "
                "explicit paper endpoint."
            )
        return v.strip()


class RiskConfig(_FrozenBase):
    """How much the desk may lose and how concentrated it may get."""

    max_daily_loss_pct: float = Field(gt=0.0, le=1.0)
    max_leverage: float = Field(gt=0.0, le=MAX_LEVERAGE_CEILING)
    long_only: bool = False
    per_symbol_max_notional: float = Field(gt=0.0)
    per_order_max_notional: float = Field(gt=0.0)
    execute_on_next_bar_open: bool = Field(
        description="t+1 rule: a signal decided on bar t may not execute "
        "before bar t+1's open. Non-negotiable in this architecture."
    )

    @field_validator("execute_on_next_bar_open")
    @classmethod
    def t_plus_one_is_not_optional(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError(
                "execute_on_next_bar_open=false is rejected: the t+1 "
                "execution rule is not optional in this architecture."
            )
        return v


class KillSwitchConfig(_FrozenBase):
    """When the independent monitor pulls the plug (Ch 11)."""

    daily_drawdown_halt_pct: float = Field(gt=0.0, le=1.0)
    max_orders_per_minute: int = Field(gt=0)


class StrategyConfig(_FrozenBase):
    """Which strategies may run, and under what inviolable rule."""

    allowed: list[str] = Field(min_length=1)
    emit_intentions_only: bool = Field(
        description="Strategies emit intentions (symbol, side, confidence), "
        "never orders. The backtester/broker turns intentions into orders."
    )

    @field_validator("allowed")
    @classmethod
    def strategy_ids_must_be_machine_names(
        cls, v: list[str]
    ) -> list[str]:
        for name in v:
            if not _STRATEGY_ID_RE.fullmatch(name):
                raise ValueError(
                    f"strategy id {name!r} is not a machine name "
                    "(lowercase, digits, underscores)"
                )
        if len(set(v)) != len(v):
            raise ValueError("strategies.allowed contains duplicates")
        return v

    @field_validator("emit_intentions_only")
    @classmethod
    def intentions_are_not_optional(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError(
                "emit_intentions_only=false is rejected: strategies emit "
                "intentions, never orders. That boundary is structural."
            )
        return v


class IntentConfig(_FrozenBase):
    """The whole mandate. One object, frozen, hashed, auditable."""

    desk: DeskConfig
    broker: BrokerConfig
    risk: RiskConfig
    killswitch: KillSwitchConfig
    strategies: StrategyConfig

    @model_validator(mode="after")
    def cross_field_guards(self) -> "IntentConfig":
        if (self.risk.per_order_max_notional
                > self.risk.per_symbol_max_notional):
            raise ValueError(
                "risk.per_order_max_notional "
                f"({self.risk.per_order_max_notional}) exceeds "
                "risk.per_symbol_max_notional "
                f"({self.risk.per_symbol_max_notional}): a single order "
                "must never be allowed to breach the per-symbol cap."
            )
        if (self.killswitch.daily_drawdown_halt_pct
                > self.risk.max_daily_loss_pct):
            raise ValueError(
                "killswitch.daily_drawdown_halt_pct "
                f"({self.killswitch.daily_drawdown_halt_pct}) exceeds "
                "risk.max_daily_loss_pct "
                f"({self.risk.max_daily_loss_pct}): a kill switch set "
                "above the loss limit is decoration."
            )
        return self


# ---------------------------------------------------------------------------
# The frozen intent: config + content hash. Secrets never enter the hash.
# ---------------------------------------------------------------------------

def _intent_hash(config: IntentConfig) -> str:
    canonical = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class SystemIntent:
    """The desk's mandate, validated and frozen.

    ``intent_hash`` is the version stamp: log it to the audit trail
    (Ch 9) and the question "what was the system told to do?" stays
    answerable months later. Secrets are deliberately excluded — the
    hash covers policy, never credentials.
    """

    config: IntentConfig
    intent_hash: str
    loaded_from: tuple[str, str]  # (intent_toml, env_file)


def load_system_intent(
    intent_path: str | Path, env_path: str | Path
) -> tuple[SystemIntent, Secrets]:
    """Load, validate, and freeze the system intent.

    Returns ``(intent, secrets)``. Raises ``ConfigError`` for missing
    files/secrets and Pydantic ``ValidationError`` (naming the exact key
    path) for malformed policy. Either way the caller must not start.
    """
    intent_p = Path(intent_path)
    if not intent_p.is_file():
        raise ConfigError(
            f"intent file not found: {intent_p}. "
            "An agent with no declared intent does not start."
        )
    try:
        with open(intent_p, "rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"intent file {intent_p} is not valid TOML: {exc}")
    secrets = load_secrets(env_path)  # secrets validated first: no
    # point parsing policy for a process that cannot authenticate
    config = IntentConfig.model_validate(raw)
    intent = SystemIntent(
        config=config,
        intent_hash=_intent_hash(config),
        loaded_from=(str(intent_p), str(Path(env_path))),
    )
    return intent, secrets
