"""Local privacy and secret-sanitization helpers for Sophyane.

The module deliberately contains no user-specific credentials or identifiers.
Detection is based only on generic secret and PII formats.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


_SECRET_PATTERNS: tuple[
    tuple[re.Pattern[str], str],
    ...,
] = (
    (
        re.compile(
            r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b"
        ),
        "<REDACTED_SECRET_KEY>",
    ),
    (
        re.compile(
            r"\bpk_(?:live|test)_[A-Za-z0-9]{16,}\b"
        ),
        "<REDACTED_PUBLIC_KEY>",
    ),
    (
        re.compile(
            r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"
        ),
        "<REDACTED_GITHUB_TOKEN>",
    ),
    (
        re.compile(
            r"\bAIza[0-9A-Za-z_-]{20,}\b"
        ),
        "<REDACTED_API_KEY>",
    ),
    (
        re.compile(
            r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b"
        ),
        "Bearer <REDACTED_TOKEN>",
    ),
    (
        re.compile(
            r"(?i)\b"
            r"(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
            r"client[_-]?secret|password|passwd|secret)"
            r"\s*[:=]\s*"
            r"([\"']?)"
            r"[^\s,\"']{8,}"
            r"\1"
        ),
        "<REDACTED_CREDENTIAL>",
    ),
    (
        re.compile(
            r"\b[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}\b"
        ),
        "<REDACTED_IBAN>",
    ),
    (
        re.compile(
            r"\b[A-Za-z0-9._%+-]+"
            r"@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        ),
        "<REDACTED_EMAIL>",
    ),
    (
        re.compile(
            r"(?<!\d)"
            r"(?:\+?[1-9]\d{7,14})"
            r"(?!\d)"
        ),
        "<REDACTED_PHONE>",
    ),
)


class ZeroKnowledgePrivacyVault:
    """Sanitize sensitive text and keep secrets in local-only storage."""

    def __init__(
        self,
        secrets_path: Path | None = None,
    ) -> None:
        self.secrets_path = (
            Path(secrets_path)
            if secrets_path is not None
            else (
                Path.home()
                / ".config"
                / "sophyane"
                / "secrets.env"
            )
        )

        self.secrets_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if not self.secrets_path.exists():
            self.secrets_path.write_text(
                "# Sophyane local private secrets\n",
                encoding="utf-8",
            )

        try:
            os.chmod(
                self.secrets_path,
                0o600,
            )
        except OSError:
            # Some platforms/filesystems do not expose POSIX permissions.
            pass

    def sanitize_code_chunk(
        self,
        code_text: str,
    ) -> str:
        """Return text with common secrets and PII replaced."""

        sanitized = str(
            code_text
        )

        for pattern, replacement in _SECRET_PATTERNS:
            sanitized = pattern.sub(
                replacement,
                sanitized,
            )

        return sanitized

    def get_or_prompt_secret(
        self,
        key: str,
        default_val: str = "",
    ) -> str:
        """Return a secret from environment or the local secrets file.

        Despite the historical method name, this function never performs
        interactive prompting. Missing values return ``default_val``.
        """

        normalized_key = str(
            key
        ).strip()

        if not normalized_key:
            return default_val

        value = os.getenv(
            normalized_key,
            "",
        )

        if value:
            return value

        if not self.secrets_path.is_file():
            return default_val

        try:
            lines = self.secrets_path.read_text(
                encoding="utf-8",
            ).splitlines()
        except OSError:
            return default_val

        prefix = (
            normalized_key
            + "="
        )

        for line in lines:
            stripped = line.strip()

            if (
                not stripped
                or stripped.startswith("#")
                or not stripped.startswith(prefix)
            ):
                continue

            return (
                stripped.split(
                    "=",
                    1,
                )[1]
                .strip()
                .strip("\"'")
            )

        return default_val

    def status(
        self,
    ) -> dict[str, Any]:
        """Return non-secret privacy-vault status information."""

        return {
            "vault_path": str(
                self.secrets_path
            ),
            "privacy_sanitization": "active",
            "local_only": True,
            "status": "protected",
        }


def sanitize_sensitive_text(
    text: str,
) -> str:
    """Sanitize text without creating or reading a secrets vault."""

    result = str(
        text
    )

    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(
            replacement,
            result,
        )

    return result
