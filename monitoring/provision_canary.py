#!/usr/bin/env python3
"""Idempotently provision the private unlimited image-canary API identity."""

from __future__ import annotations

import argparse
import os
import secrets
import uuid
from pathlib import Path

import psycopg2

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent
CANARY_WALLET = "cutedsl-production-monitor"
CANARY_EMAIL = "production-monitor@cutedsl.internal"


def dotenv_value(path: Path, name: str) -> str:
    if not path.exists():
        return ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def write_monitor_env(path: Path, api_key: str) -> None:
    existing: list[str] = []
    if path.exists():
        existing = path.read_text(encoding="utf-8").splitlines()
    output = [line for line in existing if not line.startswith("CUTEDSL_MONITOR_API_KEY=")]
    output.append(f"CUTEDSL_MONITOR_API_KEY={api_key}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision the CuteDSL production image canary")
    parser.add_argument("--env-file", type=Path, default=SCRIPT_DIR / ".env")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL") or dotenv_value(REPO_DIR / ".env", "DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not configured")

    connection = psycopg2.connect(dsn)
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT api_key FROM users WHERE wallet_address = %s", (CANARY_WALLET,))
            row = cursor.fetchone()
            if row:
                api_key = row[0]
                cursor.execute(
                    "UPDATE users SET unlimited_api = TRUE, updated_at = NOW() WHERE wallet_address = %s",
                    (CANARY_WALLET,),
                )
                created = False
            else:
                api_key = "cutedsl_" + secrets.token_hex(24)
                cursor.execute(
                    """INSERT INTO users
                       (id, wallet_address, email, api_key, credits, unlimited_api,
                        total_deposited, drip_step, drip_started_at, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, 0, TRUE, 0, 0, '1970-01-01', NOW(), NOW())""",
                    (str(uuid.uuid4()), CANARY_WALLET, CANARY_EMAIL, api_key),
                )
                created = True
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    write_monitor_env(args.env_file, api_key)
    print(f"Canary identity {'created' if created else 'updated'}; key stored in {args.env_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
