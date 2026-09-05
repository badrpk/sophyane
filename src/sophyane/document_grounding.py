"""Provider-independent grounded document ingestion.

One shared authority for turning real user-accessible files into grounded
content that can be consumed by Sophyane's existing intelligence and visual
dispatch layers.

Supported deterministic sources:
- PDF: reuse Sophyane's existing PDF/text extraction authority when callable,
  otherwise use an available local extraction backend.
- CSV: Python stdlib csv.
- JSON: Python stdlib json.
- TXT/MD: direct bounded text read.

This module never invents document contents or graph data.
"""

from __future__ import annotations

from dataclasses import dataclass
import csv
import importlib
import inspect
import io
import json
from pathlib import Path
import re
import subprocess
from typing import Any


# SOPHYANE_SHARED_DOCUMENT_GROUNDING_V1


_MAX_TEXT_CHARS = 120_000
_MAX_ROWS = 2_000
_MAX_FILE_BYTES = 40 * 1024 * 1024


@dataclass(frozen=True)
class GroundedDocument:
    path: str
    kind: str
    text: str
    source: str
    rows: tuple[tuple[str, ...], ...] = ()
    structured: Any = None


def _bounded_text(
    value: Any,
) -> str:
    return str(
        value
        or ""
    )[
        :_MAX_TEXT_CHARS
    ]


def _validate_file(
    path: Path,
) -> Path:
    resolved = (
        Path(path)
        .expanduser()
        .resolve()
    )

    if not resolved.is_file():
        raise FileNotFoundError(
            str(resolved)
        )

    size = resolved.stat().st_size

    if size > _MAX_FILE_BYTES:
        raise ValueError(
            "document exceeds grounding size limit: "
            + str(size)
        )

    return resolved


def _candidate_memory_extractors():
    """Yield existing Sophyane extraction callables conservatively."""
    try:
        module = importlib.import_module(
            "sophyane.memory_architecture"
        )
    except Exception:
        return

    for name in dir(module):
        lowered = name.casefold()

        if not any(
            marker in lowered
            for marker in (
                "extract",
                "document",
                "content",
                "text",
                "file",
            )
        ):
            continue

        value = getattr(
            module,
            name,
            None,
        )

        if not callable(value):
            continue

        try:
            signature = inspect.signature(
                value
            )
        except Exception:
            continue

        parameters = list(
            signature.parameters.values()
        )

        if len(parameters) != 1:
            continue

        yield name, value


def _reuse_existing_pdf_extractor_unvalidated(
    path: Path,
) -> tuple[str, str] | None:
    """Reuse a compatible existing Sophyane extractor if exposed."""
    for name, function in _candidate_memory_extractors() or ():
        try:
            result = function(
                path
            )
        except (
            TypeError,
            ValueError,
            OSError,
            RuntimeError,
            FileNotFoundError,
        ):
            continue
        except Exception:
            continue

        if isinstance(
            result,
            str,
        ):
            text = result.strip()

            if text:
                return (
                    _bounded_text(
                        text
                    ),
                    (
                        "sophyane.memory_architecture."
                        + name
                    ),
                )

        if isinstance(
            result,
            dict,
        ):
            for key in (
                "text",
                "content",
                "document",
                "body",
            ):
                candidate = result.get(
                    key
                )

                if isinstance(
                    candidate,
                    str,
                ) and candidate.strip():
                    return (
                        _bounded_text(
                            candidate
                        ),
                        (
                            "sophyane.memory_architecture."
                            + name
                        ),
                    )

    return None


# SOPHYANE_PDF_LEGACY_EXTRACTOR_VALIDATION_V4
def _pdf_grounded_candidate_text(
    candidate,
) -> str:
    """Return candidate text without changing the candidate contract."""

    if candidate is None:
        return ""

    if isinstance(
        candidate,
        str,
    ):
        return candidate.strip()

    value = getattr(
        candidate,
        "text",
        None,
    )

    if value is not None:
        return str(
            value
            or ""
        ).strip()

    if isinstance(
        candidate,
        (
            tuple,
            list,
        ),
    ):
        for item in candidate:
            if isinstance(
                item,
                str,
            ):
                return item.strip()

            nested = getattr(
                item,
                "text",
                None,
            )

            if nested is not None:
                return str(
                    nested
                    or ""
                ).strip()

    if isinstance(
        candidate,
        dict,
    ):
        for key in (
            "text",
            "content",
            "body",
        ):
            if key in candidate:
                return str(
                    candidate.get(
                        key
                    )
                    or ""
                ).strip()

    return ""


def _pdf_text_is_real_content(
    *,
    path: Path,
    text: str,
) -> bool:
    """Reject metadata/path strings masquerading as PDF extraction."""

    value = str(
        text
        or ""
    ).strip()

    if not value:
        return False

    resolved = path.expanduser().resolve()

    path_forms = {
        str(
            resolved
        ),
        resolved.as_posix(),
        str(
            path
        ),
        path.as_posix(),
    }

    if value in path_forms:
        return False

    #
    # The observed failure was exactly a short pathname returned by
    # memory_architecture.normalized_text().
    #
    if (
        resolved.name in value
        and "\n" not in value
        and len(value) < 256
    ):
        return False

    return True


