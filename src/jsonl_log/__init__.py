# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""jsonl-log — an append-only JSONL event log with ULID + UTC-ISO stamping.

Extracted from three near-identical implementations (pitchcraft's persistence
ledgers, rulebook's interaction log). Two layers:

* Free functions — `append_jsonl`, `read_all`, `read_latest`,
  `read_latest_list`, plus the `new_ulid` / `utc_now_iso` stamps.
* `JsonlLog` — a path-bound convenience wrapper that auto-stamps id, timestamp,
  and schema version on append.

The package takes zero configuration from the host app: no singletons, no env
reads, no config imports. Construct `JsonlLog` with explicit arguments, or call
the free functions with an explicit path.
"""

from __future__ import annotations

from .backends import DurableBackend, DurableBackendError, GcsBackend
from .log import JsonlLog, append_jsonl, read_all, read_latest, read_latest_list
from .stamps import new_ulid, utc_now_iso

__all__ = [
    "DurableBackend",
    "DurableBackendError",
    "GcsBackend",
    "JsonlLog",
    "append_jsonl",
    "new_ulid",
    "read_all",
    "read_latest",
    "read_latest_list",
    "utc_now_iso",
]

__version__ = "0.2.0"
