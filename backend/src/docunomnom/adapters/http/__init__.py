"""Resilient HTTP client wrapper.

Phase 0 placeholder. The Phase 2 wrapper around ``httpx`` enforces:
- explicit connect / read / total timeouts,
- retry policy with backoff and jitter,
- status-code whitelist for retries,
- error classification used by the generic external OCR adapter.
"""
