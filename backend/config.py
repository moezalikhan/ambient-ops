"""Central configuration. Reads .env once at import."""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

load_dotenv(REPO_ROOT / ".env")


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


FORTYGUARD_API_KEY = _get("FORTYGUARD_API_KEY")
FORTYGUARD_BASE_URL = _get("FORTYGUARD_BASE_URL", "https://api.fortyguard.com")

ORS_API_KEY = _get("ORS_API_KEY")
OVERPASS_URL = _get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")

ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _get("ANTHROPIC_MODEL", "claude-sonnet-5")

CACHE_DB_PATH = REPO_ROOT / _get("CACHE_DB_PATH", "data/ambient_ops.db")
DEMO_ROUTES_PATH = DATA_DIR / "demo_routes.json"

# Default Heat Priority Score weights (spec section 6).
# Exposed as sliders in the UI; these are the starting position, not an optimum.
DEFAULT_WEIGHTS = {
    "HEI": 0.40,  # Heat Exposure Index
    "DTF": 0.20,  # Dwell Time Factor
    "SVI": 0.20,  # Surface Vulnerability Index
    "PSI": 0.20,  # Population Sensitivity Index
}

WALKING_SPEED_MPS = 1.3  # average adult walking speed, used by DTF
SEGMENT_LENGTH_M = 50


def missing_keys() -> list[str]:
    """Which integrations are unconfigured. Surfaced at /api/health."""
    missing = []
    if not FORTYGUARD_API_KEY:
        missing.append("FORTYGUARD_API_KEY")
    if not ORS_API_KEY:
        missing.append("ORS_API_KEY")
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    return missing
