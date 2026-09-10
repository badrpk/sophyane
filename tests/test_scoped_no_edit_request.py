from __future__ import annotations

from sophyane.adaptive_execution import (
    _explicit_no_edit_request,
)


def test_scoped_do_not_modify_other_files_is_not_global_no_edit():
    request = """
Modify the repository file targeted_patch_e2e_probe.txt.

Use the repository execution path.

Replace exactly:
BOOTSTRAP_BEFORE

with exactly:
BOOTSTRAP_AFTER

Do not modify any other file.
Do not merely explain the change.
Execute the repository edit and return the verified execution result.
"""

    assert (
        _explicit_no_edit_request(request)
        is False
    )


def test_actual_global_do_not_modify_request_remains_no_edit():
    request = """
Inspect targeted_patch_e2e_probe.txt.
Do not modify the repository.
Only report what you find.
"""

    assert (
        _explicit_no_edit_request(request)
        is True
    )
