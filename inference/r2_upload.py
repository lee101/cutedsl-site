"""R2 (Cloudflare S3-compatible) upload for generated images."""

from __future__ import annotations

import logging
import os
from urllib.parse import quote_plus

import cachetools
from cachetools import cached

logger = logging.getLogger("cutedsl-inference")

R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", "https://f76d25b8b86cfa5638f43016510d8f77.r2.cloudflarestorage.com")
R2_BUCKET = os.getenv("R2_BUCKET", "appstatic")
R2_BUCKET_PATH = os.getenv("R2_BUCKET_PATH", "cutedsl/uploads")
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "appstatic.app.nz")

s3_client = None


def _get_s3_client():
    global s3_client
    if s3_client is None:
        import boto3
        session = boto3.session.Session()
        s3_client = session.client("s3", endpoint_url=R2_ENDPOINT_URL)
        logger.info("R2 client initialized: %s/%s/%s", R2_ENDPOINT_URL, R2_BUCKET, R2_BUCKET_PATH)
    return s3_client


def build_save_path(save_path: str, suffix: str | None = None) -> str:
    if not save_path:
        return ""
    parts = [p for p in save_path.split("/") if p]
    if not parts:
        return ""
    final_name = parts[-1]
    if suffix:
        if "." in final_name:
            stem, ext = final_name.rsplit(".", 1)
            final_name = f"{stem}_{suffix}.{ext}"
        else:
            final_name = f"{final_name}_{suffix}"
    directory = "/".join(parts[:-1])
    quoted_name = quote_plus(final_name)
    return f"{directory}/{quoted_name}" if directory else quoted_name


def _full_key(blob_name: str) -> str:
    return f"{R2_BUCKET_PATH}/{blob_name}"


@cached(cachetools.TTLCache(maxsize=10000, ttl=60 * 60 * 24))
def check_if_blob_exists(name: str) -> bool:
    try:
        _get_s3_client().head_object(Bucket=R2_BUCKET, Key=_full_key(name))
        return True
    except Exception:
        return False


def upload_bytes(blob_name: str, data: bytes, content_type: str = "image/webp") -> str:
    key = _full_key(blob_name)
    _get_s3_client().put_object(
        Bucket=R2_BUCKET,
        Key=key,
        Body=data,
        ACL="public-read",
        ContentType=content_type,
    )
    url = f"https://{R2_PUBLIC_BASE_URL}/{key}"
    logger.info("uploaded %s (%d bytes)", url, len(data))
    return url
