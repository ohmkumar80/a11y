"""SSRF protection for everything that fetches a customer-supplied URL (PROJECT_PLAN 3.6).

Rules: http/https only; no credentials in the URL; allow-listed ports; the host must resolve ONLY to
globally routable addresses (private, loopback, link-local, CGNAT, cloud-metadata, multicast,
reserved and IPv6 transition addresses that embed such IPv4 addresses are all refused). If ANY
resolved address is bad the whole host is refused (defeats multi-record DNS rebinding). The same
check runs again for every redirect and sub-resource the browser requests.

Known limit (documented, ADR 0007 (egress proxy)): the browser resolves names itself, so a hostile DNS server could
answer differently at fetch time than at our check (TOCTOU). The authoritative control is network
egress policy: scan workers must run in a segment that cannot reach internal services. This module
is defence in depth and fails closed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_PORTS = (80, 443, 8080, 8443)
MAX_URL_LENGTH = 2048


class BlockedTarget(Exception):
    """The URL must not be fetched. ``code`` is stable for the UI; ``message`` is user-safe."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _embedded_v4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if ip.ipv4_mapped:
        return ip.ipv4_mapped
    if ip.sixtofour:
        return ip.sixtofour
    if ip.teredo:
        return ip.teredo[1]
    # NAT64 well-known prefix 64:ff9b::/96 embeds an IPv4 address in the low 32 bits.
    if ip in ipaddress.ip_network("64:ff9b::/96"):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def ip_is_public(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        inner = _embedded_v4(ip)
        if inner is not None and not ip_is_public(inner):
            return False
    return ip.is_global and not ip.is_multicast and not ip.is_unspecified


@dataclass(frozen=True)
class Target:
    url: str
    host: str
    port: int
    addresses: tuple[str, ...]


def parse_url(url: str, *, ports: tuple[int, ...] = DEFAULT_PORTS) -> tuple[str, str, int]:
    """Static checks only (no DNS). Returns (scheme, host, port)."""
    if not url or len(url) > MAX_URL_LENGTH or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise BlockedTarget("invalid_url", "Enter a full web address, like https://example.com.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise BlockedTarget("invalid_url", "That web address is not valid.") from None
    if parts.scheme not in ("http", "https"):
        raise BlockedTarget("invalid_scheme", "Only http and https addresses can be scanned.")
    if parts.username or parts.password:
        raise BlockedTarget(
            "credentials_in_url", "Remove the username and password from the address."
        )
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise BlockedTarget("invalid_url", "That web address has no host name.")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise BlockedTarget("invalid_url", "That host name is not valid.") from None
    port = port or (443 if parts.scheme == "https" else 80)
    if port not in ports:
        raise BlockedTarget(
            "port_not_allowed",
            f"Port {port} cannot be scanned. Allowed ports: {', '.join(map(str, ports))}.",
        )
    return parts.scheme, host, port


def dev_allow_hosts() -> frozenset[str]:
    """Hosts exempt from the private-address rule. DEV/TEST ONLY (refused in production)."""
    from a11y_core.settings import get_settings

    return frozenset(
        h.strip().lower() for h in get_settings().scan_dev_allow_hosts.split(",") if h.strip()
    )


async def resolve_public(
    host: str, port: int, *, allow_hosts: frozenset[str] | None = None
) -> tuple[str, ...]:
    """Resolve and require every address to be public. ``allow_hosts`` exists ONLY for local
    development and tests (refused when ENV=production by Settings)."""
    allow_private = host.lower() in (allow_hosts if allow_hosts is not None else dev_allow_hosts())
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        infos = [ip]
    except ValueError:
        try:
            raw = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            raise BlockedTarget(
                "dns_failed", f"We could not find {host}. Check the address."
            ) from None
        infos = [ipaddress.ip_address(r[4][0].split("%")[0]) for r in raw]
    if not infos:
        raise BlockedTarget("dns_failed", f"We could not find {host}.")
    if not allow_private and not all(ip_is_public(i) for i in infos):
        raise BlockedTarget(
            "private_address",
            "That address points to a private or internal network, which cannot be scanned.",
        )
    return tuple(sorted({str(i) for i in infos}))


async def check_url(
    url: str, *, ports: tuple[int, ...] = DEFAULT_PORTS, allow_hosts: frozenset[str] | None = None
) -> Target:
    _, host, port = parse_url(url, ports=ports)
    return Target(url, host, port, await resolve_public(host, port, allow_hosts=allow_hosts))
