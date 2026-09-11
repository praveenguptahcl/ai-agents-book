"""Lab 1 — Market-Data Evidence Pipeline (Chapter 20).

THE LAB IS RED ON PURPOSE. Read the chapter before touching this file.

What is GIVEN (the harness — do not modify):
  - ``quote_server`` : a real Ch 7 ``MCPServer`` (the AlphaForge market-data
    tool server), driven in-process through JSON-RPC envelopes.
  - ``fetch``       : ``fetch(symbol) -> dict`` — calls ``get_quote`` on that
    server and returns the parsed quote dict.
  - ``router``      : a real Ch 9 ``EvidenceRouter`` (the evidence spine).
  - ``session``     : a verified Ch 6 ``TenantSession`` for tenant
    ``"desk-alpha"`` — the proof of who is emitting, never a bare string.

What YOU build (in ``pipeline.py``, same directory — NOT shipped):
  - ``QuotePipeline`` — the wiring between the MCP client and the evidence
    router: fetch → validate → label → route → acknowledge.
  - ``MalformedQuote``, ``UnlabeledData``, ``UntrustedSource`` — the three
    named refusals.

The contract your pipeline must satisfy (every test below pins one clause):

  1. ``QuotePipeline(fetch, router, session, *, allowed_sources,
     freshness_seconds=60.0, clock=time.time)``
  2. ``ingest(quote) -> dict`` — validates ONE raw quote dict and routes it
     into evidence. Returns the recorded entry: the acknowledgement. The
     entry's ``seq`` and ``entry_hash`` ARE the receipt — a signal may act
     on a quote only if it can produce this receipt.
  3. ``ingest_batch(quotes) -> list[dict]`` — emits in ``seq`` order, not
     arrival order. The wire reorders; the evidence must not.
  4. A quote is valid only if it carries ALL of: ``symbol``, ``price``,
     ``provenance``, ``source``, ``ts``, ``seq``. Missing or wrongly-typed
     fields → ``MalformedQuote``. Nothing is emitted.
  5. ``provenance`` must be exactly ``"REAL"`` or ``"SYNTHETIC"``.
     Missing, empty, or any other value → ``UnlabeledData`` — and unlabeled
     data is INADMISSIBLE: it is never emitted, never buffered, never
     "fixed up". This is the lab's canonical failure: a signal that read
     an unlabeled quote is a signal that traded on data of unknown origin.
  6. ``source`` must be in ``allowed_sources`` → else ``UntrustedSource``.
     The pipeline does not negotiate with sources it was not told to trust.
  7. A quote older than ``freshness_seconds`` is STALE, not invalid: it is
     still emitted, but the routed payload carries ``"stale": True``. The
     desk needs to see that its data went quiet — silently dropping it
     would hide the outage.
  8. The event type is ``"tool_call"``. Ch 9's taxonomy is CLOSED — new
     domains do not get new event types; they get richer payloads. A market
     quote arrived *because a tool was called*, so ``tool_call`` it is.
     Emitting any other type fails this lab.
  9. The routed payload carries, at minimum: ``tool="get_quote"``,
     ``symbol``, ``price``, ``provenance``, ``source``, ``seq``,
     ``quote_ts``, ``stale``. Extra quote fields (``currency``, ``as_of``)
     pass through untouched.

Run it red first: ``python -m pytest test_lab1_data.py -q`` — then build.
"""

from __future__ import annotations

import json
import os
import sys
import time

import pytest

# -- cross-chapter imports: Lab 1 composes Ch 7 (transport) and Ch 9
# -- (evidence), with Ch 6 sessions as the authority proof. The lab proves
# -- the composition, so it imports the real machinery, not copies of it.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BOOK = os.path.dirname(os.path.dirname(_HERE))
for _ch in ("ch06", "ch07", "ch09"):
    _p = os.path.join(_BOOK, "code", _ch)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mcp_server import MCPServer  # noqa: E402  (Ch 7: the quote server)
from evidence import EvidenceRouter  # noqa: E402  (Ch 9: the evidence spine)
from tenant import TenantStore  # noqa: E402  (Ch 6: verified sessions)

# -- the student's module. NOT SHIPPED. This import is the lab being red. --
from pipeline import (  # noqa: E402
    MalformedQuote,
    QuotePipeline,
    UnlabeledData,
    UntrustedSource,
)

PROTOCOL_META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}
TENANT = "desk-alpha"
TRUSTED_SOURCE = "alphaforge-market-data"


# ---------------------------------------------------------------------------
# GIVEN: the harness
# ---------------------------------------------------------------------------

@pytest.fixture()
def server():
    """The real Ch 7 market-data server, driven in-process."""
    return MCPServer()


@pytest.fixture()
def fetch(server):
    """fetch(symbol) -> dict: one get_quote tool call through the MCP wire."""
    def _fetch(symbol: str) -> dict:
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_quote",
                "arguments": {"symbol": symbol},
                "_meta": dict(PROTOCOL_META),
            },
        }
        resp = server.handle_message(req)
        if resp is None or "error" in resp:
            raise AssertionError(f"harness: tools/call failed: {resp!r}")
        content = resp["result"]["content"]
        assert content and content[0]["type"] == "text"
        quote = json.loads(content[0]["text"])
        # The harness labels the wire source: the server is the source of
        # every quote that crosses this boundary. A hostile source can only
        # appear in the ADVERSARIAL fixtures below, never on the real wire.
        quote["source"] = TRUSTED_SOURCE
        quote["ts"] = time.time()
        quote["seq"] = 1
        return quote
    return _fetch


