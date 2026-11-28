"""Object storage for customer files, with envelope encryption (ADR 0020).

* Every object is encrypted by US before it leaves the process: AES-256-GCM with a fresh random key per object. The
  object key is bound in as associated data, so a ciphertext copied to another key will not decrypt.
* The per-object key is wrapped with the platform master key ring (the same `SecretBox` as admin secrets, so key
  rotation and the production KMS plan are shared) and kept in the database row, not next to the data.
* The store itself is a tiny interface: S3 API in production and development (RustFS locally), an in-memory fake in
  tests. Azure Blob can be added behind the same interface without touching callers."""

from __future__ import annotations

import asyncio
import base64
import os
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config.crypto import get_box
from .settings import get_settings

NONCE_BYTES = 12


class StorageError(RuntimeError):
    """The store could not be reached or refused the request (a system fault, never the customer's)."""


class ObjectNotFound(StorageError):
    pass


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...


class MemoryStore:
    """Test double. Also usable for local runs without S3."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.objects[key] = bytes(data)

    async def get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError:
            raise ObjectNotFound(key) from None

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.objects


class S3Store:
    """S3 API through boto3 (blocking), run in a worker thread so the event loop is never blocked."""

    def __init__(
        self, *, endpoint_url: str, access_key: str, secret_key: str, bucket: str, region: str
    ):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self._c = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=60,
            ),
        )

    async def put(self, key: str, data: bytes) -> None:
        args = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": data,
            "ContentType": "application/octet-stream",  # never the customer's claimed type
        }
        if self._sse():
            args["ServerSideEncryption"] = "AES256"
        try:
            await asyncio.to_thread(self._c.put_object, **args)
        except Exception as e:  # noqa: BLE001
            raise StorageError(f"could not store object: {type(e).__name__}") from e

    @staticmethod
    def _sse() -> bool:
        # Real S3 always encrypts at rest; RustFS in development may not implement the header.
        return get_settings().env == "production"

    async def get(self, key: str) -> bytes:
        try:
            r = await asyncio.to_thread(self._c.get_object, Bucket=self.bucket, Key=key)
            return await asyncio.to_thread(r["Body"].read)
        except self._c.exceptions.NoSuchKey as e:
            raise ObjectNotFound(key) from e
        except Exception as e:  # noqa: BLE001
            raise StorageError(f"could not read object: {type(e).__name__}") from e

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._c.delete_object, Bucket=self.bucket, Key=key)
        except Exception as e:  # noqa: BLE001
            raise StorageError(f"could not delete object: {type(e).__name__}") from e

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self._c.head_object, Bucket=self.bucket, Key=key)
            return True
        except Exception as e:  # noqa: BLE001
            code = getattr(e, "response", {}).get("Error", {}).get("Code")
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise StorageError(f"could not check object: {type(e).__name__}") from e


_overrides: dict[str | None, ObjectStore] = {}
_s3_cache: dict[tuple, S3Store] = {}


def set_store(store: ObjectStore | None, region: str | None = None) -> None:
    """Tests install a fake here. With no region it serves every region; with one it serves only that region.
    `set_store(None)` removes every fake."""
    if store is None:
        _overrides.clear()
    else:
        _overrides[region] = store


async def regions() -> tuple[dict, str]:
    """(every storage region by id, the default region's id). The region 'default' always exists and uses the platform's
    own storage settings unless an administrator redefines it."""
    from .config import get_config  # noqa: PLC0415
    from .config.definitions import StorageRegion  # noqa: PLC0415

    cfg = (await get_config().effective("data.regions")).value
    out = {r.id: r for r in cfg.items}
    out.setdefault("default", StorageRegion(id="default", label="Default region"))
    return out, cfg.default_id


async def store_for(region_id: str) -> ObjectStore:
    """The store for one region. A file is only ever read from, written to or deleted in ITS region: an unknown region is an
    error, never a silent fall back to another place."""
    if region_id in _overrides:
        return _overrides[region_id]
    if None in _overrides:
        return _overrides[None]
    regs, _ = await regions()
    r = regs.get(region_id)
    if r is None:
        raise StorageError(f"storage region {region_id!r} is not configured")
    s = get_settings()
    endpoint, bucket, aws = (
        r.endpoint_url or s.s3_endpoint_url,
        r.bucket or s.s3_bucket,
        r.aws_region or s.s3_region,
    )
    key = (endpoint, bucket, aws)
    if key not in _s3_cache:
        _s3_cache[key] = S3Store(
            endpoint_url=endpoint,
            access_key=s.s3_access_key,
            secret_key=s.s3_secret_key,
            bucket=bucket,
            region=aws,
        )
    return _s3_cache[key]


def get_store() -> ObjectStore:
    """The default region's store, for health checks and code that is not about one customer's file."""
    if None in _overrides:
        return _overrides[None]
    s = get_settings()
    key = (s.s3_endpoint_url, s.s3_bucket, s.s3_region)
    if key not in _s3_cache:
        _s3_cache[key] = S3Store(
            endpoint_url=s.s3_endpoint_url,
            access_key=s.s3_access_key,
            secret_key=s.s3_secret_key,
            bucket=s.s3_bucket,
            region=s.s3_region,
        )
    return _s3_cache[key]


# --- envelope encryption ------------------------------------------------------------------------------


def seal_bytes(plaintext: bytes, key: str) -> tuple[bytes, str]:
    """(blob to store, wrapped data key to keep in the database row)."""
    data_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(NONCE_BYTES)
    blob = nonce + AESGCM(data_key).encrypt(nonce, plaintext, key.encode())
    return blob, get_box().encrypt(base64.b64encode(data_key).decode())


def open_bytes(blob: bytes, wrapped_key: str, key: str) -> bytes:
    """Decrypt; raises ValueError when the blob was altered or belongs to another key."""
    data_key = base64.b64decode(get_box().decrypt(wrapped_key))
    try:
        return AESGCM(data_key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], key.encode())
    except Exception as e:  # noqa: BLE001
        raise ValueError("stored file failed its integrity check") from e


def object_key(org_id, doc_id) -> str:
    """Tenant-prefixed so a bucket policy or an audit can always tell whose file an object is."""
    return f"documents/{org_id}/{doc_id}/original"
