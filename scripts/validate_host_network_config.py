#!/usr/bin/env python3
"""Reject duplicate or competing DHCP ownership for a host interface."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def dhcp_stanza_count(text: str, interface: str) -> int:
    pattern = re.compile(
        rf"^\s*iface\s+{re.escape(interface)}\s+inet\s+dhcp(?:\s|$)",
        re.MULTILINE,
    )
    return len(pattern.findall(text))


def validate(text: str, interface: str, *, networkd_managed: bool) -> list[str]:
    count = dhcp_stanza_count(text, interface)
    errors: list[str] = []
    if count > 1:
        errors.append(f"{interface} has {count} duplicate ifupdown DHCP stanzas")
    if networkd_managed and count:
        errors.append(
            f"{interface} is managed by systemd-networkd but also has an ifupdown DHCP stanza"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interfaces", type=Path, default=Path("/etc/network/interfaces"))
    parser.add_argument("--interface", default="eth0")
    parser.add_argument("--networkd-managed", action="store_true")
    args = parser.parse_args()

    errors = validate(
        args.interfaces.read_text(encoding="utf-8"),
        args.interface,
        networkd_managed=args.networkd_managed,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK: {args.interface} has a single DHCP owner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
