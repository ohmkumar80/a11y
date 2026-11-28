"""Minimal ClamAV (clamd) client over TCP using the INSTREAM protocol. No dependency, easy to fake in tests.

Fail closed: any problem reaching or understanding the scanner is `ScannerUnavailable`, which callers must treat
as "not scanned" - never as "clean"."""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass

CHUNK = 64 * 1024


class ScannerUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ScanVerdict:
    clean: bool
    signature: str | None = None  # name of the detection, when infected


def parse_reply(reply: str) -> ScanVerdict:
    """clamd answers 'stream: OK', 'stream: <Signature> FOUND' or '... ERROR'."""
    reply = reply.strip("\x00\n ")
    if reply.endswith("OK"):
        return ScanVerdict(True)
    if reply.endswith("FOUND"):
        sig = reply.split(":", 1)[-1].removesuffix("FOUND").strip()
        return ScanVerdict(False, sig or "unknown")
    raise ScannerUnavailable(f"unexpected scanner reply: {reply[:80]!r}")


async def scan_bytes(data: bytes, *, host: str, port: int, timeout: float = 60) -> ScanVerdict:
    async def run() -> ScanVerdict:
        reader, writer = await asyncio.open_connection(host, port)
        try:
            writer.write(b"zINSTREAM\x00")
            for i in range(0, len(data), CHUNK):
                chunk = data[i : i + CHUNK]
                writer.write(struct.pack("!I", len(chunk)) + chunk)
            writer.write(struct.pack("!I", 0))
            await writer.drain()
            return parse_reply((await reader.read(4096)).decode("utf-8", "replace"))
        finally:
            writer.close()

    try:
        return await asyncio.wait_for(run(), timeout)
    except ScannerUnavailable:
        raise
    except (TimeoutError, OSError) as e:
        raise ScannerUnavailable(f"scanner not reachable: {type(e).__name__}") from e


async def ping(*, host: str, port: int, timeout: float = 5) -> bool:
    async def run() -> bool:
        reader, writer = await asyncio.open_connection(host, port)
        try:
            writer.write(b"zPING\x00")
            await writer.drain()
            return (await reader.read(64)).strip(b"\x00\n ") == b"PONG"
        finally:
            writer.close()

    try:
        return await asyncio.wait_for(run(), timeout)
    except (TimeoutError, OSError):
        return False
