# Chapter 3: Defining System Intent

At 2:47 on a Tuesday morning, the AlphaForge research agent bought 400 shares of GME.

Nothing in its prompt told it to. Nothing in its prompt told it *not* to, either. The system prompt said "trade momentum names in the approved universe." The model, doing what models do, weighed "momentum names" as the operative phrase and "approved universe" as decorative context. GME was exhibiting extraordinary momentum. The paper broker accepted the order without complaint. The momentum desk's walk-forward numbers were contaminated by a symbol the desk had never approved, and nobody noticed for three days — because the system had no machine-checkable statement of what it was for. The intent lived in a paragraph. A paragraph is a suggestion.

Chapter 1 showed what happens when authority is ambient. Chapter 2 gave the loop its shape: observe, decide, act, verify. This chapter gives the loop its *purpose* — and makes that purpose something a program can check, not something a reader must interpret. The thesis is one sentence long:

**An agent whose purpose lives in a prompt paragraph has no intent. It has a suggestion.**

System intent is the desk's mandate made explicit, versioned, validated, and immutable: the universe of symbols it may touch, the risk limits it may not cross, the strategy mandates it operates under, the broker endpoints it may reach (paper only), the kill-switch thresholds that override everything. If it isn't in the config, the agent may not do it. The GME order above dies at startup — or rather, the *configuration that would have permitted it* dies at startup, months before any model gets creative at 2:47 in the morning.

## Fail closed, or fail at 3am

Every configuration system makes a choice about absence. When a key is missing, do you guess or do you refuse? Most frameworks guess. They call the guesses "sensible defaults," and sensible defaults are a security smell in agentic systems. Consider `max_leverage`. Suppose the loader applies a default of 1.0 when the key is absent. The desk believes it set 1.0 deliberately. The config never said so. Six months later a library upgrade changes the default to 2.0, and every desk's leverage doubles overnight — no commit, no review, no audit trail entry, because nothing *changed* in any file anyone watches. The default was load-bearing and invisible, which is the worst combination a control can have.

The alternative is fail-closed: a missing key is a refusal to start. This feels hostile the first time you meet it. Your agent won't boot because someone forgot `max_orders_per_minute` in a TOML file, and you're staring at a `ValidationError` instead of a trading session. That hostility is the point. Starting with an undeclared mandate is not a degraded mode; it is the precise failure the GME incident demonstrates. An agent that starts without knowing its limits will discover them empirically, at market prices.

There is a classical formulation of this discipline — the twelve-factor app's rule that config varies between deploys while code does not. For agents the principle sharpens: the *mandate* varies between runs, and each run must be pinned to its mandate. Code doesn't change between paper and live; config does. That is exactly why the paper-only invariant lives in config *validation*, not in a comment above a URL. Comments don't run.

One more prohibition, because it will tempt you: this chapter's loader does not allow environment variables to override policy. It is a common pattern — `ALPHAFORGE_UNIVERSE` quietly widening the symbol list for a "quick test" — and it is unauditable. An env var that changes the mandate at 2am leaves no diff, no review, no version. If you want to change what the system is for, you change the file, you commit the file, and someone reviews the file. Policy moves through version control or it doesn't move.

## The shape of intent

The mandate has five sections. Each one answers a question the loop in Chapter 2 cannot ask itself:

| Section | Question it answers |
|---|---|
| `desk` | *Who* is this run for, what data may it look at, and is that data real or synthetic? |
| `broker` | *Where* may orders go — and can we prove it's paper? |
| `risk` | *How much* may be lost, how concentrated may positions get, and is the t+1 execution rule on? |
| `killswitch` | *When* does the independent monitor pull the plug? (Full treatment in Ch 11.) |
| `strategies` | *Which* strategies may run — and do they understand they emit intentions, never orders? |

Notice what the table does not contain: model names, prompt templates, temperature settings. Those are *tactics*. Intent is the boundary inside which tactics operate. The model may choose how to pursue momentum; it may not choose what momentum means, what it may trade, or how much it may lose finding out.

A word on the file format, because it will be questioned: TOML, not YAML. YAML has executable tags, anchor aliases, and a long history of parser differentials — a config format that can execute code is not a config format, it's a deployment vector. TOML parses with the standard library's `tomllib`, has no surprises, and diffs cleanly in review. The mandate deserves a boring format. Boring is auditable.

Two of the fields deserve attention before we see any code, because they encode invariants this book treats as structural, not configurable. `execute_on_next_bar_open` must be `true`: a signal decided on bar `t` cannot execute before bar `t+1`'s open, and the config documents the invariant so the audit trail can see it was declared, not assumed. `emit_intentions_only` must be `true`: strategies emit intentions — symbol, side, confidence — and the backtester or broker turns intentions into orders. The strategy never touches orders. These are not preferences the desk sets; they are properties of the architecture, and the loader rejects any config that tries to switch them off. A config file that says `emit_intentions_only = false` is not a different mandate. It is a different system, and this loader refuses to build it.

## Secrets are not policy

The loader reads two files, and the split between them is load-bearing:

