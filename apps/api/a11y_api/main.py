from contextlib import asynccontextmanager

from a11y_core import flags, notify, webhooks  # noqa: F401  (registers settings and tasks)
from a11y_core import legal as _legal_setting  # noqa: F401
from a11y_core.billing import BillingError
from a11y_core.db import app_engine, dispose_engines
from a11y_core.settings import get_settings
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from .routers import (
    admin_ai,
    admin_billing,
    admin_documents,
    admin_notifications,
    admin_ops,
    admin_reviews,
    admin_security,
    admin_settings,
    auth,
    documents,
    domains,
    fixes,
    legal,
    me_notifications,
    mfa,
    org,
    org_ai,
    org_api_keys,
    org_data_policy,
    org_webhooks,
    reports,
    review,
    rule_guidance,
    scans,
    standards,
    v1,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await dispose_engines()


app = FastAPI(title="a11y API", version="0.1.0", lifespan=lifespan)
s = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["authorization", "content-type"],
)


@app.exception_handler(HTTPException)
async def http_error(_, exc: HTTPException):
    """One error shape for every endpoint: {detail, code?, field?} so the web UI can render
    messages next to the right input and in an error summary."""
    body = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
    return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(BillingError)
async def billing_error(_, exc: BillingError):
    """Seat limit / quota / locked subscription: structured so the UI can show an upgrade prompt."""
    return JSONResponse(exc.body(), status_code=exc.status_code)


@app.get("/health/live", include_in_schema=False)
async def live():
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def ready():
    checks: dict[str, str] = {}
    try:
        async with app_engine().connect() as c:
            await c.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:  # noqa: BLE001
        checks["postgres"] = "down"
    try:
        r = Redis.from_url(s.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception:  # noqa: BLE001
        checks["redis"] = "down"
    code = 200 if all(v == "ok" for v in checks.values()) else 503
    return JSONResponse(checks, status_code=code)


app.include_router(auth.router)
app.include_router(mfa.router)
app.include_router(org.router)
app.include_router(admin_settings.router)
app.include_router(admin_security.router)
app.include_router(admin_billing.router)
app.include_router(admin_notifications.router)
app.include_router(admin_ops.router)
app.include_router(admin_ai.router)
app.include_router(org_ai.router)
app.include_router(standards.router)
app.include_router(rule_guidance.router)
app.include_router(legal.router)
app.include_router(fixes.router)
app.include_router(me_notifications.router)
app.include_router(org_api_keys.router)
app.include_router(org_data_policy.router)
app.include_router(org_webhooks.router)
app.include_router(v1.router)
app.include_router(scans.router)
app.include_router(documents.router)
app.include_router(admin_documents.router)
app.include_router(admin_reviews.router)
app.include_router(review.router)
app.include_router(domains.router)
app.include_router(reports.router)


from fastapi.exceptions import RequestValidationError  # noqa: E402


@app.exception_handler(RequestValidationError)
async def validation_error(_, exc: RequestValidationError):
    first = exc.errors()[0]
    field = str(first["loc"][-1]) if first.get("loc") else None
    msg = "Enter a valid email address." if field == "email" else first["msg"]
    return JSONResponse({"detail": msg, "field": field}, status_code=422)