def _reuse_existing_pdf_extractor(
    path: Path,
):
    """Reuse legacy extraction only when it produced real document content."""

    candidate = (
        _reuse_existing_pdf_extractor_unvalidated(
            path
        )
    )

    if candidate is None:
        return None

    text = _pdf_grounded_candidate_text(
        candidate
    )

    if not _pdf_text_is_real_content(
        path=path,
        text=text,
    ):
        return None

    return candidate



def _pdf_via_python_library(
    path: Path,
) -> tuple[str, str] | None:
    """Use a locally available PDF library without network/provider calls."""
    backends = (
        "pypdf",
        "PyPDF2",
    )

    for module_name in backends:
        try:
            module = importlib.import_module(
                module_name
            )
        except Exception:
            continue

        reader_type = getattr(
            module,
            "PdfReader",
            None,
        )

        if reader_type is None:
            continue

        try:
            reader = reader_type(
                str(path)
            )

            pieces = []

            for page in getattr(
                reader,
                "pages",
                (),
            ):
                text = (
                    page.extract_text()
                    or ""
                )

                if text.strip():
                    pieces.append(
                        text
                    )

                if sum(
                    len(piece)
                    for piece in pieces
                ) >= _MAX_TEXT_CHARS:
                    break

            joined = "\n\n".join(
                pieces
            ).strip()

            if joined:
                return (
                    _bounded_text(
                        joined
                    ),
                    module_name,
                )

        except Exception:
            continue

    try:
        fitz = importlib.import_module(
            "fitz"
        )

        document = fitz.open(
            str(path)
        )

        pieces = []

        try:
            for page in document:
                text = (
                    page.get_text(
                        "text"
                    )
                    or ""
                )

                if text.strip():
                    pieces.append(
                        text
                    )

                if sum(
                    len(piece)
                    for piece in pieces
                ) >= _MAX_TEXT_CHARS:
                    break

        finally:
            document.close()

        joined = "\n\n".join(
            pieces
        ).strip()

        if joined:
            return (
                _bounded_text(
                    joined
                ),
                "fitz",
            )

    except Exception:
        pass

    return None


