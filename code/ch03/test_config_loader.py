"""Chapter 3 tests — written as attacks on the intent loader.

Every test is an adversary: a missing file, a smuggled key, a production
URL, a loosened invariant. Green means every attack failed and the only
intents that load are the ones the desk actually declared.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from config_loader import (
    PRODUCTION_HOSTS,
    ConfigError,
    IntentConfig,
    SystemIntent,
    _intent_hash,
    load_secrets,
    load_system_intent,
)

VALID_TOML = """\
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
"""

VALID_ENV = """\
# Paper-broker credentials. Never committed, never logged.
ALPHAFORGE_PAPER_API_KEY=PK_TEST_123
ALPHAFORGE_PAPER_API_SECRET=SK_TEST_456
"""


@pytest.fixture()
def files(tmp_path: Path) -> tuple[Path, Path]:
    intent = tmp_path / "intent.toml"
    intent.write_text(VALID_TOML)
    env = tmp_path / ".env"
    env.write_text(VALID_ENV)
    return intent, env


def _rewrite(files: tuple[Path, Path], toml: str) -> tuple[Path, Path]:
    files[0].write_text(toml)
    return files


# -- the happy path ---------------------------------------------------------

def test_valid_intent_loads_and_freezes(files):
    intent, secrets = load_system_intent(*files)
    assert isinstance(intent, SystemIntent)
    assert intent.config.desk.name == "alphaforge-paper"
    assert intent.config.desk.universe == ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]
    assert secrets.api_key.get_secret_value() == "PK_TEST_123"
    # Frozen: the mandate cannot be edited after load.
    with pytest.raises(dataclasses.FrozenInstanceError):
        intent.intent_hash = "forged"  # type: ignore[misc]


def test_intent_hash_is_stable_and_versioned(files):
    first, _ = load_system_intent(*files)
    second, _ = load_system_intent(*files)
    assert first.intent_hash == second.intent_hash
    assert len(first.intent_hash) == 64
    # A policy change changes the version stamp...
    changed = _rewrite(files, VALID_TOML.replace("max_leverage = 1.0",
                                                 "max_leverage = 1.5"))
    third, _ = load_system_intent(*changed)
    assert third.intent_hash != first.intent_hash
    # ...but a secret rotation does NOT: the hash covers policy,
    # never credentials. (Restore the original policy first.)
    _rewrite(files, VALID_TOML)
    env2 = files[1]
    env2.write_text(VALID_ENV.replace("PK_TEST_123", "PK_ROTATED_999"))
    fourth, _ = load_system_intent(files[0], env2)
    assert fourth.intent_hash == first.intent_hash


def test_secrets_repr_is_redacted(files):
    _, secrets = load_system_intent(*files)
    # SecretStr masks natively: the redaction lives in the type, not in
    # a hand-rolled __repr__ a future edit could forget.
    assert isinstance(secrets.api_key, SecretStr)
    assert isinstance(secrets.api_secret, SecretStr)
    assert "PK_TEST_123" not in repr(secrets)
    assert "SK_TEST_456" not in repr(secrets)
    assert "PK_TEST_123" not in str(secrets)
    assert "SK_TEST_456" not in str(secrets)


# -- missing pieces: refuse to start ----------------------------------------

def test_missing_env_file_is_a_clear_refusal(tmp_path):
    intent = tmp_path / "intent.toml"
    intent.write_text(VALID_TOML)
    with pytest.raises(ConfigError, match=r"\.env file not found"):
        load_system_intent(intent, tmp_path / "no-such.env")


def test_missing_intent_file_is_a_clear_refusal(tmp_path):
    env = tmp_path / ".env"
    env.write_text(VALID_ENV)
    with pytest.raises(ConfigError, match="intent file not found"):
        load_system_intent(tmp_path / "no-such.toml", env)


def test_missing_secret_key_names_the_key(files):
    files[1].write_text("ALPHAFORGE_PAPER_API_KEY=PK_TEST_123\n")
    with pytest.raises(ConfigError,
                       match="ALPHAFORGE_PAPER_API_SECRET"):
        load_secrets(files[1])


def test_empty_secret_is_missing(files):
    files[1].write_text(
        "ALPHAFORGE_PAPER_API_KEY=\n"
        "ALPHAFORGE_PAPER_API_SECRET=SK_TEST_456\n"
    )
    with pytest.raises(ConfigError, match="ALPHAFORGE_PAPER_API_KEY"):
        load_secrets(files[1])


def test_malformed_dotenv_line_refuses(files):
    files[1].write_text("THIS LINE HAS NO EQUALS\n")
    with pytest.raises(ConfigError, match="malformed line"):
        load_secrets(files[1])


def test_duplicate_dotenv_key_refuses(files):
    files[1].write_text(VALID_ENV + "ALPHAFORGE_PAPER_API_KEY=OTHER\n")
    with pytest.raises(ConfigError, match="duplicate key"):
        load_secrets(files[1])


def test_dotenv_supports_export_comments_and_quotes(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        'export ALPHAFORGE_PAPER_API_KEY="QUOTED KEY"\n'
        "ALPHAFORGE_PAPER_API_SECRET='single quoted'\n"
    )
    secrets = load_secrets(env)
    assert secrets.api_key.get_secret_value() == "QUOTED KEY"
    assert secrets.api_secret.get_secret_value() == "single quoted"


# -- malformed policy: the exact key is named ---------------------------------

def test_wrong_type_names_the_key(files):
    bad = _rewrite(files, VALID_TOML.replace("max_leverage = 1.0",
                                             'max_leverage = "high"'))
    with pytest.raises(ValidationError, match="max_leverage"):
        load_system_intent(*bad)


def test_string_where_float_belongs_rejected_strict(files):
    # Pydantic coerces by default; strict=True makes the closed world
    # closed on types too. TOML has native floats — the loader demands
    # them. A string that *looks* like a number is still a refusal.
    bad = _rewrite(files, VALID_TOML.replace("max_daily_loss_pct = 0.03",
                                             'max_daily_loss_pct = "0.03"'))
    with pytest.raises(ValidationError, match="max_daily_loss_pct"):
        load_system_intent(*bad)


def test_bool_as_string_rejected_strict(files):
    bad = _rewrite(files, VALID_TOML.replace(
        "execute_on_next_bar_open = true",
        'execute_on_next_bar_open = "true"'))
    with pytest.raises(ValidationError, match="execute_on_next_bar_open"):
        load_system_intent(*bad)


def test_leverage_above_ceiling_rejected(files):
    bad = _rewrite(files, VALID_TOML.replace("max_leverage = 1.0",
                                             "max_leverage = 3.0"))
    with pytest.raises(ValidationError, match="max_leverage"):
        load_system_intent(*bad)


def test_unknown_key_rejected_closed_world(files):
    bad = _rewrite(files, VALID_TOML.replace(
        'name = "alphaforge-paper"',
        'name = "alphaforge-paper"\nevil = true'))
    with pytest.raises(ValidationError, match="evil"):
        load_system_intent(*bad)


def test_unknown_top_level_section_rejected(files):
    bad = _rewrite(files, VALID_TOML + "\n[backdoor]\nopen = true\n")
    with pytest.raises(ValidationError, match="backdoor"):
        load_system_intent(*bad)


def test_unapproved_symbol_caught_at_startup(files):
    bad = _rewrite(files, VALID_TOML.replace('"QQQ"', '"QQQ", "GME"'))
    with pytest.raises(ValidationError, match="GME"):
        load_system_intent(*bad)


def test_duplicate_symbols_rejected(files):
    bad = _rewrite(files, VALID_TOML.replace('"QQQ"', '"QQQ", "aapl"'))
    with pytest.raises(ValidationError, match="duplicate"):
        load_system_intent(*bad)


def test_bad_data_mode_rejected(files):
    bad = _rewrite(files, VALID_TOML.replace('data_mode = "synthetic"',
                                             'data_mode = "live"'))
    with pytest.raises(ValidationError, match="data_mode"):
        load_system_intent(*bad)


def test_bad_strategy_id_rejected(files):
    bad = _rewrite(files, VALID_TOML.replace('"momentum_v1"',
                                             '"Momentum-V1!!"'))
    with pytest.raises(ValidationError, match="machine name"):
        load_system_intent(*bad)


def test_invalid_toml_is_a_config_error(files):
    files[0].write_text("this is [not valid toml")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_system_intent(*files)


# -- paper-only invariant ------------------------------------------------------

def test_production_broker_url_rejected(files):
    for host in PRODUCTION_HOSTS:
        bad = _rewrite(
            files,
            VALID_TOML.replace("https://paper-api.alpaca.markets",
                               f"https://{host}"),
        )
        with pytest.raises(ValidationError, match="production"):
            load_system_intent(*bad)


def test_unmarked_broker_url_rejected_refuses_to_guess(files):
    bad = _rewrite(files, VALID_TOML.replace(
        "https://paper-api.alpaca.markets", "https://broker.example.com"))
    with pytest.raises(ValidationError, match="no paper/sandbox/demo marker"):
        load_system_intent(*bad)


def test_non_https_broker_url_rejected(files):
    bad = _rewrite(files, VALID_TOML.replace(
        "https://paper-api.alpaca.markets", "http://paper-api.alpaca.markets"))
    with pytest.raises(ValidationError, match="https"):
        load_system_intent(*bad)


# -- structural invariants are not configurable ---------------------------------

def test_t_plus_one_cannot_be_switched_off(files):
    bad = _rewrite(files, VALID_TOML.replace(
        "execute_on_next_bar_open = true", "execute_on_next_bar_open = false"))
    with pytest.raises(ValidationError, match="t\\+1"):
        load_system_intent(*bad)


def test_intentions_only_cannot_be_switched_off(files):
    bad = _rewrite(files, VALID_TOML.replace("emit_intentions_only = true",
                                             "emit_intentions_only = false"))
    with pytest.raises(ValidationError, match="intentions"):
        load_system_intent(*bad)


# -- cross-field guards ---------------------------------------------------------

def test_per_order_above_per_symbol_rejected(files):
    bad = _rewrite(files, VALID_TOML.replace(
        "per_order_max_notional = 10000", "per_order_max_notional = 99999"))
    with pytest.raises(ValidationError, match="per_order_max_notional"):
        load_system_intent(*bad)


def test_killswitch_above_loss_limit_rejected(files):
    bad = _rewrite(files, VALID_TOML.replace(
        "daily_drawdown_halt_pct = 0.03", "daily_drawdown_halt_pct = 0.50"))
    with pytest.raises(ValidationError, match="decoration"):
        load_system_intent(*bad)


# -- the hash answers "what was the system told to do?" --------------------------

def test_hash_covers_policy_not_secrets(files):
    intent, _ = load_system_intent(*files)
    expected = hashlib.sha256(
        json.dumps(intent.config.model_dump(mode="json"),
                   sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert intent.intent_hash == expected
    assert _intent_hash(intent.config) == expected
    # The canonical form must not contain credential material.
    canonical = json.dumps(intent.config.model_dump(mode="json"),
                           sort_keys=True)
    assert "PK_TEST_123" not in canonical


def test_intent_config_itself_is_frozen(files):
    intent, _ = load_system_intent(*files)
    # Note the two different "frozen" exception types in this codebase:
    # Pydantic v2 raises pydantic_core.ValidationError on assignment to a
    # frozen *model* (config), while the plain SystemIntent *dataclass*
    # raises dataclasses.FrozenInstanceError. Both mean "you may not edit
    # the mandate after load" — the type differs because the mechanism
    # differs, not because the guarantee does.
    with pytest.raises(ValidationError):
        intent.config.risk.max_leverage = 99.0  # type: ignore[misc]
