"""Builds dist/app_src.zip: just the registry-side code notebooks need (no
Streamlit, no SQL connector). Includes the shared executor interface and the
Spark executor (app/db/executor.py, app/db/spark_client.py) but not
app/db/client.py, which needs databricks-sql-connector.

Pure stdlib, Python 3.9-compatible. Run from anywhere; paths are resolved
relative to this file's location in the repo:

    python scripts/make_smoke_bundle.py

Auto-discovers every .py file under app/registry, app/sources, and
app/queries, so adding a new source or query domain file needs no change
here.
"""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist"
OUTPUT_ZIP = DIST_DIR / "app_src.zip"

INCLUDED_DIRS = ("app/registry", "app/sources", "app/queries")
INCLUDED_FILES = (
    "app/__init__.py",
    "app/masking.py",
    "app/validation.py",
    "app/db/__init__.py",
    "app/db/executor.py",
    "app/db/spark_client.py",
)


def _iter_included_paths():
    for relative_dir in INCLUDED_DIRS:
        directory = REPO_ROOT / relative_dir
        for path in sorted(directory.rglob("*.py")):
            yield path.relative_to(REPO_ROOT)
    for relative_file in INCLUDED_FILES:
        path = REPO_ROOT / relative_file
        if not path.is_file():
            raise FileNotFoundError("Expected file not found: {0}".format(relative_file))
        yield Path(relative_file)


def build_bundle() -> Path:
    DIST_DIR.mkdir(exist_ok=True)
    included = sorted(set(_iter_included_paths()), key=lambda p: p.as_posix())
    if not included:
        raise RuntimeError("No files found to bundle -- check INCLUDED_DIRS/INCLUDED_FILES.")
    with ZipFile(OUTPUT_ZIP, "w", ZIP_DEFLATED) as zf:
        for relative_path in included:
            zf.write(REPO_ROOT / relative_path, arcname=relative_path.as_posix())
    return OUTPUT_ZIP


if __name__ == "__main__":
    output_path = build_bundle()
    print("Wrote {0}".format(output_path))
    with ZipFile(output_path) as zf:
        for name in zf.namelist():
            print("  {0}".format(name))
