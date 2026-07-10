"""Storage-neutral PLK content safety policy."""

from __future__ import annotations

import re

from detect_secrets.core.scan import scan_line
from detect_secrets.settings import default_settings
from plk_validator.secrets import CUSTOM_PATTERNS

IN_MEMORY_ENTROPY_PATTERNS = (
    ("High entropy hex token", re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{32,}(?![0-9A-Fa-f])")),
    (
        "Long base64-like token",
        re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/])"),
    ),
)


def scan_text(text: str) -> list[str]:
    """Scan an in-memory fact before it reaches any persistence adapter."""

    findings = {
        f"custom:{name}"
        for name, pattern in CUSTOM_PATTERNS
        if pattern.search(text)
    }
    findings.update(
        f"custom:{name}"
        for name, pattern in IN_MEMORY_ENTROPY_PATTERNS
        if pattern.search(text)
    )
    with default_settings():
        for line in text.splitlines():
            findings.update(
                f"detect-secrets:{secret.type}"
                for secret in scan_line(line)
                # Ad-hoc line scanning enables eager entropy detection and
                # flags ordinary ULIDs/URLs without file context. The Git
                # adapter retains the full file scan for entropy plugins.
                if secret.type
                not in {"Base64 High Entropy String", "Hex High Entropy String"}
            )
    return sorted(findings)
