"""Shared local configuration. Never commit the real .env file."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)

def required(name):
    value = os.environ.get(name)
    if not value or value == "CHANGE_ME":
        raise RuntimeError(f"Set {name} in your environment or local .env file.")
    return value

DB_PARAMS = {
    "dbname": required("PGDATABASE"),
    "user": required("PGUSER"),
    "password": required("PGPASSWORD"),
    "host": os.environ.get("PGHOST", "localhost"),
    "port": int(os.environ.get("PGPORT", "5432")),
}

def local_path(name, default):
    path = Path(os.environ.get(name, default)).expanduser()
    return str((ROOT / path).resolve() if not path.is_absolute() else path.resolve())

SHAPEFILE_PATH = local_path("SHAPEFILE_PATH", "data/parcels/dzialki.shp")
ZOBRAZOWANIA_DIR = local_path("SENTINEL_DIR", "data/sentinel")
# Fixed disposable directory: import removes everything inside it.
EXTRACT_DIR = str(ROOT / "work" / "extracted")
# SQL analysis also uses 32634; changing only this constant is insufficient.
RASTER_SRID = "32634"

def require_import_permission():
    if os.environ.get("ALLOW_TABLE_REBUILD", "").lower() != "true":
        raise RuntimeError(
            "Import recreates dzialki. Use a dedicated project database "
            "and set ALLOW_TABLE_REBUILD=true after checking the target."
        )
