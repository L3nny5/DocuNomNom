"""HTTP API layer (FastAPI)."""

from __future__ import annotations

from .. import __version__

# The API and the package version stay in lockstep for v1; we expose a
# dedicated alias so future API-only bumps don't drift the package
# version silently.
__api_version__ = __version__

__all__ = ["__api_version__"]
