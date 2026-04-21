"""Pydantic v2 DTOs for the public API.

DTOs are intentionally separate from the domain entities in
``docunomnom.core.models`` so the public wire format can evolve
independently of the internal model. Routers translate between the two.
"""

from .common import ErrorResponse, Page
from .config import (
    ConfigOverridesIn,
    ConfigResponse,
    KeywordCreate,
    KeywordOut,
    KeywordUpdate,
    SettingsView,
)
from .history import HistoryEntryOut, HistoryListResponse
from .jobs import (
    JobDetailOut,
    JobListResponse,
    JobSummaryOut,
    RescanResponse,
)
from .review import (
    FinalizeResultOut,
    MarkerSetIn,
    ReopenResponseOut,
    ReviewItemDetailOut,
    ReviewItemSummaryOut,
    ReviewListResponse,
    ReviewMarkerIn,
    ReviewMarkerOut,
    SplitProposalOut,
)

__all__ = [
    "ConfigOverridesIn",
    "ConfigResponse",
    "ErrorResponse",
    "FinalizeResultOut",
    "HistoryEntryOut",
    "HistoryListResponse",
    "JobDetailOut",
    "JobListResponse",
    "JobSummaryOut",
    "KeywordCreate",
    "KeywordOut",
    "KeywordUpdate",
    "MarkerSetIn",
    "Page",
    "ReopenResponseOut",
    "RescanResponse",
    "ReviewItemDetailOut",
    "ReviewItemSummaryOut",
    "ReviewListResponse",
    "ReviewMarkerIn",
    "ReviewMarkerOut",
    "SettingsView",
    "SplitProposalOut",
]
