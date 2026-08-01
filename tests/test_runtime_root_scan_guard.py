import unittest

from sophyane.runtime_safety import _unsafe_root_scan


class RootScanGuardTests(unittest.TestCase):
    def test_blocks_find_root(self):
        self.assertIsNotNone(
            _unsafe_root_scan("find / -name pytest")
        )

    def test_blocks_find_root_inside_shell_chain(self):
        self.assertIsNotNone(
            _unsafe_root_scan(
                "command -v pytest || find / -name pytest 2>/dev/null"
            )
        )

    def test_blocks_recursive_grep_root(self):
        self.assertIsNotNone(
            _unsafe_root_scan("grep -R pytest /")
        )

    def test_blocks_recursive_ls_root(self):
        self.assertIsNotNone(
            _unsafe_root_scan("ls -R /")
        )

    def test_blocks_du_root(self):
        self.assertIsNotNone(
            _unsafe_root_scan("du -sh /")
        )

    def test_allows_workspace_find(self):
        self.assertIsNone(
            _unsafe_root_scan("find . -name pytest")
        )

    def test_allows_specific_home_directory(self):
        self.assertIsNone(
            _unsafe_root_scan('find "$HOME/.local" -name pytest')
        )

    def test_allows_command_v(self):
        self.assertIsNone(
            _unsafe_root_scan("command -v pytest")
        )


if __name__ == "__main__":
    unittest.main()