- **`.env` carries secrets** — the paper API key id and secret. Twelve-factor style: never committed, never logged, never hashed into the intent. Secrets rotate on their own cadence, and nothing about rotation should change what the system was *told to do*.
- **`intent.toml` carries policy** — universe, limits, mandates. Versioned, reviewed, diffable, hashed. Policy changes go through pull requests; secrets never appear in diffs.

Here is the secrets half of the live artifact (`code/ch03/config_loader.py`), verbatim:

```python
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


class Secrets(BaseModel):
    """Paper-broker credentials. Frozen, never logged, never hashed.

    ``SecretStr`` masks the values on repr/str/log natively and
    idiomatically — the redaction lives in the *type*, not in a
    hand-rolled ``__repr__`` a future edit could forget to keep.
    The .env *parser* above stays hand-rolled on purpose:
    format-level strictness (duplicate keys, malformed lines) is a
    property of the FILE, and Pydantic validates VALUES. Split the
    jobs; keep both strict.
    """

    model_config = {"frozen": True, "extra": "forbid", "strict": True}

    api_key: SecretStr
    api_secret: SecretStr


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
```

Three decisions to notice. First, the parser is deliberately minimal — no `python-dotenv` dependency. `python-dotenv` is fine for general apps, but agentic risk dictates zero-leniency parsing, and a twenty-line strict parser you can read is more trustworthy than a lenient one you can't. Second, a duplicate key is an *error*, not last-wins: ambiguity in secrets is the kind of thing that becomes an incident. Third, secrets are a Pydantic model built on `SecretStr`, which masks the values on `repr`, `str`, and logging natively — no hand-rolled `__repr__` that a future edit could forget to keep. The `.env` *parser* stays hand-rolled on purpose: format-level strictness (duplicate keys, malformed lines) is a property of the file, and Pydantic validates values. Split the jobs; keep both strict.

## Policy, validated like a contract

The policy models use the same Pydantic v2 discipline as Chapter 4's tool contracts: frozen models, `extra="forbid"` everywhere, and `strict=True` on every model — a closed world. An unknown key is either a typo for a real control or an attempt to smuggle one in, and the loader treats both the same way: rejection. And the closed world is closed on *types* too. Pydantic coerces by default, so without `strict=True`, a TOML line reading `max_daily_loss_pct = "0.03"` — a string where a float belongs — would silently cast to `0.03` and the process would start. Strict mode makes that a refusal instead. (Plain TOML integers still load into float fields — a lossless numeric conversion, not a parse. The target of strict mode is string coercion, the smuggling vector: a string that *looks* like a number is not a number.) Here is the policy half, verbatim:

```python
# ---------------------------------------------------------------------------
# Policy models: Pydantic v2, frozen, extra=forbid, strict everywhere.
# A closed world — unknown keys are rejected (a typo for a real control
# or an attempt to smuggle one in), and wrong types are rejected too:
# strict=True disables Pydantic's default coercion, so a string where a
# float belongs is a refusal, not a silent cast.
# ---------------------------------------------------------------------------

class _FrozenBase(BaseModel):
    model_config = {"frozen": True, "extra": "forbid", "strict": True}


class DeskConfig(_FrozenBase):
    """Who this intent is for and what data it may look at."""

    # NOTE: pydantic's pattern uses the Rust regex engine, which has no \Z;
    # $ (end of text, multi-line off) is the portable anchor here.
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
```

Read the broker validator slowly, because it encodes the chapter's hardest lesson. It does three things: rejects non-HTTPS, rejects known production hosts by name, and then — the part that will annoy you — rejects any host that doesn't *say* it's paper. `https://broker.example.com` might be a perfectly good paper endpoint. The loader refuses it anyway. This is the "refuse to guess" principle: we would rather reject a legitimate paper URL (the operator fixes the URL and restarts) than trust a production one (the agent trades real money and nobody can undo it). Asymmetric costs demand asymmetric caution. A false refusal costs a restart. A false acceptance costs the firm.

The cross-field guards at the bottom catch a subtler class of error: individually-valid values that are jointly incoherent. A per-order cap above the per-symbol cap means a single order can breach the symbol limit — each number passed its own validator, and the *combination* is still wrong. A kill-switch threshold above the max daily loss means the halt trips after the damage the halt exists to prevent. These are the misconfigurations that survive every field-level check and detonate in production. The model validator exists because intent is a *system*, and systems fail at the joints.

## The version stamp

Validation produces a config. The loader then freezes it and stamps it:

```python
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
```

The `intent_hash` is the chapter's answer to a question every incident review eventually asks: *what was the system told to do?* Six months after a bad afternoon, "the config file on disk" is not an answer — the file has been edited forty times since. The hash, logged to the audit trail at startup (Chapter 9's evidence log carries it on every entry), pins the exact mandate to the exact run. And because the hash covers policy but never secrets, it can be logged, graphed, and compared freely: rotating the API key changes nothing about what the system was told to do, so the hash correctly stays identical. The test suite proves both directions — a leverage change moves the hash, a secret rotation doesn't. That is what "versioned intent" means operationally: not a git tag you hope someone applied, but a content hash the system computed about itself and then couldn't lie about, because it's frozen in a dataclass that raises `FrozenInstanceError` if anything tries.

