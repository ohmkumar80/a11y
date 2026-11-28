"""Legal pages (terms, privacy, and so on) as an admin setting.

THE PLATFORM SHIPS NO LEGAL TEXT. Every page starts empty and unpublished; a person with the authority to bind the company
writes (or has counsel write) the real wording and publishes it. The setting is versioned and audited like any other, so
which text was live on a given day is always answerable. Publishing requires a body and an effective date, so a half-written
page cannot go live by accident."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .config.registry import GuardrailError, SettingDef, register

SLUGS = ("terms", "privacy", "cookies", "dpa", "acceptable-use", "refunds")
TITLES = {
    "terms": "Terms of service",
    "privacy": "Privacy policy",
    "cookies": "Cookie policy",
    "dpa": "Data processing agreement",
    "acceptable-use": "Acceptable use policy",
    "refunds": "Refund policy",
}


class LegalPage(BaseModel):
    slug: Literal[SLUGS] = Field(description="Which page this is. It appears at /legal/<slug>")  # type: ignore[valid-type]
    title: str = Field("", max_length=120, description="Empty = the standard title")
    status: Literal["draft", "published"] = Field(
        "draft", description="Only published pages are public"
    )
    version: str = Field("", max_length=40, description="For example 2026-12")
    effective_date: date | None = Field(None, description="When this wording takes effect")
    body: str = Field(
        "",
        max_length=80_000,
        description="Plain text with simple formatting: # headings, - lists, **bold**, [links](https://…)",
    )


class LegalPages(BaseModel):
    items: list[LegalPage] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self):
        slugs = [i.slug for i in self.items]
        if len(slugs) != len(set(slugs)):
            raise ValueError("Each page can appear only once.")
        return self


def _guard(new: LegalPages, prev: LegalPages) -> None:
    for p in new.items:
        if p.status == "published":
            if len(p.body.strip()) < 50:
                raise GuardrailError(f"{TITLES[p.slug]}: a published page needs its text.")
            if p.effective_date is None:
                raise GuardrailError(f"{TITLES[p.slug]}: a published page needs an effective date.")


register(
    SettingDef(
        key="legal.pages",
        model=LegalPages,
        default=LegalPages(),
        description="Terms, privacy policy and other legal pages. Nothing is published until you write it and set it to published. "
        "Write the real text yourself or have counsel write it: the platform provides none.",
        guard=_guard,
        high_risk=True,
        owner_role="PLATFORM_OWNER",
        tags=("legal",),
    )
)
