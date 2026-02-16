"""Configuration defaults for OpenClaw."""

import os

# Anthropic
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Post-frame defaults (feet unless noted)
DEFAULT_POST_SPACING_FT = 8
DEFAULT_EAVE_HEIGHT_FT = 10
DEFAULT_POST_SIZE_INCHES = 6
DEFAULT_EMBED_DEPTH_FT = 4
DEFAULT_TRUSS_SPACING_FT = 2
DEFAULT_ROOF_PITCH = 4  # 4:12
DEFAULT_OVERHANG_FT = 1
DEFAULT_SLAB_THICKNESS_INCHES = 4
DEFAULT_GIRT_SPACING_FT = 2

# Output
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
