from sophyane.browser_partial_recovery import _acceptable_rewrite


def test_tiny_semantic_rewrite_is_rejected() -> None:
    previous = "<!doctype html><html><body>" + ("x" * 2200) + "</body></html>"
    assert not _acceptable_rewrite(previous, "<!doctype html><html></html>")


def test_substantial_semantic_rewrite_is_allowed() -> None:
    previous = "<!doctype html><html><body>" + ("x" * 2200) + "</body></html>"
    candidate = "<!doctype html><html><body>" + ("y" * 1800) + "</body></html>"
    assert _acceptable_rewrite(previous, candidate)


def test_missing_rewrite_is_rejected() -> None:
    assert not _acceptable_rewrite("<!doctype html><html><body>game</body></html>", None)
