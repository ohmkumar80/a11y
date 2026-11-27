"""SSRF guard: every address class we promise to block, plus the sneaky encodings."""

import ipaddress

import pytest
from a11y_core.ssrf import BlockedTarget, check_url, ip_is_public, parse_url, resolve_public


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "127.1.2.3",
        "10.0.0.5",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104
        "224.0.0.1",
        "240.0.0.1",
        "255.255.255.255",
        "192.0.2.1",
        "198.51.100.7",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "fd00::1",
        "ff02::1",
        "2001:db8::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",  # IPv4-mapped
        "64:ff9b::7f00:1",
        "64:ff9b::a9fe:a9fe",  # NAT64 -> 127.0.0.1 / metadata
        "2002:7f00:0001::1",
        "2002:a9fe:a9fe::1",  # 6to4 -> 127.0.0.1 / metadata
        "fd00:ec2::254",  # AWS IPv6 metadata
    ],
)
def test_non_public_addresses_are_blocked(ip):
    assert ip_is_public(ipaddress.ip_address(ip)) is False


@pytest.mark.parametrize(
    "ip", ["93.184.216.34", "8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "::ffff:8.8.8.8"]
)
def test_public_addresses_are_allowed(ip):
    assert ip_is_public(ipaddress.ip_address(ip)) is True


@pytest.mark.parametrize(
    "url,code",
    [
        ("", "invalid_url"),
        ("example.com", "invalid_scheme"),
        ("ftp://example.com/x", "invalid_scheme"),
        ("file:///etc/passwd", "invalid_scheme"),
        ("gopher://example.com", "invalid_scheme"),
        ("javascript:alert(1)", "invalid_scheme"),
        ("http://user:pass@example.com", "credentials_in_url"),
        ("http://user@example.com", "credentials_in_url"),
        ("http://example.com:22/", "port_not_allowed"),
        ("http://example.com:6379/", "port_not_allowed"),
        ("http:///nohost", "invalid_url"),
        ("http://exa mple.com", "invalid_url"),
        ("http://example.com/\n", "invalid_url"),
        ("http://" + "a" * 3000, "invalid_url"),
    ],
)
def test_static_url_checks(url, code):
    with pytest.raises(BlockedTarget) as e:
        parse_url(url)
    assert e.value.code == code


def test_default_ports_and_idna():
    assert parse_url("https://Example.COM./path") == ("https", "example.com", 443)
    assert parse_url("http://example.com") == ("http", "example.com", 80)
    assert parse_url("https://bücher.example/")[1] == "xn--bcher-kva.example"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.1.2.3/",
        "http://192.168.0.1:8080/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fd00:ec2::254]/",
        "http://0.0.0.0/",
        "http://2130706433/",  # decimal form of 127.0.0.1
        "http://0x7f000001/",
        "http://017700000001/",  # hex / octal forms
        "http://127.1/",  # short form
    ],
)
async def test_internal_targets_are_refused_after_resolution(url):
    with pytest.raises(BlockedTarget) as e:
        await check_url(url)
    assert e.value.code == "private_address", url


async def test_one_bad_record_blocks_the_host(monkeypatch):
    """DNS answering with a public AND a private address (rebinding trick) is refused outright."""
    import socket

    async def fake(self, host, port, **kw):
        return [
            (socket.AF_INET, 0, 0, "", ("93.184.216.34", port)),
            (socket.AF_INET, 0, 0, "", ("10.0.0.7", port)),
        ]

    monkeypatch.setattr("asyncio.base_events.BaseEventLoop.getaddrinfo", fake)
    with pytest.raises(BlockedTarget) as e:
        await resolve_public("rebind.example", 80)
    assert e.value.code == "private_address"


async def test_public_resolution_passes_and_unknown_host_fails_cleanly(monkeypatch):
    import socket

    async def fake(self, host, port, **kw):
        if host == "nope.invalid":
            raise socket.gaierror
        return [(socket.AF_INET, 0, 0, "", ("93.184.216.34", port))]

    monkeypatch.setattr("asyncio.base_events.BaseEventLoop.getaddrinfo", fake)
    t = await check_url("https://example.com/page")
    assert (t.host, t.port, t.addresses) == ("example.com", 443, ("93.184.216.34",))
    with pytest.raises(BlockedTarget) as e:
        await check_url("https://nope.invalid")
    assert e.value.code == "dns_failed"


async def test_dev_allow_list_is_exact_and_blocked_in_production():
    allow = frozenset({"127.0.0.1"})
    assert (await resolve_public("127.0.0.1", 80, allow_hosts=allow)) == ("127.0.0.1",)
    with pytest.raises(BlockedTarget):  # only the listed host is exempt
        await resolve_public("10.0.0.1", 80, allow_hosts=allow)
    from a11y_core.settings import Settings

    with pytest.raises(ValueError, match="production"):
        Settings(
            env="production",
            jwt_secret="x" * 40,
            a11y_master_keys="k" * 44,
            scan_dev_allow_hosts="127.0.0.1",
        )
