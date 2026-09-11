"""Lab 1 answer key (Appendix B) — the reference QuotePipeline.

The wiring between the Ch 7 MCP market-data server and the Ch 9 evidence
spine: fetch -> validate -> label -> route -> acknowledge.

Validation order is load-bearing: SHAPE first (MalformedQuote), then
PROVENANCE (UnlabeledData — the lab's canonical failure), then SOURCE
TRUST (UntrustedSource), then FRESHNESS (stale is flagged, never dropped).
A quote that fails an earlier gate never reaches a later one, so a missing
price can never be misreported as an untrusted source.
"""

from __future__ import annotations

import time


class MalformedQuote(Exception):
    """The quote's shape is wrong: a required field is missing or wrongly
    typed. A judgment call was never reached — this is structural."""


class UnlabeledData(Exception):
    """The quote carries no usable provenance label. Unlabeled data is
    INADMISSIBLE: it is never emitted, never buffered, never 'fixed up'.
    A signal that read an unlabeled quote traded on data of unknown origin."""


class UntrustedSource(Exception):
    """The quote's source is not in the allowlist. The pipeline does not
    negotiate with sources it was not told to trust."""


_PROVENANCE_VALUES = ("REAL", "SYNTHETIC")


def _is_number(value) -> bool:
    # bool is a subclass of int; True is not a price.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class QuotePipeline:
    """fetch -> validate -> label -> route -> acknowledge."""

    def __init__(self, fetch, router, session, *, allowed_sources,
                 freshness_seconds: float = 60.0, clock=time.time):
        self._fetch = fetch
        self._router = router
        self._session = session
        self._allowed_sources = set(allowed_sources)
        self._freshness_seconds = float(freshness_seconds)
        self._clock = clock

    # -- validation ------------------------------------------------------
    def _check_shape(self, quote: dict) -> None:
        """Every required field present and correctly typed.

        Provenance is deliberately NOT checked here: a missing or empty
        provenance is the UnlabeledData gate's job, and misreporting it as
        a shape error would hide the lab's canonical failure behind the
        wrong name.
        """
        for field in ("symbol", "price", "source", "ts", "seq"):
            if field not in quote:
                raise MalformedQuote(f"missing required field: {field!r}")
        if not isinstance(quote["symbol"], str) or not quote["symbol"]:
            raise MalformedQuote(f"symbol must be a non-empty string, "
                                 f"got {quote['symbol']!r}")
        if not _is_number(quote["price"]):
            raise MalformedQuote(f"price must be numeric, "
                                 f"got {quote['price']!r}")
        if not isinstance(quote["source"], str) or not quote["source"]:
            raise MalformedQuote(f"source must be a non-empty string, "
                                 f"got {quote['source']!r}")
        if not _is_number(quote["ts"]):
            raise MalformedQuote(f"ts must be numeric, got {quote['ts']!r}")
        if not isinstance(quote["seq"], int) or isinstance(quote["seq"], bool):
            raise MalformedQuote(f"seq must be an integer, "
                                 f"got {quote['seq']!r}")

    def _validate(self, quote: dict) -> None:
        if not isinstance(quote, dict):
            raise MalformedQuote(f"quote must be a dict, "
                                 f"got {type(quote).__name__}")
        self._check_shape(quote)
        if quote.get("provenance") not in _PROVENANCE_VALUES:
            # Missing, empty, wrong type, or any other value: the data's
            # origin is unknown, so the data is inadmissible. Nothing is
            # emitted, nothing buffered, nothing "fixed up".
            raise UnlabeledData(
                f"quote for {quote.get('symbol')!r} carries no usable "
                f"provenance label (got {quote.get('provenance')!r}); "
                f"unlabeled data is inadmissible")
        if quote["source"] not in self._allowed_sources:
            raise UntrustedSource(
                f"source {quote['source']!r} is not in the allowlist")

    # -- the pipeline ----------------------------------------------------
    def ingest(self, quote: dict) -> dict:
        """Validate ONE raw quote and route it into evidence.

        Returns the recorded entry — the acknowledgement. The entry's
        ``seq`` and ``entry_hash`` ARE the receipt: a signal may act on a
        quote only if it can produce this receipt.
        """
        self._validate(quote)
        stale = (self._clock() - quote["ts"]) > self._freshness_seconds
        payload = dict(quote)  # extra fields (currency, as_of) pass through
        payload["tool"] = "get_quote"
        payload["quote_ts"] = quote["ts"]
        payload["stale"] = bool(stale)
        # Ch 9's taxonomy is CLOSED: a market quote arrived because a tool
        # was called, so it is a "tool_call" event with a rich payload —
        # never a new event type.
        return self._router.emit(self._session, "tool_call", payload)

    def ingest_batch(self, quotes: list[dict]) -> list[dict]:
        """Emit in ``seq`` order, not arrival order. The wire reorders; the
        evidence must not.

        Failures are NOT rolled back: quotes admitted before a bad one stay
        admitted (they were valid), and the refusal propagates to the
        caller. The ledger never contains a quote that failed validation.
        """
        ordered = sorted(quotes, key=lambda q: q["seq"])
        return [self.ingest(q) for q in ordered]
