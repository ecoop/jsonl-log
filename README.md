# jsonl-log

An append-only [JSONL](https://jsonlines.org/) event log with ULID + UTC-ISO
stamping and last-row-wins reads. One JSON object per line, appended and never
rewritten — cheap to write, cheap to `grep`, safe to tail from another process.

Extracted from three codebases that had each reinvented the same shape:
pitchcraft's persistence ledgers (`da_notes_log`, `decisions_ledger`,
`downstream_constraints`) and rulebook's `interaction_log`. The source flagged
its own duplication — this package is the consolidation.

_Last updated: 2026-08-06_

---

## Install

```bash
pip install jsonl-log
```

One runtime dependency: [`python-ulid`](https://pypi.org/project/python-ulid/).

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

## Adopting it

See [`docs/integration.md`](docs/integration.md) for the before/after mapping
from each source implementation, including which parts of jobscout do (and don't)
apply.

---

## License

MIT — see [LICENSE](LICENSE).
