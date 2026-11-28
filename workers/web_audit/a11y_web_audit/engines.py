"""Loads the pinned engine bundles and refuses to run if one was tampered with or is stale."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from a11y_core.settings import get_settings

ENGINE_IDS = ("axe", "ibm", "htmlcs")


class EngineBundleError(RuntimeError):
    pass


def bundles_dir() -> Path:
    if d := get_settings().engine_bundles_dir:
        return Path(d)
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages/engine-bundles/dist/versions.json").exists():
            return parent / "packages/engine-bundles/dist"
    raise EngineBundleError(
        "engine bundles not built: run `pnpm --filter @a11y/engine-bundles build`"
    )


@lru_cache
def load_bundles() -> tuple[dict[str, str], dict[str, str]]:
    """Returns ({engine: javascript source}, {engine: version}). Verifies every SHA-256."""
    root = bundles_dir()
    manifest = json.loads((root / "versions.json").read_text())
    sources: dict[str, str] = {}
    versions: dict[str, str] = {}
    for eng in ENGINE_IDS:
        meta = manifest[eng]
        data = (root / meta["file"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != meta["sha256"]:
            raise EngineBundleError(f"{eng} bundle does not match its recorded hash")
        sources[eng] = data.decode("utf-8")
        versions[eng] = meta["version"]
    return sources, versions


def runner_source() -> str:
    return (Path(__file__).parent / "runner.js").read_text()
