import ast
import inspect

import sophyane.providers.fallback as fallback


def _source() -> str:
    return inspect.getsource(fallback)


def _tree() -> ast.Module:
    return ast.parse(_source())


def _string_set_values(node: ast.AST) -> set[str]:
    if not isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return set()

    values = set()

    for item in node.elts:
        if (
            isinstance(item, ast.Constant)
            and isinstance(item.value, str)
        ):
            values.add(item.value)

    return values


def _strict_external_membership_nodes():
    matches = []

    for node in ast.walk(_tree()):
        if not isinstance(node, ast.Compare):
            continue

        if len(node.ops) != 1:
            continue

        if not isinstance(node.ops[0], ast.In):
            continue

        if not (
            isinstance(node.left, ast.Name)
            and node.left.id == "session_mode"
        ):
            continue

        if len(node.comparators) != 1:
            continue

        values = _string_set_values(
            node.comparators[0]
        )

        if {
            "cloud_llm",
            "nifdu_llm",
        }.issubset(values):
            matches.append(node)

    return matches


def _function(name: str) -> ast.FunctionDef:
    for node in _tree().body:
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == name
        ):
            return node

    raise AssertionError(
        f"function not found: {name}"
    )


def test_nifdu_session_is_explicit_terminal_provider_authority():
    text = _source()

    assert '"cloud_llm"' in text
    assert '"nifdu_llm"' in text


def test_nifdu_authority_participates_in_strict_external_session_check():
    matches = _strict_external_membership_nodes()

    assert matches, (
        "no session_mode membership check contains both "
        "cloud_llm and nifdu_llm"
    )


def test_nifdu_strict_mode_cannot_enable_local_rescue_from_persisted_config():
    text = _source()

    assert _strict_external_membership_nodes()

    # Existing rescue mechanism remains gated by strict_cloud.
    assert "allow_cloud_local_rescue" in text
    assert "not strict_cloud" in text


def test_provider_chain_builder_recognizes_nifdu_as_strict_session():
    builder = _function(
        "build_fallback_provider"
    )

    found = False

    for node in ast.walk(builder):
        if not isinstance(node, ast.Compare):
            continue

        if len(node.ops) != 1:
            continue

        if not isinstance(node.ops[0], ast.In):
            continue

        if not (
            isinstance(node.left, ast.Name)
            and node.left.id == "session_mode"
        ):
            continue

        if len(node.comparators) != 1:
            continue

        values = _string_set_values(
            node.comparators[0]
        )

        if {
            "cloud_llm",
            "nifdu_llm",
        }.issubset(values):
            found = True
            break

    assert found, (
        "build_fallback_provider does not classify "
        "nifdu_llm with cloud_llm"
    )


def test_nifdu_authority_does_not_remove_existing_explicit_mode4_policy():
    text = _source()

    assert (
        "SOPHYANE_MODE4_EXTERNAL_FAILOVER"
        in text
    )

    assert (
        "SOPHYANE_DISABLE_LOCAL_FALLBACK"
        in text
    )


def test_exactly_two_nifdu_strict_authority_memberships_exist():
    matches = _strict_external_membership_nodes()

    # One is the rescue/terminal-authority decision,
    # one is the fallback-provider-chain decision.
    assert len(matches) == 2
