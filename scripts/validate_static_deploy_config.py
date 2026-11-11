#!/usr/bin/env python3
"""Validate that exported static URLs map to the R2 upload prefix."""

from __future__ import annotations

import argparse
from urllib.parse import urlparse


def validate_static_deploy_config(
    static_base_url: str, bucket_path: str, static_path: str
) -> None:
    parsed = urlparse(static_base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("static base URL must be an absolute HTTP(S) URL")
    if parsed.query or parsed.fragment:
        raise ValueError("static base URL must not contain a query or fragment")

    object_prefix = "/" + "/".join(
        part.strip("/") for part in (bucket_path, static_path) if part.strip("/")
    )
    public_path = parsed.path.rstrip("/")
    if parsed.hostname == "appstatic.app.nz" and public_path != object_prefix:
        raise ValueError(
            f"{static_base_url!r} maps to {public_path or '/'!r}, but assets are "
            f"uploaded under {object_prefix!r}; set CUTEDSL_STATIC_BASE_URL to "
            f"'https://appstatic.app.nz{object_prefix}'"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static-base-url", required=True)
    parser.add_argument("--bucket-path", required=True)
    parser.add_argument("--static-path", required=True)
    args = parser.parse_args()
    try:
        validate_static_deploy_config(
            args.static_base_url, args.bucket_path, args.static_path
        )
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
