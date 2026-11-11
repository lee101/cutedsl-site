#!/usr/bin/env python3
"""Run the open-source CuteDSL diffusion frontier from this deployment repo."""

from __future__ import annotations

import sys
from pathlib import Path

SIBLING_CUTEDSL = Path(__file__).resolve().parents[2] / "cutedsl"
if str(SIBLING_CUTEDSL) not in sys.path:
    sys.path.insert(0, str(SIBLING_CUTEDSL))

from diffusion_frontier.benchmark import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
