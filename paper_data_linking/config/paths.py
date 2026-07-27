# ./config/paths.py
from pathlib import Path
from .settings import PROJECT_ROOT_DIR

# --- Core Project Directories ---
DATA_ASSETS_DIR: Path = PROJECT_ROOT_DIR / "data_assets"

# --- VSO Related Paths (within data_assets) ---
VSO_ASSETS_DATA_DIR: Path = DATA_ASSETS_DIR / "vso"
VSO_METADATA_JSONL: Path = VSO_ASSETS_DATA_DIR / "vso_metadata_exploded.jsonl"
