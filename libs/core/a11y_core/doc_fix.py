"""The guided-fix plan for a PDF (ADR 0022): what a person wants changed, validated against what the file really contains.

A plan is plain data, never code: a title, a language, alt text per figure and a level per heading. It is checked here, in
core, so the API can refuse a bad plan immediately (using the structure stored with the audit) and the worker checks it again
against the real file before applying anything."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,3}$")
ID = re.compile(r"^\d{1,9}-\d{1,5}$")
MAX_EDITS = 500


class FixPlan(BaseModel):
    title: str | None = Field(None, max_length=200, description="The document title")
    language: str | None = Field(
        None, max_length=35, description="A language code such as en, en-GB or hi"
    )
    alt: dict[str, str] = Field(default_factory=dict, description="Alternative text by figure id")
    heading_levels: dict[str, int] = Field(
        default_factory=dict, description="New level (1 to 6) by heading id"
    )

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if v and not LANG.match(v):
            raise ValueError("Enter a language code such as en, en-GB or hi.")
        return v or None

    @field_validator("alt")
    @classmethod
    def _alt(cls, v: dict[str, str]) -> dict[str, str]:
        out = {}
        for k, t in v.items():
            t = " ".join((t or "").split())
            if not t:
                continue  # blank means "no change"
            if len(t) > 1000:
                raise ValueError(
                    "Alternative text can be at most 1000 characters. Keep it short: say what the image shows or is for."
                )
            out[k] = t
        return out

    @field_validator("heading_levels")
    @classmethod
    def _levels(cls, v: dict[str, int]) -> dict[str, int]:
        for lvl in v.values():
            if not 1 <= lvl <= 6:
                raise ValueError("A heading level is a number from 1 to 6.")
        return v

    def is_empty(self) -> bool:
        return not (self.title or self.language or self.alt or self.heading_levels)

    def edit_count(self) -> int:
        return (
            sum(1 for x in (self.title, self.language) if x)
            + len(self.alt)
            + len(self.heading_levels)
        )


def check_against(plan: FixPlan, structure: dict) -> list[str]:
    """Problems, in plain words, between a plan and the structure read from the file. Empty list = fine."""
    problems: list[str] = []
    if (plan.alt or plan.heading_levels) and not structure.get("has_structure"):
        return ["This file has no tags, so image descriptions and heading levels cannot be changed here."]
    if plan.edit_count() > MAX_EDITS:
        problems.append(
            f"That is more than {MAX_EDITS} changes at once. Apply some first, then continue."
        )
    figures = {f["id"]: f for f in structure.get("figures", []) if f.get("editable")}
    headings = {h["id"]: h for h in structure.get("headings", []) if h.get("editable")}
    for fid in plan.alt:
        if not ID.match(fid) or fid not in figures:
            problems.append(
                "One of the images you described is no longer in the file. Reload the page and try again."
            )
            break
    for hid in plan.heading_levels:
        if not ID.match(hid) or hid not in headings:
            problems.append(
                "One of the headings you changed is no longer in the file. Reload the page and try again."
            )
            break
    if (plan.alt or plan.heading_levels) and not structure.get("has_structure"):
        problems.append(
            "This file has no tags, so image descriptions and heading levels cannot be changed here."
        )
    return problems
