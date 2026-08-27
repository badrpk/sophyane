from __future__ import annotations

from pathlib import Path

from sophyane.fast_local_coding import (
    try_fast_local_python_coding,
)


STARTER = """def normalize(value):
    raise NotImplementedError
"""

TESTS = """from sample import normalize


def test_value():
    assert normalize(" A ") == "a"
"""


def workspace(tmp_path: Path) -> Path:
    (tmp_path / "sample.py").write_text(
        STARTER,
        encoding="utf-8",
    )

    (tmp_path / "test_sample.py").write_text(
        TESTS,
        encoding="utf-8",
    )

    return tmp_path


def test_fast_path_accepts_first_verified_candidate(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    calls = []

    def backend(prompt: str, system: str) -> str:
        calls.append((prompt, system))
        return """def normalize(value):
    return str(value).strip().lower()
"""

    result = try_fast_local_python_coding(
        request="Implement normalize in sample.py",
        workspace=root,
        backend=backend,
    )

    assert result.attempted is True
    assert result.success is True
    assert result.model_calls == 1
    assert result.passed == 1
    assert len(calls) == 1


def test_fast_path_uses_one_compact_repair(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    calls = []

    responses = iter(
        [
            """def normalize(value):
    return str(value)
""",
            """def normalize(value):
    return str(value).strip().lower()
""",
        ]
    )

    def backend(prompt: str, system: str) -> str:
        calls.append((prompt, system))
        return next(responses)

    result = try_fast_local_python_coding(
        request="Fix sample.py",
        workspace=root,
        backend=backend,
    )

    assert result.attempted is True
    assert result.success is True
    assert result.model_calls == 2
    assert result.passed == 1
    assert "PYTEST FAILURE EVIDENCE" in calls[1][0]


def test_fast_path_restores_original_after_failure(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    original = (
        root / "sample.py"
    ).read_text(encoding="utf-8")

    def backend(prompt: str, system: str) -> str:
        return """def normalize(value):
    return "wrong"
"""

    result = try_fast_local_python_coding(
        request="Fix sample.py",
        workspace=root,
        backend=backend,
    )

    assert result.attempted is True
    assert result.success is False

    assert (
        root / "sample.py"
    ).read_text(
        encoding="utf-8"
    ) == original


def test_fast_path_declines_multiple_python_targets(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)

    called = False

    def backend(prompt: str, system: str) -> str:
        nonlocal called
        called = True
        return ""

    result = try_fast_local_python_coding(
        request="Update sample.py and other.py",
        workspace=root,
        backend=backend,
    )

    assert result.attempted is False
    assert called is False


def test_fast_path_declines_without_pytest_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / "sample.py").write_text(
        STARTER,
        encoding="utf-8",
    )

    def backend(prompt: str, system: str) -> str:
        raise AssertionError(
            "backend must not run"
        )

    result = try_fast_local_python_coding(
        request="Fix sample.py",
        workspace=tmp_path,
        backend=backend,
    )

    assert result.attempted is False


def test_fast_path_accepts_filename_before_sentence_period(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    calls = []

    def backend(prompt: str, system: str) -> str:
        calls.append((prompt, system))
        return """def normalize(value):
    return str(value).strip().lower()
"""

    result = try_fast_local_python_coding(
        request=(
            "Implement normalize(value) in sample.py. "
            "Do not modify tests."
        ),
        workspace=root,
        backend=backend,
    )

    assert result.attempted is True
    assert result.success is True
    assert result.path == "sample.py"
    assert result.model_calls == 1
    assert len(calls) == 1


def test_fast_path_does_not_truncate_longer_extension(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    called = False

    def backend(prompt: str, system: str) -> str:
        nonlocal called
        called = True
        return ""

    result = try_fast_local_python_coding(
        request="Inspect sample.py.bak only.",
        workspace=root,
        backend=backend,
    )

    assert result.attempted is False
    assert called is False


def test_repair_prompt_contains_objective_assertion_guidance() -> None:
    from sophyane.fast_local_coding import _repair_prompt

    value = _repair_prompt(
        "Fix sample.py",
        "sample.py",
        "def normalize(value):\n    return value\n",
        "E AssertionError: assert 'a__b' == 'a_b'",
    )

    assert "Compare each reported actual value with the expected value." in value
    assert "Preserve behavior for tests that already pass." in value
    assert "Include every import required by the returned source." in value
    assert "Do not special-case test names or literal test inputs." in value


def test_deterministic_string_conversion_contradiction_closure(
    tmp_path: Path,
) -> None:
    (tmp_path / "sample.py").write_text(
        """def normalize(value):
    raise NotImplementedError
""",
        encoding="utf-8",
    )

    (tmp_path / "test_sample.py").write_text(
        """from sample import normalize


def test_string():
    assert normalize(" A ") == "a"


def test_integer():
    assert normalize(123) == "123"
""",
        encoding="utf-8",
    )

    responses = iter(
        [
            """def normalize(value):
    if not isinstance(value, str):
        return "anonymous"
    return value.strip().lower()
""",
            """def normalize(value):
    if not isinstance(value, str):
        return "anonymous"
    return value.strip().lower()
""",
        ]
    )

    calls = []

    def backend(prompt: str, system: str) -> str:
        calls.append((prompt, system))
        return next(responses)

    result = try_fast_local_python_coding(
        request=(
            "Implement normalize in sample.py. "
            "Accept any value. Convert it to string. "
            "Strip whitespace and lowercase it."
        ),
        workspace=tmp_path,
        backend=backend,
        max_model_calls=2,
    )

    assert result.attempted is True
    assert result.success is True
    assert result.model_calls == 2
    assert result.passed == 2
    assert result.total == 2
    assert (
        "deterministic string-conversion contradiction"
        in result.reason
    )
    assert len(calls) == 2

    final = (
        tmp_path
        / "sample.py"
    ).read_text(
        encoding="utf-8",
    )

    assert "return \"anonymous\"" not in final
    assert normalize_source_contains_str_call(final)


def normalize_source_contains_str_call(
    source: str,
) -> bool:
    import ast

    tree = ast.parse(source)

    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        for node in ast.walk(tree)
    )


def test_deterministic_closure_declines_without_explicit_contract(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    original = (
        root
        / "sample.py"
    ).read_text(
        encoding="utf-8",
    )

    def backend(prompt: str, system: str) -> str:
        return """def normalize(value):
    if not isinstance(value, str):
        return "anonymous"
    return value
"""

    result = try_fast_local_python_coding(
        request="Fix sample.py",
        workspace=root,
        backend=backend,
        max_model_calls=2,
    )

    assert result.attempted is True
    assert result.success is False

    assert (
        root
        / "sample.py"
    ).read_text(
        encoding="utf-8",
    ) == original


def test_deterministic_unhashable_equality_contradiction_closure(
    tmp_path: Path,
) -> None:
    (tmp_path / "unique.py").write_text(
        """def unique_preserve(values):
    raise NotImplementedError
""",
        encoding="utf-8",
    )

    (tmp_path / "test_unique.py").write_text(
        """from unique import unique_preserve


def test_hashable():
    assert unique_preserve([1, 2, 1]) == [1, 2]


def test_unhashable():
    assert unique_preserve([[1], [2], [1]]) == [[1], [2]]
""",
        encoding="utf-8",
    )

    generated = """def unique_preserve(values):
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
"""

    calls = []

    def backend(
        prompt: str,
        system: str,
    ) -> str:
        calls.append(
            (prompt, system)
        )
        return generated

    result = try_fast_local_python_coding(
        request=(
            "Implement unique_preserve(values) in unique.py. "
            "Preserve original order. "
            "Equality semantics should match normal Python equality. "
            "Must work for both hashable and unhashable values. "
            "Do not modify tests."
        ),
        workspace=tmp_path,
        backend=backend,
        max_model_calls=2,
    )

    assert result.attempted is True
    assert result.success is True
    assert result.model_calls == 2
    assert result.passed == 2
    assert result.total == 2
    assert (
        "unhashable-equality contradiction"
        in result.reason
    )

    assert len(calls) == 2

    source = (
        tmp_path
        / "unique.py"
    ).read_text(
        encoding="utf-8",
    )

    assert "seen = set()" not in source
    assert "any(" in source


def test_unhashable_equality_closure_requires_explicit_contract(
    tmp_path: Path,
) -> None:
    (tmp_path / "unique.py").write_text(
        """def unique_preserve(values):
    raise NotImplementedError
""",
        encoding="utf-8",
    )

    (tmp_path / "test_unique.py").write_text(
        """from unique import unique_preserve


def test_unhashable():
    assert unique_preserve([[1], [1]]) == [[1]]
""",
        encoding="utf-8",
    )

    original = (
        tmp_path
        / "unique.py"
    ).read_text(
        encoding="utf-8",
    )

    generated = """def unique_preserve(values):
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
"""

    def backend(
        prompt: str,
        system: str,
    ) -> str:
        return generated

    result = try_fast_local_python_coding(
        request="Implement unique_preserve(values) in unique.py.",
        workspace=tmp_path,
        backend=backend,
        max_model_calls=2,
    )

    assert result.attempted is True
    assert result.success is False

    assert (
        tmp_path
        / "unique.py"
    ).read_text(
        encoding="utf-8",
    ) == original