def _pdf_via_system_tool(
    path: Path,
) -> tuple[str, str] | None:
    import shutil

    executable = shutil.which(
        "pdftotext"
    )

    if not executable:
        return None

    try:
        completed = subprocess.run(
            [
                executable,
                "-layout",
                str(path),
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception:
        return None

    if completed.returncode != 0:
        return None

    text = completed.stdout.strip()

    if not text:
        return None

    return (
        _bounded_text(
            text
        ),
        "pdftotext",
    )


def _ground_pdf(
    path: Path,
) -> GroundedDocument:
    existing = (
        _reuse_existing_pdf_extractor(
            path
        )
    )

    if existing is not None:
        text, source = existing

        return GroundedDocument(
            path=str(path),
            kind="pdf",
            text=text,
            source=source,
        )

    local = _pdf_via_python_library(
        path
    )

    if local is not None:
        text, source = local

        return GroundedDocument(
            path=str(path),
            kind="pdf",
            text=text,
            source=source,
        )

    system = _pdf_via_system_tool(
        path
    )

    if system is not None:
        text, source = system

        return GroundedDocument(
            path=str(path),
            kind="pdf",
            text=text,
            source=source,
        )

    raise RuntimeError(
        "No usable local PDF text extraction authority is available"
    )


def _ground_csv(
    path: Path,
) -> GroundedDocument:
    text = path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )

    reader = csv.reader(
        io.StringIO(
            text
        )
    )

    rows: list[tuple[str, ...]] = []

    for index, row in enumerate(
        reader
    ):
        if index >= _MAX_ROWS:
            break

        rows.append(
            tuple(
                str(value)
                for value in row
            )
        )

    normalized = "\n".join(
        ", ".join(
            row
        )
        for row in rows
    )

    return GroundedDocument(
        path=str(path),
        kind="csv",
        text=_bounded_text(
            normalized
        ),
        source="python.csv",
        rows=tuple(
            rows
        ),
    )


def _json_to_grounded_text(
    value: Any,
    *,
    prefix: str = "",
    out: list[str] | None = None,
) -> list[str]:
    if out is None:
        out = []

    if len(out) >= _MAX_ROWS:
        return out

    if isinstance(
        value,
        dict,
    ):
        for key, child in value.items():
            child_prefix = (
                f"{prefix}.{key}"
                if prefix
                else str(key)
            )

            _json_to_grounded_text(
                child,
                prefix=child_prefix,
                out=out,
            )

            if len(out) >= _MAX_ROWS:
                break

        return out

    if isinstance(
        value,
        list,
    ):
        for index, child in enumerate(
            value
        ):
            child_prefix = (
                f"{prefix}[{index}]"
                if prefix
                else str(index + 1)
            )

            _json_to_grounded_text(
                child,
                prefix=child_prefix,
                out=out,
            )

            if len(out) >= _MAX_ROWS:
                break

        return out

    if isinstance(
        value,
        (
            int,
            float,
            str,
            bool,
        ),
    ) or value is None:
        label = (
            prefix
            or "value"
        )

        out.append(
            f"{label}: {value}"
        )

    return out


def _ground_json(
    path: Path,
) -> GroundedDocument:
    data = json.loads(
        path.read_text(
            encoding="utf-8",
            errors="strict",
        )
    )

    lines = _json_to_grounded_text(
        data
    )

    return GroundedDocument(
        path=str(path),
        kind="json",
        text=_bounded_text(
            "\n".join(
                lines
            )
        ),
        source="python.json",
        structured=data,
    )


def ground_document(
    path: Path | str,
) -> GroundedDocument:
    resolved = _validate_file(
        Path(
            path
        )
    )

    suffix = resolved.suffix.casefold()

    if suffix == ".pdf":
        return _ground_pdf(
            resolved
        )

    if suffix == ".csv":
        return _ground_csv(
            resolved
        )

    if suffix == ".json":
        return _ground_json(
            resolved
        )

    if suffix in {
        ".txt",
        ".md",
        ".markdown",
    }:
        return GroundedDocument(
            path=str(resolved),
            kind=suffix.lstrip("."),
            text=_bounded_text(
                resolved.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            ),
            source="direct-text",
        )

    raise ValueError(
        "unsupported grounded document type: "
        + suffix
    )


_FILE_REFERENCE = re.compile(
    r"""
    (?:
        ["']
        (?P<quoted>[^"']+\.(?:pdf|csv|json|txt|md))
        ["']
        |
        (?P<plain>
            (?:
                ~/
                |
                /
                |
                \./
                |
                \.\./
            )?
            [^\s,;]+
            \.(?:pdf|csv|json|txt|md)
        )
    )
    """,
    flags=(
        re.IGNORECASE
        | re.VERBOSE
    ),
)


def referenced_document_paths(
    request: str,
    *,
    workspace: Path,
) -> tuple[Path, ...]:
    text = str(
        request
        or ""
    )

    workspace = (
        Path(workspace)
        .expanduser()
        .resolve()
    )

    found: list[Path] = []
    seen: set[Path] = set()

    for match in _FILE_REFERENCE.finditer(
        text
    ):
        raw = (
            match.group(
                "quoted"
            )
            or match.group(
                "plain"
            )
            or ""
        ).strip()

        if not raw:
            continue

        candidate = Path(
            raw
        ).expanduser()

        if not candidate.is_absolute():
            candidate = (
                workspace
                / candidate
            )

        candidate = candidate.resolve()

        if candidate in seen:
            continue

        if candidate.is_file():
            seen.add(
                candidate
            )

            found.append(
                candidate
            )

    return tuple(
        found
    )


def ground_request_documents(
    request: str,
    *,
    workspace: Path,
) -> tuple[GroundedDocument, ...]:
    documents = []

    for path in referenced_document_paths(
        request,
        workspace=workspace,
    ):
        try:
            documents.append(
                ground_document(
                    path
                )
            )
        except (
            OSError,
            ValueError,
            RuntimeError,
            json.JSONDecodeError,
        ):
            continue

    return tuple(
        documents
    )


def augment_request_with_grounded_documents(
    request: str,
    *,
    workspace: Path,
) -> tuple[str, tuple[GroundedDocument, ...]]:
    documents = ground_request_documents(
        request,
        workspace=workspace,
    )

    if not documents:
        return (
            str(
                request
                or ""
            ),
            (),
        )

    sections = [
        str(
            request
            or ""
        ).rstrip(),
        "",
        "BEGIN_SOPHYANE_GROUNDED_DOCUMENTS",
    ]

    for index, document in enumerate(
        documents,
        start=1,
    ):
        sections.extend(
            (
                (
                    f"DOCUMENT_{index}_PATH="
                    f"{document.path}"
                ),
                (
                    f"DOCUMENT_{index}_TYPE="
                    f"{document.kind}"
                ),
                (
                    f"DOCUMENT_{index}_SOURCE="
                    f"{document.source}"
                ),
                (
                    f"DOCUMENT_{index}_CONTENT:"
                ),
                document.text,
                (
                    f"END_DOCUMENT_{index}"
                ),
            )
        )

    sections.append(
        "END_SOPHYANE_GROUNDED_DOCUMENTS"
    )

    return (
        "\n".join(
            sections
        ),
        documents,
    )


__all__ = [
    "GroundedDocument",
    "augment_request_with_grounded_documents",
    "ground_document",
    "ground_request_documents",
    "referenced_document_paths",
]
