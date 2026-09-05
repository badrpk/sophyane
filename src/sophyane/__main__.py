"""Module entry point for ``python -m sophyane``."""

from sophyane.runtime_safety import install_runtime_safety
from sophyane.runtime_filesystem_capabilities_v20 import install_filesystem_capabilities_v20

# Install execution guards before importing the main application and TUI.
# This ensures modules that capture execute_action receive the guarded version.
install_runtime_safety()
install_filesystem_capabilities_v20()

# SOPHYANE_CANONICAL_MODULE_ENTRYPOINT_V1
# `python -m sophyane` must use the same verified CLI authority
# as the installed Sophyane launcher. The legacy main.main()
# one-shot path converts AgentResponse text into exit code 0 and
# therefore cannot own repository execution.
from sophyane.cli_entry import main


if __name__ == "__main__":
    raise SystemExit(main())