One caveat, for the distributed future: the hash is pinned to the generating environment. JSON float rendering can vary across Python versions and platforms (`0.03` here, `0.030` there), so two machines hashing the same mandate could in principle disagree on the stamp. The guarantee in this chapter is per-environment stability — the same file, the same interpreter, the same hash, every time — which the test suite proves. Canonical cross-environment verification belongs to Chapter 9's audit trail, where the canonical form gets pinned down for exactly this reason.

Note the ordering inside `load_system_intent`: secrets are validated *before* policy is parsed. There is no point validating the mandate of a process that cannot authenticate, and more importantly, the failure you get first should be the most fundamental one. Error ordering is user-interface design for operators at 2am.

## The desk's mandate, on paper

Here is AlphaForge's actual intent file — the one the test suite loads. It is also the document a director could read:

```toml
[desk]
name = "alphaforge-paper"
data_mode = "synthetic"
universe = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]

[broker]
base_url = "https://paper-api.alpaca.markets"

[risk]
max_daily_loss_pct = 0.03
max_leverage = 1.0
long_only = true
per_symbol_max_notional = 25000
per_order_max_notional = 10000
execute_on_next_bar_open = true

[killswitch]
daily_drawdown_halt_pct = 0.03
max_orders_per_minute = 60

[strategies]
allowed = ["momentum_v1", "meanrev_v2"]
emit_intentions_only = true
```

Now replay the GME incident against this file. Somebody — a well-meaning researcher, a tired operator — adds `"GME"` to the universe and restarts the desk. The process does not start. It raises `ValidationError: unapproved symbol(s) in universe: ['GME']`, naming the key, at startup, in under a millisecond, with zero market exposure. The misconfiguration is caught where misconfigurations are cheap. That is the entire chapter in one error message.

The `data_mode = "synthetic"` line carries the book's provenance invariant: every bar this run touches is labeled SYNTHETIC. Flip it to `"real"` and the run declares its bars REAL. There is no third option and no default — `"live"` is rejected outright, because a provenance field that accepts free text will eventually accept a lie. When Chapter 7's market-data server stamps its quotes `SYNTHETIC`, it is honoring a declaration made here, in this file, before the first bar was ever read.

FIG: Reference Architecture — the Control, Execution, Data, and Evaluation planes for the AlphaForge/WealthForge trading edition. (Full layout spec: `figs/ch03-figspec.md`.)

## Drills

The test suite for this chapter (`test_config_loader.py`, 30 tests, all green) is written as attacks: missing files, missing secrets, malformed lines, duplicate keys, wrong types, type-coercion attempts, smuggled keys, unapproved symbols, production URLs, unmarked URLs, switched-off invariants, incoherent combinations. Green means every attack failed. Run it yourself: `~/workspace/book-rebuild/build-venv/bin/python -m pytest code/ch03/ -q`. Thirty dots, zero network calls, zero mandates smuggled.

**Exercise 1.** Add `max_position_age_hours` to `RiskConfig` (a position held longer must be flattened — a day-trading desk that wakes up holding overnight inventory has a different risk profile than it declared). Choose the bounds, write the failing test first, and decide: should an absent key fail closed? Defend your answer in three sentences.

**Exercise 2.** Secrets rotate; frozen intents don't. Design the rotation path: the API secret changes at noon, but the mandate is frozen and hashed. Do you rebuild the `SystemIntent`? Does the intent hash change? Where does the rotation get recorded so the audit trail stays continuous? Implement `reload_secrets` and write the test that proves the hash is untouched by rotation.

**Exercise 3.** The loader bans env-var overrides of policy. Steelman the other side: a researcher wants `ALPHAFORGE_UNIVERSE` for a quick experiment without committing a file. Write the strongest argument for allowing it, then write the audit-trail entry that a 2am env-var mandate change would have to produce to be acceptable. Which is cheaper — the env var, or the commit?

**Exercise 4.** WealthForge runs two tenants (Ch 6) on one process. Compose the designs: one `SystemIntent` per tenant, each hashed separately, each bound to its tenant session. What breaks if both tenants share one intent file? Write the test that proves the breakage — a config valid for tenant A that tenant B must never inherit.

**Exercise 5.** Add a `dry_run` mode to `DeskConfig`: when true, the loader still validates everything, but `load_system_intent` returns the intent with a `dry_run=True` marker and the process must refuse to authenticate (no secrets loaded). Where does the marker live — in the hash or out of it? What does your answer imply about whether dry-run is policy or metadata?

---

Intent is declared. The mandate is explicit, validated, frozen, and hashed; the secrets are separate and redacted; the paper-only invariant is enforced, not hoped for. But a mandate is still words in a file. The next chapter answers the question the mandate cannot answer by itself: when the model emits its JSON and reaches for the world, *what may cross the boundary?* Chapter 4 builds the tool contract — the schema standing at the gate, checking papers. And the papers it checks are the ones this chapter issued.
