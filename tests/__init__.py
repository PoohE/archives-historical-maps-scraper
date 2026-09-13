"""Test package bootstrap for the project's flat-import module layout."""

import sys
from pathlib import Path

MODULES = Path(__file__).resolve().parents[1] / "scripts" / "modules"
SCRAPERS = MODULES / "scrapers"
for path in (MODULES, SCRAPERS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
