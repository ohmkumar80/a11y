"""Synthetic canaries (PROJECT_PLAN 3.15): small jobs that prove the parts customers depend on still work, before a
customer finds out. Each canary runs on a schedule in the worker that owns the capability and records its result in
Redis (``canary:<name>``); the read-only operations page shows them and calls a missing or old result what it is: stale.

* ``web_scan``  a headless browser loads a known-bad snippet, the three engines find it, the normaliser merges it, and a
  fixed version is clean. No network, no credits, nothing stored.
* ``docs_pdf``  a sample report becomes an accessible PDF and passes the PDF/UA check.
* ``email_smtp`` the mail server accepts a connection and a login. Nothing is sent."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis

from .celery_app import celery_app
from .settings import get_settings

log = logging.getLogger(__name__)
KEEP_SECONDS = 6 * 3600
STALE_FACTOR = 2.5  # a canary that has not reported for this many intervals is stale


@dataclass(frozen=True)
class Canary:
    key: str
    label: str
    interval: int  # seconds between runs


CANARIES: dict[str, Canary] = {
    c.key: c
    for c in (
        Canary("web_scan", "Browser and scan engines", 900),
        Canary("docs_pdf", "Accessible PDF generation and the PDF/UA check", 1800),
        Canary("email_smtp", "Mail server connection", 900),
    )
}


def _redis() -> Redis:
    return Redis.from_url(get_settings().redis_url)


async def record(name: str, ok: bool, detail: str = "", duration_ms: int = 0) -> None:
    r = _redis()
    try:
        await r.set(
            f"canary:{name}",
            json.dumps(
                {
                    "ok": ok,
                    "at": datetime.now(UTC).isoformat(),
                    "detail": detail[:300],
                    "duration_ms": duration_ms,
                }
            ),
            ex=KEEP_SECONDS,
        )
    finally:
        await r.aclose()


async def run_timed(name: str, check) -> bool:
    """Run ``check`` (an async callable returning a short detail string), record the outcome and never raise."""
    t0 = time.perf_counter()
    try:
        detail = await check()
        ok = True
    except Exception as e:  # noqa: BLE001 - a canary reports failure, it does not crash
        detail, ok = f"{type(e).__name__}: {str(e)[:200]}", False
        log.warning("canary %s failed: %s", name, detail)
    await record(name, ok, detail, int((time.perf_counter() - t0) * 1000))
    return ok


async def status(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    r = _redis()
    try:
        raw = {k: await r.get(f"canary:{k}") for k in CANARIES}
    finally:
        await r.aclose()
    out = []
    for k, c in CANARIES.items():
        row = {
            "key": k,
            "label": c.label,
            "interval_seconds": c.interval,
            "state": "never",
            "at": None,
            "detail": "",
            "duration_ms": None,
        }
        if raw[k]:
            d = json.loads(raw[k])
            age = (now - datetime.fromisoformat(d["at"])).total_seconds()
            state = "stale" if age > c.interval * STALE_FACTOR else ("ok" if d["ok"] else "failing")
            row |= {
                "state": state,
                "at": d["at"],
                "detail": d["detail"],
                "duration_ms": d["duration_ms"],
            }
        out.append(row)
    return out


@celery_app.task(name="canary.email")
def email_canary_task() -> bool:
    from .db import dispose_engines
    from .mail import check_connection

    async def run() -> bool:
        try:
            return await run_timed("email_smtp", check_connection)
        finally:
            await dispose_engines()

    return asyncio.run(run())


# Schedules live here (the beat process loads only the core library); the work for web.* and docs.* is done by those workers.
celery_app.conf.beat_schedule = {
    **(celery_app.conf.beat_schedule or {}),
    "canary-web-scan": {"task": "web.canary", "schedule": float(CANARIES["web_scan"].interval)},
    "canary-docs-pdf": {"task": "docs.canary", "schedule": float(CANARIES["docs_pdf"].interval)},
    "canary-email": {"task": "canary.email", "schedule": float(CANARIES["email_smtp"].interval)},
}
