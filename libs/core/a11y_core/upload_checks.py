"""First-line checks on an uploaded file, before anything is stored or parsed (ADR 0020).

Standard library only, and nothing here extracts a file to disk. Three rules:
* The customer's claim (file name, content type) is never trusted: the kind is decided from the bytes.
* ZIP-based files (Word, PowerPoint, EPUB) are measured by actually decompressing into a counter with a hard cap,
  not by believing the sizes written in the archive header, which an attacker controls.
* Every refusal carries a stable `code` (for metrics and support) and a plain-language `message` (for the person)."""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass

KINDS = ("pdf", "docx", "pptx", "epub")
EXT = {".pdf": "pdf", ".docx": "docx", ".pptx": "pptx", ".epub": "epub"}
PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"
EPUB_MIME = b"application/epub+zip"
_NESTED = (
    ".zip",
    ".jar",
    ".apk",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".msi",
    ".bat",
    ".cmd",
    ".scr",
    ".js",
    ".vbs",
)
READ_CHUNK = 1024 * 1024


class Refusal(Exception):
    """A file we will not accept. A refusal is always the customer's file, never ours: a storage or scanner outage
    is a different kind of failure and must not be reported as one (PROJECT_PLAN 3.5)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ZipLimits:
    max_entries: int
    max_uncompressed_bytes: int
    max_ratio: int


def sanitize_filename(name: str | None) -> str:
    """A safe display name: no path, no control characters, bounded length. Never used to build a storage key."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFC", base)
    base = "".join(c for c in base if c.isprintable() and c not in '<>:"|?*\x7f').strip(" .")
    base = re.sub(r"\s+", " ", base)
    if len(base) > 150:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: 145 - len(ext)] + dot + ext) if dot and len(ext) <= 8 else base[:150]
    return base or "document"


def kind_from_name(name: str) -> str | None:
    m = re.search(r"\.[A-Za-z0-9]+$", name)
    return EXT.get(m.group(0).lower()) if m else None


def check_size(kind: str, size: int, max_bytes: int) -> None:
    if size == 0:
        raise Refusal("empty", "That file is empty.")
    if size > max_bytes:
        raise Refusal(
            "too_large",
            f"That file is {size / 1048576:.1f} MB, and the limit for this file type is {max_bytes // 1048576} MB.",
        )


def _inspect_zip(data: bytes, limits: ZipLimits) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError):
        raise Refusal(
            "corrupt", "That file is damaged or is not a valid Office or EPUB file."
        ) from None
    infos = zf.infolist()
    if len(infos) > limits.max_entries:
        raise Refusal(
            "zip_bomb",
            "That file contains far more items than a normal document, so we cannot accept it.",
        )
    total = 0
    for info in infos:
        name = info.filename
        if name.startswith("/") or ".." in name.replace("\\", "/").split("/") or "\x00" in name:
            raise Refusal(
                "zip_unsafe_path",
                "That file contains items with unsafe paths, so we cannot accept it.",
            )
        if info.flag_bits & 0x1:
            raise Refusal(
                "encrypted",
                "That file is password-protected. Remove the password and upload it again.",
            )
        if name.lower().endswith(_NESTED):
            raise Refusal(
                "zip_nested", "That file contains programs or archives, so we cannot accept it."
            )
        # Trust measured bytes, not the header: decompress into a counter with a hard stop.
        measured = 0
        budget = limits.max_uncompressed_bytes - total
        try:
            with zf.open(info) as f:
                while chunk := f.read(READ_CHUNK):
                    measured += len(chunk)
                    if measured > budget:
                        raise Refusal(
                            "zip_bomb",
                            "That file expands to far more data than a normal document, so we cannot accept it.",
                        )
                    if measured > limits.max_ratio * max(info.compress_size, 1024):
                        raise Refusal(
                            "zip_bomb",
                            "That file is compressed in a suspicious way, so we cannot accept it.",
                        )
        except (
            zipfile.BadZipFile,
            EOFError,
            OSError,
            ValueError,
            RuntimeError,
            NotImplementedError,
        ):
            raise Refusal(
                "corrupt", "That file is damaged or is not a valid Office or EPUB file."
            ) from None
        total += measured
    return zf


def detect_kind(data: bytes, claimed_name: str, limits: ZipLimits) -> str:
    """The real kind of the file, which must agree with its extension. Raises Refusal otherwise."""
    claimed = kind_from_name(claimed_name)
    if claimed is None:
        raise Refusal(
            "unsupported_type", "We accept PDF, Word (.docx), PowerPoint (.pptx) and EPUB files."
        )
    if claimed == "pdf":
        if PDF_MAGIC not in data[:1024]:
            raise Refusal("type_mismatch", "That file has a .pdf name but is not a PDF.")
        return "pdf"
    if data[:4] != ZIP_MAGIC:
        raise Refusal(
            "type_mismatch",
            f"That file has a .{claimed} name but is not a real {claimed.upper()} file.",
        )
    zf = _inspect_zip(data, limits)
    names = set(zf.namelist())
    if claimed == "docx":
        ok = "[Content_Types].xml" in names and "word/document.xml" in names
    elif claimed == "pptx":
        ok = "[Content_Types].xml" in names and "ppt/presentation.xml" in names
    else:
        ok = (
            bool(zf.infolist())
            and zf.infolist()[0].filename == "mimetype"
            and zf.read("mimetype").strip() == EPUB_MIME
        )
    if not ok:
        raise Refusal(
            "type_mismatch",
            f"That file has a .{claimed} name but is not a real {claimed.upper()} file.",
        )
    return claimed
