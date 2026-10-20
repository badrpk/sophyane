"""Language analysis must reject uncertainty and hash source semantics."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from sophyane.mutation.adapters import AnalysisResult, CppAdapter, PythonAdapter
from sophyane.mutation.hashing import semantic_diff_hash, semantic_tree_hash


def test_python_parses_and_ignores_source_positions(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("def answer():\n    return 42\n")
    first = PythonAdapter().analyze(source, ())
    source.write_text("\n\n# comment\ndef answer():\n\n    return 42\n")
    second = PythonAdapter().analyze(source, ())

    assert first.ok and second.ok
    assert first.language == "python" and first.path == str(source)
    assert first.failure_boundary is None and first.diagnostics == ""
    assert first.semantic_digest == second.semantic_digest


def test_python_semantic_edit_changes_digest(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("VALUE = 1\n")
    first = PythonAdapter().analyze(source, ())
    source.write_text("VALUE = 2\n")

    assert first.semantic_digest != PythonAdapter().analyze(source, ()).semantic_digest


@pytest.mark.parametrize("text", ["def broken(:\n    pass\n", "x = (\n", "return 1\n"])
def test_python_syntax_error_fails_closed(tmp_path: Path, text: str) -> None:
    source = tmp_path / "broken.py"
    source.write_text(text)

    result = PythonAdapter().analyze(source, ())

    assert not result.ok and result.semantic_digest is None
    assert result.failure_boundary == "python_syntax"
    assert result.diagnostics


def test_python_required_function_and_class_names(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("class Widget:\n    async def run(self):\n        pass\n")

    result = PythonAdapter().analyze(source, ("class:Widget", "function:run"))

    assert result.ok and result.semantic_digest


@pytest.mark.parametrize("invariant", ["function:missing", "class:Missing"])
def test_python_missing_invariant_fails_closed(tmp_path: Path, invariant: str) -> None:
    source = tmp_path / "sample.py"
    source.write_text("class Widget:\n    pass\n")

    result = PythonAdapter().analyze(source, (invariant,))

    assert not result.ok and result.semantic_digest is None
    assert result.failure_boundary == "python_invariant"
    assert invariant in result.diagnostics


def test_python_unknown_invariant_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("x = 1\n")

    result = PythonAdapter().analyze(source, ("arbitrary shell command",))

    assert not result.ok and result.failure_boundary == "python_invariant"


def test_python_missing_file_fails_closed(tmp_path: Path) -> None:
    result = PythonAdapter().analyze(tmp_path / "missing.py", ())

    assert not result.ok and result.semantic_digest is None
    assert result.failure_boundary == "python_io"


@pytest.fixture
def clang() -> str:
    compiler = shutil.which("clang++")
    if compiler is None:
        pytest.skip("clang++ unavailable")
    return compiler


def test_cpp_parses_header_with_fixed_include_dir(tmp_path: Path, clang: str) -> None:
    includes = tmp_path / "include"
    includes.mkdir()
    (includes / "widget.hpp").write_text("class Widget {};\n")
    source = tmp_path / "sample.cpp"
    source.write_text('#include "widget.hpp"\nint answer() { return 42; }\n')

    result = CppAdapter(clang, (includes,)).analyze(source, ("function:answer", "class:Widget"))

    assert result.ok, result.diagnostics
    assert result.language == "cpp" and result.path == str(source)
    assert result.semantic_digest and result.failure_boundary is None


def test_cpp_invariants_accept_header_declarations_without_bodies(
    tmp_path: Path, clang: str
) -> None:
    header = tmp_path / "api.hpp"
    header.write_text("class Widget;\nint answer();\n")

    result = CppAdapter(clang).analyze(header, ("class:Widget", "function:answer"))

    assert result.ok, result.diagnostics


def test_cpp_ast_hash_ignores_source_positions(tmp_path: Path, clang: str) -> None:
    source = tmp_path / "sample.cpp"
    source.write_text("int answer() { return 42; }\n")
    first = CppAdapter(clang).analyze(source, ())
    source.write_text("\n// comment\nint answer() { return 42; }\n")
    second = CppAdapter(clang).analyze(source, ())

    assert first.ok and second.ok
    assert first.semantic_digest == second.semantic_digest


def test_cpp_nonzero_diagnostics_fail_closed(tmp_path: Path, clang: str) -> None:
    source = tmp_path / "broken.cpp"
    source.write_text("int answer( {\n")

    result = CppAdapter(clang).analyze(source, ())

    assert not result.ok and result.semantic_digest is None
    assert result.failure_boundary == "cpp_syntax"
    assert result.diagnostics


def test_cpp_missing_compiler_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "sample.cpp"
    source.write_text("int answer() { return 42; }\n")

    result = CppAdapter(str(tmp_path / "missing-clang")).analyze(source, ())

    assert not result.ok and result.semantic_digest is None
    assert result.failure_boundary == "cpp_tool"


@pytest.mark.parametrize(
    "output",
    [
        "{}",
        '{"kind":"TranslationUnitDecl"}',
        '{"kind":"TranslationUnitDecl","inner":"bad"}',
        '{"kind":"TranslationUnitDecl","inner":[{"name":"answer"}]}',
        '{"kind":"TranslationUnitDecl","inner":[{"kind":"FunctionDecl","inner":[{}]}]}',
    ],
)
def test_cpp_unsupported_ast_output_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str
) -> None:
    import subprocess

    source = tmp_path / "sample.cpp"
    source.write_text("int answer() { return 42; }\n")

    def unsupported(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, output, "")

    monkeypatch.setattr(subprocess, "run", unsupported)
    result = CppAdapter().analyze(source, ())

    assert not result.ok and result.semantic_digest is None
    assert result.failure_boundary == "cpp_ast"


def test_cpp_missing_invariant_fails_closed(tmp_path: Path, clang: str) -> None:
    source = tmp_path / "sample.cpp"
    source.write_text("int answer() { return 42; }\n")

    result = CppAdapter(clang).analyze(source, ("function:missing",))

    assert not result.ok and result.semantic_digest is None
    assert result.failure_boundary == "cpp_invariant"


def _result(path: str, digest: str) -> AnalysisResult:
    return AnalysisResult("python", path, True, digest, None, "")


def test_semantic_tree_hash_is_order_independent() -> None:
    first = [_result("b.py", "bbb"), _result("a.py", "aaa")]

    assert semantic_tree_hash(first) == semantic_tree_hash(reversed(first))
    assert semantic_tree_hash(first) != semantic_tree_hash([_result("a.py", "aaa")])


def test_semantic_tree_hash_rejects_failed_analysis() -> None:
    failed = AnalysisResult("python", "a.py", False, None, "python_syntax", "bad")

    with pytest.raises(ValueError):
        semantic_tree_hash([failed])


def test_semantic_tree_hash_rejects_duplicate_paths() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        semantic_tree_hash([_result("pkg/a.py", "old"), _result("pkg/a.py", "new")])


@pytest.mark.parametrize("bad_path", ["/lab/a.py", "../a.py", "pkg/../a.py", r"C:\lab\a.py"])
def test_semantic_tree_hash_rejects_non_relative_paths(bad_path: str) -> None:
    with pytest.raises(ValueError, match="relative"):
        semantic_tree_hash([_result(bad_path, "digest")])


def test_semantic_diff_hash_only_includes_changed_paths() -> None:
    baseline = {"b.py": "old", "a.py": "same"}
    candidate = {"a.py": "same", "b.py": "new"}

    assert semantic_diff_hash(baseline, candidate) == semantic_diff_hash(
        {"b.py": "old"}, {"b.py": "new"}
    )
    assert semantic_diff_hash(baseline, candidate) != semantic_diff_hash(
        {"b.py": "new"}, {"b.py": "old"}
    )
    assert semantic_diff_hash(baseline, baseline) == hashlib.sha256(b"").hexdigest()


@pytest.mark.parametrize("bad_path", ["/lab/a.py", "../a.py", "pkg/../a.py", r"C:\lab\a.py"])
def test_semantic_diff_hash_rejects_non_relative_paths_even_when_unchanged(bad_path: str) -> None:
    with pytest.raises(ValueError, match="relative"):
        semantic_diff_hash({bad_path: "same"}, {bad_path: "same"})
