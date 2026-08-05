from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
}

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
    ".sh",
}


def test_repository_contains_no_ollama_references() -> None:
    violations: list[str] = []

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path.suffix.casefold() not in TEXT_SUFFIXES:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        forbidden = "olla" + "ma"
        if forbidden in text.casefold():
            violations.append(str(path.relative_to(ROOT)))

    assert not violations, (
        "Forbidden legacy local-provider references remain:\n"
        + "\n".join(violations)
    )
