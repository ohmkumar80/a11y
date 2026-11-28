"""Public legal pages. No sign-in needed: anyone must be able to read the terms before they agree to them."""

from a11y_core import legal
from a11y_core.config import get_config
from fastapi import APIRouter, HTTPException, Response, status

router = APIRouter(prefix="/legal", tags=["legal"])


async def _published() -> dict[str, legal.LegalPage]:
    items = (await get_config().effective("legal.pages")).value.items
    return {p.slug: p for p in items if p.status == "published"}


@router.get("")
async def list_pages(response: Response):
    """Which pages are published, for the site footer."""
    response.headers["Cache-Control"] = "public, max-age=60"
    return [
        {"slug": s, "title": p.title or legal.TITLES[s]} for s, p in (await _published()).items()
    ]


@router.get("/{slug}")
async def read_page(slug: str, response: Response):
    page = (await _published()).get(slug)
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This page has not been published.")
    response.headers["Cache-Control"] = "public, max-age=60"
    return {
        "slug": slug,
        "title": page.title or legal.TITLES[slug],
        "version": page.version,
        "effective_date": page.effective_date,
        "body": page.body,
    }
