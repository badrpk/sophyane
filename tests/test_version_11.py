"""Version 11 release consistency checks."""

from pathlib import Path

from sophyane.version import __version__


def test_runtime_version_is_11() -> None:
    assert __version__ == "11.0.0"


def test_package_metadata_versions_match() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    setup = (root / "setup.py").read_text(encoding="utf-8")
    assert 'version = "11.0.0"' in pyproject
    assert 'version="11.0.0"' in setup
