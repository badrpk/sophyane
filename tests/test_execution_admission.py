from pathlib import Path

from sophyane.capability_flow_graph import default_capability_graph
from sophyane.execution_admission import classify_execution_admission


def test_read_policy_does_not_weaken_write_policy():
    graph = default_capability_graph()

    write = graph.descriptor("local_filesystem")
    read = graph.descriptor("local_filesystem_read")

    assert write.persistent_sink is True
    assert "filesystem_write" in write.side_effects

    assert read.persistent_sink is False
    assert read.side_effects == frozenset()
    assert read.required_verifiers == frozenset(
        {"workspace_boundary"}
    )


def test_list_files_is_read_only():
    result = classify_execution_admission("list files")

    assert result is not None
    assert result.read_only is True
    assert result.policy_capabilities == (
        "local_reasoning",
        "local_filesystem_read",
    )
    assert result.side_effects == frozenset()


def test_list_folders_is_read_only():
    result = classify_execution_admission("list folders")

    assert result is not None
    assert result.read_only is True
    assert result.policy_capabilities[-1] == "local_filesystem_read"


def test_strict_exact_write_requires_write_policy():
    result = classify_execution_admission(
        "Create a file named artifact.txt. "
        "The line must begin X and contain the uppercase words "
        "ONE and TWO joined by underscores. "
        "End the file with exactly one newline."
    )

    assert result is not None
    assert result.read_only is False
    assert result.policy_capabilities[-1] == "local_filesystem"
    assert "filesystem_write" in result.side_effects


def test_python_create_requires_write_and_execution_policy():
    result = classify_execution_admission(
        "create hello.py that prints hello"
    )

    assert result is not None
    assert result.runtime_family == "development.local_coding"
    assert result.read_only is False
    assert result.policy_capabilities == (
        "local_reasoning",
        "local_filesystem",
        "local_process_execution",
    )
    assert "filesystem_write" in result.side_effects
    assert "process_execution" in result.side_effects


def test_explanation_does_not_get_misclassified_as_coding():
    result = classify_execution_admission(
        "explain how to create hello.py"
    )

    assert (
        result is None
        or result.runtime_family != "development.local_coding"
    )


def test_empty_request_has_no_admission():
    assert classify_execution_admission("") is None


def test_classifier_is_workspace_mutation_free(tmp_path):
    before = sorted(
        str(path.relative_to(tmp_path))
        for path in tmp_path.rglob("*")
    )

    classify_execution_admission(
        "list files",
        workspace=tmp_path,
    )

    after = sorted(
        str(path.relative_to(tmp_path))
        for path in tmp_path.rglob("*")
    )

    assert after == before


def test_read_transition_exists():
    graph = default_capability_graph()

    # validate_chain requires a labeled value, but the edge itself is an
    # architectural invariant exercised by the existing graph API.
    assert any(
        edge.source == "local_reasoning"
        and edge.target == "local_filesystem_read"
        for edge in graph._edges
    )
