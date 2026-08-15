from __future__ import annotations

from pathlib import Path

from sophyane.continual import engine


def test_packaged_continual_cpp_sources_exist() -> None:
    package_sources = (
        Path(engine.__file__).resolve().parent
        / "cpp"
    )

    assert (
        package_sources
        / "src"
        / "train_core.cpp"
    ).is_file()

    assert (
        package_sources
        / "include"
        / "sophyane_train.hpp"
    ).is_file()

    assert (
        package_sources
        / "CMakeLists.txt"
    ).is_file()


def test_cpp_sources_prefers_packaged_resource() -> None:
    resolved = engine._cpp_sources()

    assert (
        resolved
        / "src"
        / "train_core.cpp"
    ).is_file()