@pytest.fixture()
def router():
    import secrets
    return EvidenceRouter(secret=secrets.token_bytes(32))


@pytest.fixture()
def session():
    """A VERIFIED Ch 6 session — issued and signature-checked, not a string."""
    store = TenantStore(secret=b"lab-1-fixture-secret-32-bytes!!")
    store.register(TENANT, "Alpha desk")
    # Ch 6's scope vocabulary is read/submit/admin ("write" is not a scope).
    return store.verify(store.issue(TENANT, scopes=("read", "submit")))


@pytest.fixture()
def pipeline(fetch, router, session):
    return QuotePipeline(
        fetch=fetch,
        router=router,
        session=session,
        allowed_sources={TRUSTED_SOURCE},
        freshness_seconds=60.0,
    )


def _entries(router):
    return router.audit.read(TENANT)


# ---------------------------------------------------------------------------
# The tests: each pins one clause of the contract
# ---------------------------------------------------------------------------

def test_happy_path_emits_evidence(pipeline, fetch, router):
    """fetch → validate → label → route → acknowledge."""
    ack = pipeline.ingest(fetch("AAPL"))

    # The acknowledgement IS the receipt: seq + entry hash, or it is not
    # evidence and no signal may act on it.
    assert ack["seq"] == 0
    assert len(ack["entry_hash"]) == 64

    entries = _entries(router)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["event_type"] == "tool_call"  # closed taxonomy: no new types
    payload = entry["payload"]
    assert payload["tool"] == "get_quote"
    assert payload["symbol"] == "AAPL"
    assert payload["provenance"] == "SYNTHETIC"  # the fixture never passes
    assert payload["source"] == TRUSTED_SOURCE  #     as real
    assert payload["stale"] is False


def test_unlabeled_quote_rejected(pipeline, fetch, router):
    """The canonical failure: no provenance label → inadmissible."""
    quote = fetch("MSFT")
    del quote["provenance"]

    with pytest.raises(UnlabeledData):
        pipeline.ingest(quote)

    # Inadmissible means inadmissible: nothing buffered, nothing "fixed up",
    # nothing for a signal to find later.
    assert _entries(router) == []


def test_empty_provenance_is_still_unlabeled(pipeline, fetch, router):
    quote = fetch("MSFT")
    quote["provenance"] = ""
    with pytest.raises(UnlabeledData):
        pipeline.ingest(quote)
    assert _entries(router) == []


def test_stale_quote_flagged_not_dropped(pipeline, fetch, router):
    """A quiet feed is information. Dropping it would hide the outage."""
    quote = fetch("NVDA")
    quote["ts"] = time.time() - 3600.0  # an hour old against a 60s window

    ack = pipeline.ingest(quote)

    entries = _entries(router)
    assert len(entries) == 1
    assert entries[0]["payload"]["stale"] is True
    assert ack["payload"]["stale"] is True


def test_untrusted_source_rejected(pipeline, fetch, router):
    quote = fetch("SPY")
    quote["source"] = "totally-legit-feed"  # not in allowed_sources

    with pytest.raises(UntrustedSource):
        pipeline.ingest(quote)

    assert _entries(router) == []


def test_malformed_quote_rejected(pipeline, fetch, router):
    quote = fetch("QQQ")
    del quote["price"]  # shape violation, not a judgment call

    with pytest.raises(MalformedQuote):
        pipeline.ingest(quote)

    assert _entries(router) == []


def test_out_of_order_arrival_emitted_in_seq_order(pipeline, fetch, router):
    """The wire reorders. The evidence must not."""
    quotes = []
    for seq in (3, 1, 2):  # scrambled arrival
        q = fetch("AAPL")
        q["seq"] = seq
        quotes.append(q)

    acks = pipeline.ingest_batch(quotes)

    assert [a["payload"]["seq"] for a in acks] == [1, 2, 3]
    emitted = [e["payload"]["seq"] for e in _entries(router)]
    assert emitted == [1, 2, 3]


def test_mixed_batch_admits_only_the_valid(pipeline, fetch, router):
    """Adversarial batch: the good quote lands, the bad ones leave no trace."""
    good = fetch("AAPL")
    good["seq"] = 1
    bad = fetch("MSFT")
    bad["seq"] = 2
    del bad["provenance"]  # the canonical failure, smuggled into a batch

    with pytest.raises(UnlabeledData):
        pipeline.ingest_batch([good, bad])

    entries = _entries(router)
    assert len(entries) == 1
    assert entries[0]["payload"]["symbol"] == "AAPL"
    # And the inadmissible quote is nowhere — a downstream signal reading
    # this log can trust that every quote in it survived validation.
    assert all(e["payload"].get("provenance") in ("REAL", "SYNTHETIC")
               for e in entries)


def test_evidence_chain_survives_the_lab(pipeline, fetch, router):
    """Whatever the pipeline emitted, the Ch 9 chain still verifies."""
    for symbol in ("AAPL", "MSFT", "NVDA"):
        q = fetch(symbol)
        pipeline.ingest(q)
    ok, broken_at = router.verify()
    assert ok and broken_at is None
