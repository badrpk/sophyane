"""Release consistency checks for Sophyane v16."""

from pathlib import Path

from sophyane.version import __version__


def test_runtime_version_is_current() -> None:
    assert __version__ == "16.0.0"


def test_package_metadata_versions_match() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    setup = (root / "setup.py").read_text(encoding="utf-8")
    assert f'version = "{__version__}"' in pyproject
    assert f'version="{__version__}"' in setup
