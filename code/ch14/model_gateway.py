"""Model gateway: route, fall back, cache, and account for every model call.

Ch 5 taught the provider call as a single disciplined act; this module runs
the call as a *fleet decision*. Three jobs:

  - ROUTING: task classes map to models. Summarization does not need the
    flagship model; grading a trading thesis does. Small-vs-large routing
    is a cost control with security side effects (fewer capabilities
    invoked per task means less to verify).
  - FALLBACK: providers have outages. When the primary raises
    ``ProviderOutage``, the gateway walks an ordered fallback list for the
    same task class. An agent that cannot reach its model must degrade to a
    weaker model or halt — never to an unverified guess.
  - CACHING: identical canonical requests hit the cache instead of the
    provider. The cache is namespaced by Ch 3's intent hash: rotate the
    system's intent and every cached answer is suspect, because the
    question was asked by a different system.

Every call is cost-accounted into a ledger. Providers are injected
callables returning ``ProviderResult`` — the seam is honest, and the
``ProviderOutage`` / ``ProviderContractViolation`` exceptions are raised by
the test doubles, which is exactly how production adapters behave.

Token counts come from the provider's reported usage (as real LLM APIs
do), not from a local estimator. A provider that will not report usage
cannot be cost-accounted, and a call that cannot be accounted is refused:
``ProviderContractViolation``.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass


class ProviderOutage(RuntimeError):
    """The provider is unreachable. The gateway may try a fallback."""


class ProviderContractViolation(RuntimeError):
    """The provider answered but broke the usage-reporting contract."""


@dataclass(frozen=True)
class ProviderResult:
    """What a provider must return for the gateway to accept the call."""
    text: str
    model: str
    tokens_in: int
    tokens_out: int


@dataclass(frozen=True)
class GatewayResult:
    text: str
    model: str
    cached: bool
    cost_usd: float


def _canonical_request(request: dict) -> str:
    """Deterministic serialization: identical questions hash identically."""
    return json.dumps(request, sort_keys=True, separators=(",", ":"),
                      default=str)


class ModelGateway:
    """Routes model calls, survives provider outages, caches, accounts."""

    def __init__(self, routes: dict[str, str],
                 providers: dict[str, object],
                 prices_per_1k: dict[str, tuple[float, float]],
                 fallbacks: dict[str, list[str]] | None = None,
                 intent_hash: str = "") -> None:
        """
        routes: task_class -> model id (e.g. "summarize" -> "small-1").
        providers: model id -> callable(request) -> ProviderResult.
                   May raise ProviderOutage.
        prices_per_1k: model id -> (usd_per_1k_input, usd_per_1k_output).
        fallbacks: model id -> ordered list of substitute model ids.
        intent_hash: Ch 3's version stamp; the cache is namespaced by it.
        """
        self._routes = dict(routes)
        self._providers = dict(providers)
        self._prices = dict(prices_per_1k)
        self._fallbacks = {k: list(v) for k, v in (fallbacks or {}).items()}
        self._intent_hash = intent_hash
        self._cache: dict[tuple[str, str], GatewayResult] = {}
        self._ledger: list[dict] = []

    # -- routing ------------------------------------------------------------
    def route(self, task_class: str) -> str:
        """Which model serves this task class. Unknown classes fail closed."""
        try:
            return self._routes[task_class]
        except KeyError:
            raise KeyError(
                f"no route for task class {task_class!r}: refusing to guess "
                f"which model should answer") from None

    # -- the call -----------------------------------------------------------
    def complete(self, task_class: str, request: dict) -> GatewayResult:
        """One accounted, cached, fallback-capable model call."""
        model = self.route(task_class)
        key = (self._intent_hash, hashlib.sha256(
            _canonical_request(request).encode("utf-8")).hexdigest())
        if key in self._cache:
            hit = self._cache[key]
            return GatewayResult(text=hit.text, model=hit.model,
                                 cached=True, cost_usd=0.0)
        candidates = [model] + self._fallbacks.get(model, [])
        last_outage: ProviderOutage | None = None
        for candidate in candidates:
            provider = self._providers.get(candidate)
            if provider is None:
                continue  # misconfigured fallback entry: skip, don't die
            try:
                result = provider(copy.deepcopy(request))
            except ProviderOutage as exc:
                last_outage = exc
                continue  # try the next fallback
            result = self._check_contract(candidate, result)
            cost = self._price(candidate, result)
            self._ledger.append({
                "task_class": task_class, "model": candidate,
                "tokens_in": result.tokens_in, "tokens_out": result.tokens_out,
                "cost_usd": cost, "fallback": candidate != model,
            })
            answer = GatewayResult(text=result.text, model=candidate,
                                   cached=False, cost_usd=cost)
            self._cache[key] = answer
            return answer
        raise ProviderOutage(
            f"all providers for {model!r} are down: {last_outage!r}")

    # -- accounting ---------------------------------------------------------
    def _check_contract(self, model: str, result: object) -> ProviderResult:
        if not isinstance(result, ProviderResult):
            raise ProviderContractViolation(
                f"provider for {model!r} did not return a ProviderResult")
        if result.tokens_in < 0 or result.tokens_out < 0:
            raise ProviderContractViolation(
                f"provider for {model!r} reported negative usage")
        return result

    def _price(self, model: str, result: ProviderResult) -> float:
        try:
            in_p, out_p = self._prices[model]
        except KeyError:
            raise ProviderContractViolation(
                f"no price for model {model!r}: refusing unpriced calls"
            ) from None
        return result.tokens_in / 1000 * in_p + result.tokens_out / 1000 * out_p

    def total_cost_usd(self) -> float:
        return sum(r["cost_usd"] for r in self._ledger)

    def ledger(self) -> list[dict]:
        return [dict(r) for r in self._ledger]

    # -- intent rotation ----------------------------------------------------
    def rotate_intent(self, new_intent_hash: str) -> None:
        """A new system intent invalidates every cached answer.

        The old answers were produced for a different system's questions.
        The ledger survives rotation — money spent is money spent.
        """
        self._intent_hash = new_intent_hash
        self._cache.clear()
