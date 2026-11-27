"""Typed settings registry (PROJECT_PLAN 3.11.1).

Every admin-configurable value is declared ONCE here: key, Pydantic model, default, allowed
scopes and optional guardrail. The admin API and generated forms read this registry, so a new
setting needs no new screen. Anything that can change after launch belongs here, not in code
or environment variables. (Database URLs, master keys, RLS and sandbox settings do NOT.)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .crypto import get_box


class Scope(StrEnum):
    GLOBAL = "global"
    PLAN = "plan"
    ORG = "org"


# Most specific wins.
RESOLUTION_ORDER = (Scope.ORG, Scope.PLAN, Scope.GLOBAL)


class GuardrailError(ValueError):
    """A change was rejected because it would leave the platform in an unsafe state."""


class Secret(BaseModel):
    """Write-only credential.

    Clients send ``{"$secret": true, "plaintext": "..."}`` to set or replace it, or
    ``{"$secret": true}`` to keep the stored one. The store keeps only ``ct`` (ciphertext) and
    ``hint`` (last 4 characters). The API returns ``set`` and ``hint`` - never ``ct``/plaintext.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    marker: Literal[True] = Field(True, alias="$secret")
    plaintext: str | None = Field(None, max_length=4096)
    ct: str | None = None
    hint: str | None = None

    def value(self) -> str:
        """Decrypt for internal use (e.g. calling a provider). Never log or return this."""
        if not self.ct:
            raise ValueError("secret is not set")
        return get_box().decrypt(self.ct)

    @property
    def is_set(self) -> bool:
        return bool(self.ct)


# --- walking raw JSON for secrets -----------------------------------------------------------

_MARK = "$secret"


def _is_secret(d: Any) -> bool:
    return isinstance(d, dict) and d.get(_MARK) is True


def _child_prev(prev: Any, key: Any, item: Any = None) -> Any:
    """Find the previous value matching ``key``. List items match by their ``id``."""
    if isinstance(prev, dict) and isinstance(key, str):
        return prev.get(key)
    if isinstance(prev, list):
        if isinstance(item, dict) and "id" in item:
            return next(
                (p for p in prev if isinstance(p, dict) and p.get("id") == item["id"]), None
            )
    return None


def seal(data: Any, prev: Any = None) -> Any:
    """Encrypt submitted plaintext secrets; carry stored ones forward when not re-submitted."""
    if _is_secret(data):
        plaintext = data.get("plaintext")
        if not plaintext and data.get("ct"):  # already sealed (a stored draft being published)
            return {_MARK: True, "ct": data["ct"], "hint": data.get("hint"), "plaintext": None}
        if plaintext:
            return {
                _MARK: True,
                "ct": get_box().encrypt(plaintext),
                "hint": plaintext[-4:] if len(plaintext) >= 12 else "",
                "plaintext": None,
            }
        if _is_secret(prev):
            return {_MARK: True, "ct": prev.get("ct"), "hint": prev.get("hint"), "plaintext": None}
        return {_MARK: True, "ct": None, "hint": None, "plaintext": None}
    if isinstance(data, dict):
        return {k: seal(v, _child_prev(prev, k)) for k, v in data.items()}
    if isinstance(data, list):
        return [seal(v, _child_prev(prev, i, v)) for i, v in enumerate(data)]
    return data


def strip_untrusted(data: Any) -> Any:
    """Client input may only carry ``plaintext`` for a secret - never ciphertext or a hint."""
    if _is_secret(data):
        return {_MARK: True, "plaintext": data.get("plaintext")}
    if isinstance(data, dict):
        return {k: strip_untrusted(v) for k, v in data.items()}
    if isinstance(data, list):
        return [strip_untrusted(v) for v in data]
    return data


def redact(data: Any) -> Any:
    """What the API may return: secrets reduced to ``{set, hint}``."""
    if _is_secret(data):
        hint = data.get("hint") or ""
        return {_MARK: True, "set": bool(data.get("ct")), "hint": f"••••{hint}" if hint else None}
    if isinstance(data, dict):
        return {k: redact(v) for k, v in data.items()}
    if isinstance(data, list):
        return [redact(v) for v in data]
    return data


# --- definitions ----------------------------------------------------------------------------


@dataclass(frozen=True)
class SettingDef:
    key: str
    model: type[BaseModel]
    default: BaseModel
    description: str
    scopes: frozenset[Scope] = frozenset({Scope.GLOBAL})
    # Called with (new, previous-or-default). Raise GuardrailError to reject.
    guard: Callable[[Any, Any], None] | None = None
    # Two-person approval applies from Phase 2 (PROJECT_PLAN 4); the flag is declared now.
    high_risk: bool = False
    owner_role: str = "PLATFORM_OWNER"
    tags: tuple[str, ...] = field(default_factory=tuple)

    def json_schema(self) -> dict:
        return self.model.model_json_schema(by_alias=True)

    def validate(self, raw: Any, prev_raw: Any = None, *, trusted: bool = False) -> dict:
        """Validate submitted JSON, run the guardrail, and return the JSON to STORE (sealed).
        ``trusted`` is only for values read back from our own store (publish, rollback)."""
        if not trusted:
            raw = strip_untrusted(raw)
        try:
            model = self.model.model_validate(raw)
        except ValueError as e:  # pydantic.ValidationError subclasses ValueError
            raise GuardrailError(str(e)) from e
        sealed = seal(model.model_dump(mode="json", by_alias=True), prev_raw)
        final = self.model.model_validate(sealed)
        if self.guard:
            prev = self.model.model_validate(prev_raw) if prev_raw is not None else self.default
            self.guard(final, prev)
        return final.model_dump(mode="json", by_alias=True)


REGISTRY: dict[str, SettingDef] = {}


def register(defn: SettingDef) -> SettingDef:
    if defn.key in REGISTRY:
        raise ValueError(f"duplicate setting key {defn.key}")
    REGISTRY[defn.key] = defn
    return defn


def get_def(key: str) -> SettingDef:
    from . import definitions  # noqa: F401  (registers on import)

    try:
        return REGISTRY[key]
    except KeyError:
        raise KeyError(f"unknown setting {key!r}") from None
