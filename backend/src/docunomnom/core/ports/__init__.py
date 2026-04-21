"""Domain ports (interfaces) implemented by adapters and storage."""

from .ai_split import AiSplitPort
from .clock import ClockPort
from .job_queue import JobQueuePort
from .ocr import OcrPageResult, OcrPort, OcrResult
from .storage import (
    AnalysisRepositoryPort,
    ConfigProfileRepositoryPort,
    ConfigSnapshotRepositoryPort,
    DocumentPartRepositoryPort,
    EvidenceRepositoryPort,
    ExportRepositoryPort,
    FileRepositoryPort,
    JobEventRepositoryPort,
    JobRepositoryPort,
    KeywordRepositoryPort,
    PageRepositoryPort,
    ReviewItemRepositoryPort,
    ReviewMarkerRepositoryPort,
    SplitProposalRepositoryPort,
)

__all__ = [
    "AiSplitPort",
    "AnalysisRepositoryPort",
    "ClockPort",
    "ConfigProfileRepositoryPort",
    "ConfigSnapshotRepositoryPort",
    "DocumentPartRepositoryPort",
    "EvidenceRepositoryPort",
    "ExportRepositoryPort",
    "FileRepositoryPort",
    "JobEventRepositoryPort",
    "JobQueuePort",
    "JobRepositoryPort",
    "KeywordRepositoryPort",
    "OcrPageResult",
    "OcrPort",
    "OcrResult",
    "PageRepositoryPort",
    "ReviewItemRepositoryPort",
    "ReviewMarkerRepositoryPort",
    "SplitProposalRepositoryPort",
]
