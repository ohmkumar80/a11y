"""Egress-filtering forward proxy: the browser's ONLY way to the network (ADR 0007).

Why a proxy and not just request interception: Chromium follows redirects, opens WebSockets and
resolves DNS inside its own network stack, where page-level interception cannot see them. Routing
every connection through this proxy means each hop is judged here, and we connect to the very IP
we validated (no DNS-rebinding window). Anything that is not a public address, or not an allowed
port, gets 403 with ``X-A11y-Blocked: 1``.

Supports CONNECT (HTTPS, WebSockets over TLS) and plain HTTP forwarding with ``Connection: close``
(so one proxy connection never serves two different origins).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from urllib.parse import urlsplit

from a11y_core.ssrf import BlockedTarget, parse_url, resolve_public

log = logging.getLogger(__name__)
MAX_HEADER_BYTES = 64 * 1024
CONNECT_TIMEOUT_S = 10
BLOCK_BODY = b"Blocked by the scanner's network policy.\n"


class EgressProxy:
    def __init__(
        self, *, ports: tuple[int, ...], allow_hosts: frozenset[str] = frozenset()
    ) -> None:
        self.ports = ports
        self.allow_hosts = allow_hosts
        self.blocked: list[str] = []
        self._server: asyncio.AbstractServer | None = None
        self.port = 0

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    # -- helpers ------------------------------------------------------------------------------------
    async def _pin(self, host: str, port: int) -> list[str]:
        """Public IPs for host, or raise BlockedTarget. Port/host syntax checked first."""
        bracketed = f"[{host}]" if ":" in host else host  # IPv6 literals need brackets in a URL
        _, host, port = parse_url(f"http://{bracketed}:{port}/", ports=self.ports)
        return list(await resolve_public(host, port, allow_hosts=self.allow_hosts))

    async def _connect(self, ips: list[str], port: int):
        last: Exception | None = None
        for ip in ips:
            try:
                return await asyncio.wait_for(asyncio.open_connection(ip, port), CONNECT_TIMEOUT_S)
            except (OSError, TimeoutError) as e:
                last = e
        raise ConnectionError(str(last))

    @staticmethod
    async def _reply(
        w: asyncio.StreamWriter, status: str, extra: str = "", body: bytes = b""
    ) -> None:
        w.write(
            f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n{extra}\r\n".encode()
            + body
        )
        with contextlib.suppress(Exception):
            await w.drain()

    @staticmethod
    async def _pipe(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            while data := await r.read(65536):
                w.write(data)
                await w.drain()
        except (ConnectionError, asyncio.CancelledError, OSError):
            pass
        finally:
            with contextlib.suppress(Exception):
                w.close()

    async def _tunnel(self, cr, cw, ur, uw) -> None:
        a, b = asyncio.create_task(self._pipe(cr, uw)), asyncio.create_task(self._pipe(ur, cw))
        await asyncio.wait({a, b}, return_when=asyncio.FIRST_COMPLETED)
        for t in (a, b):
            t.cancel()
        for w in (cw, uw):
            with contextlib.suppress(Exception):
                w.close()

    async def _block(self, w: asyncio.StreamWriter, what: str, e: BlockedTarget) -> None:
        self.blocked.append(f"{e.code}: {what}")
        await self._reply(
            w, "403 Forbidden", "X-A11y-Blocked: 1\r\nContent-Type: text/plain\r\n", BLOCK_BODY
        )
        with contextlib.suppress(Exception):
            w.close()

    # -- connection handler -----------------------------------------------------------------------
    async def _handle(self, cr: asyncio.StreamReader, cw: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(cr.readuntil(b"\r\n\r\n"), 30)
        except (
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            TimeoutError,
            ConnectionError,
        ):
            cw.close()
            return
        if len(head) > MAX_HEADER_BYTES:
            await self._reply(cw, "431 Request Header Fields Too Large")
            cw.close()
            return
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, _ = lines[0].split(" ", 2)
        except ValueError:
            await self._reply(cw, "400 Bad Request")
            cw.close()
            return
        try:
            if method.upper() == "CONNECT":
                host, _, port_s = target.rpartition(":")
                host, port = host.strip("[]"), int(port_s)
                ips = await self._pin(host, port)
                ur, uw = await self._connect(ips, port)
                cw.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await cw.drain()
                await self._tunnel(cr, cw, ur, uw)
                return
            u = urlsplit(target)
            if u.scheme != "http" or not u.hostname:
                raise BlockedTarget("invalid_url", "unsupported proxy request")
            port = u.port or 80
            ips = await self._pin(u.hostname, port)
            ur, uw = await self._connect(ips, port)
            path = (u.path or "/") + (f"?{u.query}" if u.query else "")
            hdrs = [
                h
                for h in lines[1:]
                if h
                and h.split(":", 1)[0].lower()
                not in ("proxy-connection", "connection", "proxy-authorization")
            ]
            uw.write(
                f"{method} {path} HTTP/1.1\r\n".encode()
                + "\r\n".join([*hdrs, "Connection: close"]).encode("latin-1")
                + b"\r\n\r\n"
            )
            await uw.drain()
            await self._tunnel(cr, cw, ur, uw)
        except BlockedTarget as e:
            await self._block(cw, target[:120], e)
        except (ConnectionError, ValueError, OSError):
            with contextlib.suppress(Exception):
                await self._reply(cw, "502 Bad Gateway")
                cw.close()
