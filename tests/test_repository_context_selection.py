from __future__ import annotations

from pathlib import Path

from sophyane.coding_runtime import RepositoryIndex


def test_large_first_match_does_not_starve_other_relevant_file(
    tmp_path: Path,
) -> None:
    (tmp_path / "alpha_service.py").write_text(
        "class AlphaService:\n"
        + ("    value = 'A'\n" * 2000),
        encoding="utf-8",
    )
    (tmp_path / "alpha_worker.py").write_text(
        "def alpha_worker():\n"
        "    return 'SECOND_RELEVANT_FILE'\n",
        encoding="utf-8",
    )

    index = RepositoryIndex(tmp_path)
    index.build()

    context = index.context("alpha", max_chars=1200)

    assert "### alpha_service.py" in context
    assert "### alpha_worker.py" in context
    assert "SECOND_RELEVANT_FILE" in context


def test_direct_hits_precede_dependency_neighbors(
    tmp_path: Path,
) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()

    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "helper.py").write_text(
        "def helper():\n"
        "    return 'DEPENDENCY_MARKER'\n",
        encoding="utf-8",
    )
    (tmp_path / "checkout.py").write_text(
        "from pkg.helper import helper\n\n"
        "class CheckoutService:\n"
        "    def total(self):\n"
        "        return helper()\n",
        encoding="utf-8",
    )

    index = RepositoryIndex(tmp_path)
    index.build()

    paths = index.ranked_context_paths("CheckoutService")

    assert paths[0] == "checkout.py"
    assert "pkg/helper.py" in paths
    assert paths.index("checkout.py") < paths.index("pkg/helper.py")


def test_src_layout_dependency_is_resolved(
    tmp_path: Path,
) -> None:
    package = tmp_path / "src" / "shop"
    package.mkdir(parents=True)

    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "pricing.py").write_text(
        "def price():\n"
        "    return 42\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text(
        "from shop.pricing import price\n\n"
        "class CartApplication:\n"
        "    pass\n",
        encoding="utf-8",
    )

    index = RepositoryIndex(tmp_path)
    index.build()

    paths = index.ranked_context_paths("CartApplication")

    assert paths[0] == "app.py"
    assert "src/shop/pricing.py" in paths


def test_context_remains_within_requested_content_budget(
    tmp_path: Path,
) -> None:
    for index_value in range(4):
        (tmp_path / f"target_{index_value}.py").write_text(
            f"def target_{index_value}():\n"
            + ("    return 'x'\n" * 200),
            encoding="utf-8",
        )

    index = RepositoryIndex(tmp_path)
    index.build()

    context = index.context("target", max_chars=1000)

    payload_chars = sum(
        len(chunk.split("\n", 1)[1])
        for chunk in context.split("\n\n")
        if "\n" in chunk
    )

    assert payload_chars <= 1000


def test_existing_single_symbol_context_contract(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text(
        "class Inventory:\n"
        "    def total(self):\n"
        "        return 42\n",
        encoding="utf-8",
    )

    index = RepositoryIndex(tmp_path)
    index.build()

    context = index.context("Inventory")

    assert "### app.py" in context
    assert "class Inventory" in context
