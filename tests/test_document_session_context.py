from pathlib import Path


def _document(
    tmp_path,
    *,
    name="report.pdf",
    text="Quarterly report\nQ1: 275\nQ2: 310\nQ3: 298\nQ4: 355\n",
):
    from sophyane.document_grounding import (
        GroundedDocument,
    )

    path = (
        tmp_path
        / name
    )

    path.write_bytes(
        b"%PDF-1.4\n%%EOF\n"
    )

    return GroundedDocument(
        path=str(
            path
        ),
        kind="pdf",
        text=text,
        source="test-grounded",
    )


def test_remember_and_retrieve_current_document(
    tmp_path,
):
    from sophyane.document_session_context import (
        clear_current_document,
        current_document,
        remember_grounded_document,
    )

    clear_current_document()

    source = _document(
        tmp_path
    )

    remembered = (
        remember_grounded_document(
            source
        )
    )

    current = (
        current_document()
    )

    assert current is not None
    assert current == remembered
    assert current.kind == "pdf"
    assert "Q1: 275" in current.text


def test_followup_pronoun_is_detected():
    from sophyane.document_session_context import (
        request_refers_to_current_document,
    )

    assert request_refers_to_current_document(
        "summarize it"
    )

    assert request_refers_to_current_document(
        "what does this document say about installation?"
    )

    assert request_refers_to_current_document(
        "now graph the values in it"
    )


def test_unrelated_request_does_not_acquire_document_context(
    tmp_path,
):
    from sophyane.document_session_context import (
        augment_request_with_current_document,
        clear_current_document,
        remember_grounded_document,
    )

    clear_current_document()

    remember_grounded_document(
        _document(
            tmp_path
        )
    )

    request = (
        "what is the weather tomorrow?"
    )

    augmented, document = (
        augment_request_with_current_document(
            request
        )
    )

    assert augmented == request
    assert document is None


def test_followup_is_augmented_with_grounded_document(
    tmp_path,
):
    from sophyane.document_session_context import (
        augment_request_with_current_document,
        clear_current_document,
        remember_grounded_document,
    )

    clear_current_document()

    source = _document(
        tmp_path
    )

    remember_grounded_document(
        source
    )

    augmented, document = (
        augment_request_with_current_document(
            "summarize it"
        )
    )

    assert document is not None
    assert "SOPHYANE_CURRENT_GROUNDED_DOCUMENT" in augmented
    assert "Q1: 275" in augmented
    assert str(
        Path(
            source.path
        ).resolve()
    ) in augmented


def test_clear_current_document_removes_context(
    tmp_path,
):
    from sophyane.document_session_context import (
        clear_current_document,
        current_document,
        remember_grounded_document,
    )

    remember_grounded_document(
        _document(
            tmp_path
        )
    )

    assert current_document() is not None

    clear_current_document()

    assert current_document() is None
