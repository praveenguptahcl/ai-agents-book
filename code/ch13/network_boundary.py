"""The network boundary: every outbound HTTP request passes a gate.

Chapter 12 filtered the model's WORDS. This module gates the WORLD those
words can touch. An agent that decides to exfiltrate meets the allowlist,
not the policy doc.

The gate runs five checks in order and refuses LOUDLY (named exceptions)
at the first failure:

1. **Scheme.** http/https only. No ``file://``, no ``gopher://``, no
   custom schemes smuggled through a tool that "just fetches a URL".
2. **Userinfo.** ``user:pass@host`` is refused outright. Credentials in
   URLs leak into logs, and the userinfo slot is a classic SSRF smuggling
   position.
3. **Allowlist, deny by default.** The host must match an entry. Entries
   are exact hosts or ``".suffix"`` wildcards: ``".polygon.io"`` matches
   ``api.polygon.io`` but NOT ``polygon.io.evil.com`` — the leading dot
   is load-bearing.
4. **Resolve-then-check.** The hostname is resolved to IPs (injectable
   resolver, so tests never touch DNS), and EVERY resolved address is
   checked against blocked ranges: loopback, RFC1918 private, link-local
   (``169.254.0.0/16`` — the cloud-metadata range), multicast,
   unspecified, reserved. Checking the ADDRESS, not the NAME, defeats DNS
   rebinding.
5. **Redirects, re-checked per hop.** Redirects are followed MANUALLY —
   never delegated to the HTTP client's auto-redirect. Every hop re-runs
   the full gate. A 302 from an allowlisted host to 169.254.169.254 dies
   at hop two.

Timeouts are capped: the agent may ask for less, never more.

Transport seam: the bytes go through an injected ``transport`` callable
``(method, url, timeout) -> TransportResponse``. In production this wraps
urllib/requests with auto-redirect DISABLED; in tests it is a fake that
replays canned chains. The boundary is transport-agnostic.

HONEST RESIDUAL — the resolve-then-fetch TOCTOU: DNS can change between
the check and the connect, so a hostile resolver can still rebind after
we looked. This module returns the checked addresses in the verdict so a
production deployment can PIN the connection to them (custom connector /
Happy-Eyeballs with a pinned first address) or re-check at connect time.
What this module guarantees: no request is ever SENT to an unchecked
address. What it does not guarantee: that the address is still the same
when the SYN packet leaves. Name the residual; pin the IP.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse


# --------------------------------------------------------------------------
# Exceptions: every refusal is named, so the trace says WHY it stopped.
# --------------------------------------------------------------------------


class EgressError(Exception):
    """Base: the network boundary refused something on purpose."""


class SchemeDenied(EgressError):
    """The URL scheme is not http/https. Refused."""


class UserinfoDenied(EgressError):
    """The URL carries userinfo (user:pass@host). Refused."""


class HostNotAllowlisted(EgressError):
    """Deny by default: the host matches no allowlist entry. Refused."""


class SSRFAddressBlocked(EgressError):
    """A resolved IP falls in a blocked range (metadata/private/loopback).

    Raised even when the HOSTNAME is allowlisted — DNS rebinding means the
    name is not the address. The message names the offending IP and the
    category it matched, so the trace is auditable.
    """


class RedirectBlocked(EgressError):
    """A redirect hop failed the gate. The chain stops here."""


class TooManyRedirects(EgressError):
    """The redirect chain exceeded the hop limit. Refused."""


# --------------------------------------------------------------------------
# Transport seam
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TransportResponse:
    """What the transport layer returned. Headers keyed lowercase."""

    status_code: int
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class GateVerdict:
    """The auditable record of one gated request.

    ``resolved_ips`` carries the addresses that were actually checked, so a
    production caller can pin the connection to them (see the module
    docstring's TOCTOU residual). ``hops`` records every URL the chain
    visited, in order.
    """

    allowed: bool
    final_url: str
    status_code: int
    hops: tuple[str, ...]
    resolved_ips: tuple[str, ...]
    response: TransportResponse | None = None
    reason: str = ""


Transport = Callable[[str, str, float], TransportResponse]
Resolver = Callable[[str], list[str]]

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def _default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def _address_category(ip: str) -> str | None:
    """Return the blocked-range category for an IP, or None if routable."""
    addr = ipaddress.ip_address(ip)
    if addr.is_loopback:
        return "loopback"
    if addr.is_link_local:
        # Covers 169.254.0.0/16 — the cloud metadata range.
        return "link-local (cloud metadata range)"
    if addr.is_private:
        return "private (RFC1918)"
    if addr.is_multicast:
        return "multicast"
    if addr.is_unspecified:
        return "unspecified"
    if addr.is_reserved:
        return "reserved"
    return None


class NetworkBoundary:
    """The egress gate. Construct once per agent; share nothing mutable."""

    def __init__(
        self,
        *,
        allowlist: Iterable[str],
        transport: Transport,
        resolver: Resolver | None = None,
        timeout_ceiling: float = 10.0,
        max_redirects: int = 5,
        allowed_ports: frozenset[int] = frozenset({80, 443}),
    ) -> None:
        self._allowlist = tuple(a.lower() for a in allowlist)
        self._transport = transport
        self._resolver = resolver or _default_resolver
        self._timeout_ceiling = timeout_ceiling
        self._max_redirects = max_redirects
        self._allowed_ports = allowed_ports

    # -- the gate ------------------------------------------------------

    def _host_allowed(self, host: str) -> bool:
        host = host.lower()
        for entry in self._allowlist:
            if entry.startswith("."):
                if host.endswith(entry) and host != entry[1:]:
                    return True
            elif host == entry:
                return True
        return False

    def _check_resolved_ips(self, host: str) -> tuple[str, ...]:
        """Resolve the host and refuse any address in a blocked range.

        Every resolved IP is checked — a hostname that resolves to one
        public and one private address is still refused. The name is not
        the address; DNS rebinding is exactly this gap.

        IP literals skip DNS entirely and are checked directly: there is
        nothing to rebind, and asking a resolver about a literal would
        let a lying or confused resolver launder it.
        """
        try:
            ipaddress.ip_address(host)
            ips = [host]
        except ValueError:
            ips = self._resolver(host)
        if not ips:
            raise SSRFAddressBlocked(f"{host}: resolved to no addresses")
        for ip in ips:
            category = _address_category(ip)
            if category is not None:
                raise SSRFAddressBlocked(
                    f"{host} resolved to {ip} ({category}); "
                    "refusing: the address, not the name, is the trust unit"
                )
        return tuple(ips)

    def _gate_one_url(self, url: str) -> tuple[str, str, tuple[str, ...]]:
        """Run checks 1-4 on a single URL. Returns (host, url, ips)."""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise SchemeDenied(f"scheme {parsed.scheme!r} is not http/https")
        if parsed.username or parsed.password:
            raise UserinfoDenied("userinfo in URL is never permitted")
        host = (parsed.hostname or "").lower()
        if not host:
            raise HostNotAllowlisted(f"no host in URL {url!r}")
        if not self._host_allowed(host):
            raise HostNotAllowlisted(
                f"{host!r} matches no allowlist entry (deny by default)"
            )
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in self._allowed_ports:
            raise HostNotAllowlisted(f"port {port} is not an allowed port")
        ips = self._check_resolved_ips(host)
        return host, url, ips

    # -- the request ---------------------------------------------------

    def request(
        self, method: str, url: str, timeout: float | None = None
    ) -> GateVerdict:
        """Fetch through the gate, following redirects manually.

        Every redirect hop re-runs the full gate. Returns a GateVerdict
        recording the chain; raises a named EgressError on any refusal.
        """
        timeout = min(
            self._timeout_ceiling if timeout is None else timeout,
            self._timeout_ceiling,
        )
        hops: list[str] = []
        checked_ips: list[str] = []
        current = url
        for step in range(self._max_redirects + 1):
            # Gate exactly once per hop, at the top of the loop. A
            # pre-validation of the next URL at the bottom of the loop
            # would double-gate the same URL — a TOCTOU gap where a DNS
            # rebind between the two checks surfaces a bare
            # SSRFAddressBlocked instead of the RedirectBlocked the
            # named-refusal trace promises. Redirect hops (step > 0)
            # wrap gate failures as RedirectBlocked.
            try:
                _, checked_url, ips = self._gate_one_url(current)
            except EgressError as exc:
                if step > 0:
                    raise RedirectBlocked(
                        f"redirect hop {len(hops)} -> {current!r} "
                        f"failed the gate: {exc}"
                    ) from exc
                raise
            hops.append(checked_url)
            checked_ips.extend(ips)
            resp = self._transport(method.upper(), checked_url, timeout)
            if resp.status_code not in _REDIRECT_STATUSES:
                return GateVerdict(
                    allowed=True,
                    final_url=checked_url,
                    status_code=resp.status_code,
                    hops=tuple(hops),
                    resolved_ips=tuple(checked_ips),
                    response=resp,
                )
            location = resp.headers.get("location", "")
            if not location:
                raise RedirectBlocked(
                    f"{checked_url} returned {resp.status_code} with no Location"
                )
            nxt = urljoin(checked_url, location)
            # 301/302/303 rewrite to GET per RFC 7231; 307/308 keep method.
            if resp.status_code in (301, 302, 303):
                method = "GET"
            current = nxt
        raise TooManyRedirects(
            f"exceeded {self._max_redirects} redirect hops from {url!r}"
        )
