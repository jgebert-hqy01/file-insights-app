"""Tests for scripts/make_smoke_bundle.py.

Confirms the zip contains exactly the registry-side code the smoke test
needs (and excludes the Streamlit/SQL-connector/pandas-touching layers), and
that pkgutil-based auto-discovery actually works when importing from the
produced zip. The second test runs in a fresh subprocess rather than
mutating this process's sys.modules, so it can't leak state into other
tests -- it needs no pyspark or dbutils, only the standard library's
zipimport plus this repo's real dependencies (pydantic).
"""
import subprocess
import sys
from zipfile import ZipFile

from scripts.make_smoke_bundle import build_bundle
import scripts.make_smoke_bundle as bundler


def _build_bundle_in(tmp_path, monkeypatch):
    dist_dir = tmp_path / "dist"
    monkeypatch.setattr(bundler, "DIST_DIR", dist_dir)
    monkeypatch.setattr(bundler, "OUTPUT_ZIP", dist_dir / "app_src.zip")
    return build_bundle()


def test_bundle_contains_expected_files_and_excludes_app_layer(tmp_path, monkeypatch):
    output_path = _build_bundle_in(tmp_path, monkeypatch)

    with ZipFile(output_path) as zf:
        names = set(zf.namelist())

    assert "app/__init__.py" in names
    assert "app/registry/__init__.py" in names
    assert "app/registry/loader.py" in names
    assert "app/registry/models.py" in names
    assert "app/sources/__init__.py" in names
    assert "app/sources/correlation.py" in names
    assert "app/queries/__init__.py" in names
    assert "app/queries/correlation.py" in names
    assert "app/masking.py" in names
    assert "app/validation.py" in names

    assert not any(name.startswith("app/db/") for name in names)
    assert not any(name.startswith("app/ui/") for name in names)
    assert "app/main.py" not in names
    assert "app/config.py" not in names
    assert "app/auth.py" not in names


def test_pkgutil_discovers_sources_and_queries_from_the_zip(tmp_path, monkeypatch):
    output_path = _build_bundle_in(tmp_path, monkeypatch)

    script = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from app.registry.loader import load_queries, load_sources; "
        "sources = load_sources(); queries = load_queries(); "
        "assert 'correlation_file' in sources, sources; "
        "assert 'correlation_file_last_loaded_at' in queries, queries; "
        "assert 'correlation_file_load_history' in queries, queries; "
        "assert 'correlation_file_load_count' in queries, queries; "
        "print('OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(output_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
