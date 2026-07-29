"""Module entry point for ``python -m sophyane``."""

from sophyane.runtime_safety import install_runtime_safety

# Install execution guards before importing the main application and TUI.
# This ensures modules that capture execute_action receive the guarded version.
install_runtime_safety()

from sophyane.main import main


if __name__ == "__main__":
    raise SystemExit(main())
