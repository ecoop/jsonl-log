# jsonl-log

[![PyPI](https://img.shields.io/pypi/v/jsonl-log.svg)](https://pypi.org/project/jsonl-log/)
[![Python](https://img.shields.io/pypi/pyversions/jsonl-log.svg)](https://pypi.org/project/jsonl-log/)
[![CI](https://github.com/ecoop/jsonl-log/actions/workflows/ci.yml/badge.svg)](https://github.com/ecoop/jsonl-log/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

An append-only [JSONL](https://jsonlines.org/) event log with ULID + UTC-ISO
stamping and last-row-wins reads. One JSON object per line, appended and never
rewritten — cheap to write, cheap to `grep`, safe to tail from another process.

Optionally mirrors every append into an object store, so a log living on a
container's ephemeral disk survives a restart — without paying a network
round-trip on any read.

Extracted from three codebases that had each reinvented the same shape:
pitchcraft's persistence ledgers (`da_notes_log`, `decisions_ledger`,
`downstream_constraints`) and rulebook's `interaction_log`. The source flagged
its own duplication — this package is the consolidation.

_Last updated: 2026-09-08_

---

## Install

```bash
pip install jsonl-log
```

Requires Python 3.11+. One runtime dependency,
[`python-ulid`](https://pypi.org/project/python-ulid/) (plus
`typing-extensions` on 3.11, which `python-ulid` needs but doesn't declare).
The durable-backend layer is an opt-in extra — see
[Durable backends](#durable-backends-v02).

---

## Two layers

The library is deliberately split into low-level functions and a convenience
class, because the source codebases used it at both altitudes.

### Free functions — the storage-agnostic core

```python
from jsonl_log import append_jsonl, read_all, read_latest, read_latest_list

# Append one complete JSON object per line (parents created, write locked).
append_jsonl("data/feedback.jsonl", {"qa_id": "q1", "rating": 5})

# "Last write wins" per key — the current state when each append is an event.
latest = read_latest("data/feedback.jsonl", key="qa_id")   # {"q1": {...}}

# Same, as a list, newest-first by a timestamp field.
rows = read_latest_list("data/feedback.jsonl", key="qa_id", sort_desc="timestamp")

# Everything, in file order, with an optional row filter.
rows = read_all("data/feedback.jsonl", where=lambda r: r["rating"] >= 4)
```

### `JsonlLog` — a path-bound log with auto-stamping

```python
from jsonl_log import JsonlLog

ledger = JsonlLog("data/decisions_ledger.jsonl", stamp_id=True, schema_version=2)

entry_id = ledger.append({"user_id": "01USER", "choice": "substitute"})
# -> row on disk carries a minted ULID `id`, a `Z`-second `timestamp`,
#    a `schema_version`, plus your fields. entry_id is the minted ULID.

for row in ledger.read_all():
    ...
```

### Stamps, standalone

```python
from jsonl_log import new_ulid, utc_now_iso

new_ulid()                              # "01J9Z8...": sortable, time-ordered
utc_now_iso()                           # "2026-08-04T12:34:56Z"  (default)
utc_now_iso(timespec="auto", z=False)   # "2026-08-04T12:34:56.789012+00:00"
```

---

## Auto-stamping and field names

`JsonlLog` stamps each appended row before it hits disk, and **never overwrites
a field the caller already set**. Every field name is configurable so an
existing on-disk shape survives adoption unchanged.

| Option | Default | What it does |
|---|---|---|
| `stamp_id` | `False` | Mint a ULID into `id_field` (kept if caller supplied one). `append()` returns it. |
| `stamp_time` | `True` | Stamp `utc_now_iso()` into `timestamp_field` if absent. |
| `schema_version` | `None` | Stamp this value into `version_field` if set and absent. |
| `id_field` | `"id"` | Field name for the minted ULID. |
| `timestamp_field` | `"timestamp"` | Field name for the timestamp. |
| `version_field` | `"schema_version"` | Field name for the schema version (rulebook uses `"v"`). |
| `timespec` / `z` | `"seconds"` / `True` | Timestamp precision + `Z`-suffix vs `+00:00` offset. |
| `lock` | new `Lock()` | Write lock; pass a shared one to serialize across logs. |

Because stamping skips fields already present, the "one timestamp shared across
a batch" case (pitchcraft's `da_notes_log`, where every note in a call carries
the same stamp) works by pre-setting `timestamp` on each row.

---

## Concurrency

Appends are serialized under a lock so concurrent writers can't interleave
partial lines — JSONL requires exactly one complete object per line, and a raced
write corrupts the file for every reader. A single in-process lock is enough
under a single-process server (uvicorn `--reload`), a CLI, or a worker.

A **multi-worker** deployment needs OS-level file locking (`fcntl.flock`) or a
dedicated append service — out of scope here. The free functions accept a
`lock=` you own; `JsonlLog` instances each hold their own lock unless you pass a
shared one.

---

## Durable backends (v0.2)

For deployments where the local filesystem is ephemeral (Cloud Run, ECS, any
container that restarts to a fresh disk), `JsonlLog` can mirror each append to
an object-store backend and hydrate local state back on startup. **Reads stay
local-only** — no network round-trip per read.

```bash
pip install jsonl-log[gcs]   # adds google-cloud-storage
```

```python
from jsonl_log import JsonlLog, GcsBackend

log = JsonlLog(
    "data/feedback.jsonl",
    durable_backend=GcsBackend("rulebook-state", prefix="logs/"),
    strict=False,          # log-and-continue on backend failure (see below)
)
log.hydrate()              # pull latest state from GCS at startup
log.append({"qa_id": "q1", "rating": 5})   # writes local AND GCS
rows = log.read_latest_list(key="qa_id", sort_desc="timestamp")
```

| Option | Default | What it does |
|---|---|---|
| `durable_backend` | `None` | A `DurableBackend`. `None` is v0.1 behavior byte-for-byte. |
| `durable_name` | `Path(path).name` | Object name at the backend, so `data/feedback.jsonl` stores as `feedback.jsonl`. |
| `strict` | `False` | Raise `DurableBackendError` on a backend append failure instead of warning. |

### Three operating modes

- **No backend** (`durable_backend=None`) — v0.1 behavior byte-for-byte. Local
  append, local reads, no cloud path.
- **Backend, reachable** — every append writes local first, then mirrors to
  the backend under the same lock. `hydrate()` at startup pulls the backend's
  view down into the local file, overwriting any diverged local content.
- **Backend, unreachable at startup** — `hydrate()` propagates the backend's
  own exception (it is not wrapped in `DurableBackendError`); the container
  should either fail fast or catch and continue local-only. Subsequent appends
  retry the backend on every call.

### How appends stay O(1)

Naively, "append a row to an object store" means download the object, add a
line, re-upload — O(N) per row, which degrades as the log grows. `GcsBackend`
instead uploads the single new line to a temp object and asks GCS to
[compose](https://cloud.google.com/storage/docs/composite-objects)
`[target, temp] → target` server-side. The target grows by one row without its
contents ever crossing the wire, which matches the cost model of the local
append it mirrors.

Composed objects carry a component count that GCS caps, so every
`consolidate_every` appends (default 1000, counted per-process) the target is
rewritten as a flat blob to reset it. That rewrite is O(N), but amortized over
a thousand rows — a rare latency spike on the write path, not a per-row cost.

### `strict` and the silent-gap caveat

By default (`strict=False`) a backend append failure is logged as a warning
and the row remains on local disk only. On the next container restart,
`hydrate()` pulls the backend-authoritative state and that missed row
**disappears** from the container's view — nothing back-fills it. This is
intentional for HITL signal (thumbs, curation clicks): losing one row on a GCS
outage is preferable to failing the user's request. For audit-critical logs,
pass `strict=True` and handle `DurableBackendError` yourself.

### Hydrate is startup-only

`hydrate()` overwrites the local file from the backend, so calling it after
rows have been appended in-process would silently discard them. It raises
`RuntimeError` in that case; pass `force=True` if overwriting is genuinely what
you want. Call it once, during single-threaded startup, before any appends.

### Adopting on a pre-existing log

If you already have a local jsonl file and are enabling durability for the
first time, call `log.bootstrap()` once at startup **before any appends** to
push the existing rows up to the backend. Idempotent — a no-op once the
backend has content.

### Single-writer assumption

v0.2 assumes **one writer per (bucket, prefix, name) tuple**. Match your
deployment shape (e.g. Cloud Run `--max-instances=1 --min-instances=0`).
Concurrent writers can race the first-append existence check and interleave
composes. Multi-writer correctness is on the v0.3 roadmap; see the v0.2 design
notes in [`docs/v0.2-plan.md`](docs/v0.2-plan.md) for the candidates.

### Custom backends

`DurableBackend` is a runtime-checkable Protocol — any class with
`read_all(name) -> str | None` and `append(name, line) -> None` satisfies
it. Consumers who want Firestore, S3, or an in-memory test backend
implement two methods and pass the instance to `JsonlLog(...,
durable_backend=...)`.

---

## Adopting it

See [`docs/integration.md`](docs/integration.md) for the before/after mapping
from each source implementation, including which parts of jobscout do (and don't)
apply.

---

## Development

```bash
pip install -e ".[dev]"
ruff check src tests
pytest
```

65 tests, no network required — the GCS backend is exercised against a fake
bucket, so the suite runs offline. Three integration tests hit real GCS and
skip unless `GCS_TEST_BUCKET` is set. CI runs ruff + pytest on Python 3.11,
3.12, and 3.13; releases publish to PyPI from a version tag via trusted
publishing (OIDC, no API token).

---

## License

MIT — see [LICENSE](LICENSE).
