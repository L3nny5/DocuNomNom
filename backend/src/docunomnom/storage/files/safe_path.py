"""Path sandboxing.

All filesystem operations that touch user-controlled inputs (input dir, work
dir, output dir, archive dir, OCR artifacts) MUST go through ``safe_path``
to ensure the resolved path stays inside an allowed root. This prevents
classical traversal bugs (``../../etc/shadow``) and accidental escapes via
symlinks.

The function is intentionally strict:

- It resolves both the root and the candidate (``Path.resolve(strict=False)``)
  so symlinks are followed once at the boundary check.
- It raises ``UnsafePathError`` on any escape or invalid input.
- It never auto-creates directories; callers do that explicitly after the
  check.
"""

from __future__ import annotations

from pathlib import Path


class UnsafePathError(ValueError):
    """Raised when a candidate path resolves outside the allowed root."""


def safe_path(root: str | Path, *parts: str | Path) -> Path:
    """Resolve ``parts`` relative to ``root`` and assert containment.

    ``parts`` may be absolute; this is treated as untrusted input and
    rejected unless the resolved path stays inside ``root``.
    """
    if root is None:
        raise UnsafePathError("root must not be None")
    raw_root = Path(root)
    if not raw_root.is_absolute():
        # Reject relative roots before .resolve() makes them absolute
        # against the current working directory.
        raise UnsafePathError(f"root must be absolute, got {root!r}")
    root_path = raw_root.resolve(strict=False)

    candidate = root_path
    for part in parts:
        candidate = candidate / Path(part)
    resolved = candidate.resolve(strict=False)

    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise UnsafePathError(f"path {resolved!s} escapes root {root_path!s}") from exc

    return resolved


def is_inside(root: str | Path, candidate: str | Path) -> bool:
    """Return True iff ``candidate`` resolves inside ``root``."""
    try:
        safe_path(root, candidate)
    except UnsafePathError:
        return False
    return True
