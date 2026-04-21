"""Worker process.

Single process in v1. Polls the database-backed job queue, leases jobs,
runs the Phase 2 pipeline, and emits audit events.
"""

from .loop import JobLoop, JobLoopConfig, JobOutcome, JobProcessingError, JobProcessor
from .ocr_factory import build_ocr_port_factory
from .processor import Phase2Processor, Phase2ProcessorConfig
from .watcher import StabilityWatcher, WatcherResult, settings_to_config_snapshot

__all__ = [
    "JobLoop",
    "JobLoopConfig",
    "JobOutcome",
    "JobProcessingError",
    "JobProcessor",
    "Phase2Processor",
    "Phase2ProcessorConfig",
    "StabilityWatcher",
    "WatcherResult",
    "build_ocr_port_factory",
    "settings_to_config_snapshot",
]
