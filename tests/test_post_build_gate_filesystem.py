from __future__ import annotations

import unittest

from sophyane.request_classification import requires_post_build_menu


class PostBuildGateFilesystemTests(unittest.TestCase):
    def test_largest_file_request_does_not_open_project_menu(self):
        self.assertFalse(
            requires_post_build_menu(
                "find the largest file in my computer"
            )
        )

    def test_live_steered_multi_scope_request_is_read_only(self):
        request = """
        CURRENT AUTHORITATIVE USER REQUEST

        Original goal:
        find the largest file in my computer

        Live instructions received after the original request:
        1. also find the largest file in this workspace

        Retain every non-conflicting requirement in planning,
        implementation, validation, and the final result.
        """

        self.assertFalse(requires_post_build_menu(request))

    def test_project_boilerplate_does_not_override_filesystem_intent(self):
        request = """
        Find the largest file in this workspace.

        Internal project implementation and validation guidance.
        """

        self.assertFalse(requires_post_build_menu(request))

    def test_browser_project_still_opens_menu(self):
        self.assertTrue(
            requires_post_build_menu(
                "Build a responsive snake game as a complete "
                "index.html project"
            )
        )

    def test_backend_project_still_opens_menu(self):
        self.assertTrue(
            requires_post_build_menu(
                "Create a Python REST API backend project"
            )
        )

    def test_project_continuation_still_opens_menu(self):
        self.assertTrue(
            requires_post_build_menu(
                "Continue project and improve the existing dashboard"
            )
        )


if __name__ == "__main__":
    unittest.main()
