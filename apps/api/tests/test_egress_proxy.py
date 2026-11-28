"""The egress proxy is the scanner's network boundary: test it directly, with raw sockets."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from a11y_web_audit.egress import EgressProxy


class Echo(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        body = f"hello host={self.headers.get('Host')} conn={self.headers.get('Connection')} path={self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def origin():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


async def talk(proxy_port: int, request: bytes) -> bytes:
    r, w = await asyncio.open_connection("127.0.0.1", proxy_port)
    w.write(request)
    await w.drain()
    data = b""
    try:
        data = await asyncio.wait_for(r.read(65536), 5)
    finally:
        w.close()
    return data


@pytest.fixture
async def strict():
    p = EgressProxy(ports=(80, 443, 8080, 8443))
    await p.start()
    yield p
    await p.stop()


@pytest.mark.parametrize(
    "target",
    [
        "127.0.0.1:80",
        "169.254.169.254:80",
        "[::1]:443",
        "10.0.0.5:443",
        "localhost:80",
        "192.168.1.1:8080",
    ],
)
async def test_connect_to_internal_addresses_is_refused(strict, target):
    out = await talk(strict.port, f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
    assert out.startswith(b"HTTP/1.1 403") and b"X-A11y-Blocked: 1" in out
    assert strict.blocked and "private_address" in strict.blocked[-1]


async def test_disallowed_ports_are_refused_even_on_public_hosts(strict):
    out = await talk(
        strict.port, b"CONNECT example.com:22 HTTP/1.1\r\nHost: example.com:22\r\n\r\n"
    )
    assert out.startswith(b"HTTP/1.1 403") and "port_not_allowed" in strict.blocked[-1]


async def test_plain_http_to_metadata_service_is_refused(strict):
    out = await talk(
        strict.port,
        b"GET http://169.254.169.254/latest/meta-data/ HTTP/1.1\r\nHost: 169.254.169.254\r\n\r\n",
    )
    assert out.startswith(b"HTTP/1.1 403") and b"X-A11y-Blocked: 1" in out


async def test_unsupported_requests_are_refused_or_rejected(strict):
    assert (await talk(strict.port, b"GET /relative HTTP/1.1\r\nHost: x\r\n\r\n")).startswith(
        b"HTTP/1.1 403"
    )
    assert (await talk(strict.port, b"nonsense\r\n\r\n")).startswith(b"HTTP/1.1 400")
    assert (await talk(strict.port, b"GET ftp://example.com/x HTTP/1.1\r\n\r\n")).startswith(
        b"HTTP/1.1 403"
    )


async def test_allow_list_lets_the_dev_host_through_and_forwards_http(origin):
    p = EgressProxy(ports=(origin,), allow_hosts=frozenset({"127.0.0.1"}))
    await p.start()
    try:
        out = await talk(
            p.port,
            f"GET http://127.0.0.1:{origin}/a/b?x=1 HTTP/1.1\r\nHost: 127.0.0.1:{origin}\r\nProxy-Connection: keep-alive\r\nConnection: keep-alive\r\n\r\n".encode(),
        )
        assert b" 200 " in out.split(b"\r\n")[0] and b"path=/a/b?x=1" in out
        assert b"conn=close" in out  # one proxy connection never serves two origins
    finally:
        await p.stop()


async def test_connect_tunnel_carries_bytes_both_ways(origin):
    p = EgressProxy(ports=(origin,), allow_hosts=frozenset({"127.0.0.1"}))
    await p.start()
    try:
        r, w = await asyncio.open_connection("127.0.0.1", p.port)
        w.write(f"CONNECT 127.0.0.1:{origin} HTTP/1.1\r\nHost: 127.0.0.1:{origin}\r\n\r\n".encode())
        await w.drain()
        assert (await r.readuntil(b"\r\n\r\n")).startswith(b"HTTP/1.1 200")
        w.write(b"GET /tunnel HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        await w.drain()
        # Read until the origin closes (we asked it to): one read() can return only the headers if the body arrives in a
        # later packet, which a slower network does.
        body = await asyncio.wait_for(r.read(), 5)
        assert b"path=/tunnel" in body
        w.close()
    finally:
        await p.stop()


async def test_proxy_connects_to_the_validated_ip_not_to_a_fresh_lookup(origin, monkeypatch):
    """DNS pinning: we resolve once, check, and connect to THAT address. A name that resolves to the
    loopback fixture is only reachable because it was explicitly allowed; the proxy uses the IP it saw."""
    import socket

    calls = []

    async def fake(self, host, port, **kw):
        calls.append(host)
        return [(socket.AF_INET, 0, 0, "", ("127.0.0.1", port))]

    monkeypatch.setattr("asyncio.base_events.BaseEventLoop.getaddrinfo", fake)
    p = EgressProxy(ports=(origin,), allow_hosts=frozenset({"pinned.test"}))
    await p.start()
    try:
        out = await talk(
            p.port,
            f"GET http://pinned.test:{origin}/ HTTP/1.1\r\nHost: pinned.test\r\n\r\n".encode(),
        )
        assert b" 200 " in out.split(b"\r\n")[0] and calls == ["pinned.test"]  # exactly one lookup
    finally:
        await p.stop()


async def test_rebinding_mixed_records_refused(monkeypatch):
    import socket

    async def fake(self, host, port, **kw):
        return [
            (socket.AF_INET, 0, 0, "", ("93.184.216.34", port)),
            (socket.AF_INET, 0, 0, "", ("127.0.0.1", port)),
        ]

    monkeypatch.setattr("asyncio.base_events.BaseEventLoop.getaddrinfo", fake)
    p = EgressProxy(ports=(80, 443))
    await p.start()
    try:
        out = await talk(
            p.port, b"CONNECT rebind.example:443 HTTP/1.1\r\nHost: rebind.example:443\r\n\r\n"
        )
        assert out.startswith(b"HTTP/1.1 403")
    finally:
        await p.stop()
