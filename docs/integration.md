# Integration Guide

_Last updated: 2026-09-08_

How to adopt `jsonl-log` in a Python application. The [README](../README.md)
explains *what* the library does; this doc explains *how* to swap each existing
hand-rolled log over to it.

There are two independent adoption steps, and you can stop after the first:

1. **Replace the hand-rolled log** with the append/read core — the
   [per-consumer mappings](#pitchcraft--persistenceda_notes_logdecisions_ledgerdownstream_constraintspy)
   below. Local disk, no cloud, no new failure modes.
2. **Add durability** (v0.2) so the log survives a container restart — see
   [Adding durability](#adding-durability-v02). Only needed when the
   filesystem is ephemeral (Cloud Run, ECS).

**Provenance:** this package was extracted from three codebases that had each
reimplemented the same append-only JSONL shape. The mappings below are the
literal before/after for each one.

---

## Install

```bash
pip install jsonl-log
```

Requires Python 3.11+. One runtime dependency (`python-ulid`). The core
append/read surface is in the base install; the optional durable-backend layer
adds an extra:

```bash
pip install jsonl-log[gcs]   # adds google-cloud-storage
```

The per-consumer mappings below are all base-install; only
[Adding durability](#adding-durability-v02) needs the extra.

---

## Design stance: zero host configuration

Like the other extractions in this family, the library **takes no configuration
from the host app**: no module singletons, no env reads, no config imports. You
give it a path (and, for `JsonlLog`, explicit stamping options); it gives you
append + read. Where the host app wants a facade (a `_log_dir()` helper, a
shared settings object), that stays in the host app and wraps these calls.

---

## pitchcraft — `persistence/{da_notes_log,decisions_ledger,downstream_constraints}.py`

All three modules mint a ULID `id`, stamp a `Z`-second `timestamp`, carry a
`schema_version`, and append one line. Two of them return the minted id as a
back-reference. That is exactly `JsonlLog(stamp_id=True, schema_version=2)`.

**Before** (`decisions_ledger.py`, condensed):

```python
from datetime import datetime, timezone
from ulid import ULID

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def append_decision(persona, ..., data_root=None) -> str:
    ledger_path = (data_root or Path("data")) / "sessions" / user_id / "personas" / persona / "decisions_ledger.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    entry_id = str(ULID())
    entry = {"schema_version": 2, "id": entry_id, "timestamp": _utc_now_iso(), ...}
    with ledger_path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry_id
```

**After:**

```python
from jsonl_log import JsonlLog

def append_decision(persona, ..., data_root=None) -> str:
    ledger_path = (data_root or Path("data")) / "sessions" / user_id / "personas" / persona / "decisions_ledger.jsonl"
    ledger = JsonlLog(ledger_path, stamp_id=True, schema_version=2)
    return ledger.append({
        "user_id": user_id,
        "persona": persona,
        "persona_uuid": persona_uuid,
        "jd_context": jd_context,
        "note_context": note_context,
        "decision": decision,
        "applied_edit": applied_edit,
        "side_effects": side_effects_emitted or [],
    })
```

The local `_utc_now_iso()` helpers in all three modules — the ones whose comments
already said *"identical helper appears in… Worth consolidating"* — delete, and
the ULID/timestamp fields drop out of each `entry` dict; the library stamps them.
The record shape on disk is byte-for-byte the same (same field names, same field
order isn't guaranteed by JSON but readers don't depend on it).

**The `da_notes_log` batch case:** every note in one call shares a single
timestamp. Pre-compute it and set it on each row so auto-stamping leaves it
alone:

```python
log = JsonlLog(log_path, stamp_id=True, schema_version=2)
ts = utc_now_iso()
for note in notes:
    log.append({"timestamp": ts, "section": note.get("section"), ...})
```

Path construction, the `data_root` override, and argument validation stay in the
pitchcraft functions — the library is only replacing the stamp-and-append tail.

Pitchcraft already runs on Cloud Run and has historical ledgers on disk, so it
is the case [Adding durability](#adding-durability-v02) covers with
`bootstrap()` — the one-time push of existing rows up to the backend. Note the
per-call `JsonlLog(...)` construction above becomes a module-level log once a
backend is attached, so startup can hydrate it before serving.

---

## rulebook — `src/rulebook/interaction_log.py`

rulebook's shape differs in three ways, all covered by config: the key is
**caller-supplied** (`qa_id`, no minted id), the version field is **`v`** not
`schema_version`, and the timestamp is the bare
`datetime.now(timezone.utc).isoformat()` (auto precision, `+00:00` offset).

Its `_append_jsonl` and `read_latest_*` map onto the free functions almost
one-to-one. You can adopt at either layer.

**Free-function adoption** (closest to the current code):

```python
from jsonl_log import append_jsonl, read_latest, read_latest_list, utc_now_iso

def log_feedback(qa_id, *, rating, comment=None, tags=None):
    append_jsonl(_log_dir() / "feedback.jsonl", {
        "v": FEEDBACK_SCHEMA_VERSION,
        "qa_id": qa_id,
        "timestamp": utc_now_iso(timespec="auto", z=False),
        "rating": rating,
        "tags": list(tags or []),
        "comment": comment or None,
    })

def read_latest_feedback():
    return read_latest_list(
        _log_dir() / "feedback.jsonl",
        key="qa_id",
        where=lambda r: not isinstance(r.get("rating"), str),  # drop legacy v1 rows
        sort_desc="timestamp",
    )

def read_latest_curation():
    latest = read_latest(_log_dir() / "gold_curation.jsonl", key="qa_id")
    return {qa_id: bool(row["included"]) for qa_id, row in latest.items()}
```

The module-level `_write_lock` and `_append_jsonl` helper delete; the library's
lock replaces them. The `where=` filter absorbs the hand-written legacy-row skip.
`read_latest`/`read_latest_list` replace every `read_latest_*` walk.

**Class adoption** (if you'd rather bind each file once):

```python
feedback_log = JsonlLog(_log_dir() / "feedback.jsonl",
                        schema_version=3, version_field="v",
                        timespec="auto", z=False)
feedback_log.append({"qa_id": qa_id, "rating": rating, "tags": [...]})
```

Note `_log_dir()` reads `settings.repo_root` — that config access stays in
rulebook. The library never sees `settings`.

Rulebook is the consumer heading for Cloud Run, and the free-function adoption
shown above is exactly the shape that has to change to get durability — see
[the migration gotcha](#the-one-migration-gotcha-free-functions-have-no-durability)
in the next section.

---

## Adding durability (v0.2)

Everything above writes to local disk. That is the right answer on a VM or a
developer laptop, where the file outlives the process. It is the wrong answer on
Cloud Run, ECS, or any container that restarts onto a fresh filesystem: the log
is gone on the next deploy.

v0.2 adds an optional durable backend. Each append writes local **first**, then
mirrors the same line into an object store; a `hydrate()` call at startup pulls
the store's view back down. Reads never touch the network.

Reach for this only when the disk is actually ephemeral. If your log lives on a
real volume, skip this section — the local path is unchanged and adding a
backend buys you nothing but a new failure mode.

### The one migration gotcha: free functions have no durability

`durable_backend` lives on `JsonlLog` only. `append_jsonl` and the `read_*` free
functions deliberately did **not** grow the argument — hydration has no natural
home on a stateless function, and splitting the contract across two layers makes
the strict/hydrate semantics harder to reason about.

So a consumer that adopted at the free-function layer — the rulebook shape
[above](#rulebook--srcrulebookinteraction_logpy) — must move to the class to get
durability. It is a small change, and the on-disk record shape does not move:

```python
# Before — free functions, local only.
from jsonl_log import append_jsonl, read_latest_list, utc_now_iso

def log_feedback(qa_id, *, rating, comment=None, tags=None):
    append_jsonl(_log_dir() / "feedback.jsonl", {
        "v": FEEDBACK_SCHEMA_VERSION,
        "qa_id": qa_id,
        "timestamp": utc_now_iso(timespec="auto", z=False),
        "rating": rating,
        "tags": list(tags or []),
        "comment": comment or None,
    })

def read_latest_feedback():
    return read_latest_list(_log_dir() / "feedback.jsonl", key="qa_id",
                            sort_desc="timestamp")
```

```python
# After — one bound log per file, durability optional at construction.
from jsonl_log import JsonlLog

feedback_log = JsonlLog(
    _log_dir() / "feedback.jsonl",
    schema_version=FEEDBACK_SCHEMA_VERSION, version_field="v",
    timespec="auto", z=False,          # same timestamp flavour as before
    durable_backend=_backend(),        # None off-cloud — see wiring below
)

def log_feedback(qa_id, *, rating, comment=None, tags=None):
    feedback_log.append({
        "qa_id": qa_id,
        "rating": rating,
        "tags": list(tags or []),
        "comment": comment or None,
    })

def read_latest_feedback():
    return feedback_log.read_latest_list(key="qa_id", sort_desc="timestamp")
```

The stamping options reproduce the fields the free-function version wrote by
hand, so rows written before and after the migration are the same shape. The
`where=` legacy filter, if you had one, moves onto the read call unchanged.

### Wiring it at startup

Two rules, and the API enforces the first one for you:

- **`hydrate()` before any `append()`.** It overwrites local from the backend,
  so calling it later would silently discard rows this process appended.
  `JsonlLog` raises `RuntimeError` if you try; `force=True` overrides when
  clobbering is genuinely what you want.
- **`bootstrap()` before `hydrate()`,** and only when adopting durability on a
  log that already has local rows. It pushes existing local content up if the
  backend is empty, and is a no-op once the backend has anything.

```python
# app startup — once, single-threaded, before serving traffic.
import os
from jsonl_log import JsonlLog, GcsBackend

def _backend():
    """A backend on cloud, None locally. Keeps dev runs off the network."""
    bucket = os.environ.get("STATE_BUCKET")
    return GcsBackend(bucket, prefix="logs/") if bucket else None

feedback_log = JsonlLog(
    _log_dir() / "feedback.jsonl",
    schema_version=3, version_field="v",
    durable_backend=_backend(),
)

def startup() -> None:
    feedback_log.bootstrap()   # first deploy only; no-op forever after
    feedback_log.hydrate()     # pull the authoritative view down
```

Returning `None` from `_backend()` off-cloud is the recommended shape: every
call above stays valid, `bootstrap()` and `hydrate()` become no-ops, and local
development never needs credentials or a bucket.

### Decide what a backend outage should do

`strict=False` (the default) logs a warning and keeps the row on local disk. The
request succeeds, but that row is **permanently absent from the backend** —
nothing back-fills it, so the next restart's `hydrate()` drops it.

That trade is correct for HITL signal, where losing one thumbs-up beats failing
a user's request. It is wrong for an audit log. Pick per log, not per app:

```python
# HITL signal — availability wins.
feedback_log = JsonlLog(..., durable_backend=backend, strict=False)

# Audit trail — durability wins; handle the failure.
from jsonl_log import DurableBackendError

audit_log = JsonlLog(..., durable_backend=backend, strict=True)
try:
    audit_log.append(row)
except DurableBackendError:
    ...  # the local write already committed and is NOT rolled back
```

Note that `hydrate()` is not covered by `strict`: an unreachable backend at
startup raises the provider's own exception, not `DurableBackendError`. Decide
deliberately whether the container fails fast or continues local-only:

```python
def startup() -> None:
    try:
        feedback_log.hydrate()
    except Exception:
        logging.exception("hydrate failed; serving local-only this boot")
```

### Check the single-writer assumption before you ship

v0.2 assumes **one writer per (bucket, prefix, name) tuple**. Two container
instances appending to the same object can race the first-append existence
check and interleave composes. Match your deploy shape to it:

```bash
gcloud run deploy ... --max-instances=1 --min-instances=0
```

If you cannot cap instances, do not adopt the durable backend yet — multi-writer
correctness is v0.3. Note this is *narrower* than the local-file story: the
in-process lock already only covered a single process, so a multi-worker
deployment was never safe for the local file either.

### Testing your integration without GCS

`DurableBackend` is a runtime-checkable Protocol, so a dozen lines of in-memory
double covers your consumer's tests — no credentials, no network, no mocks of
the GCS client. This is exactly what this repo's own suite uses:

```python
class FakeDurableBackend:
    def __init__(self):
        self.store: dict[str, str] = {}

    def read_all(self, name: str) -> str | None:
        return self.store.get(name)

    def append(self, name: str, line: str) -> None:
        self.store[name] = self.store.get(name, "") + line


def test_feedback_survives_restart(tmp_path):
    backend = FakeDurableBackend()
    log = JsonlLog(tmp_path / "feedback.jsonl", durable_backend=backend)
    log.append({"qa_id": "q1", "rating": 5})

    # Simulate a container restart: fresh disk, same backend.
    (tmp_path / "feedback.jsonl").unlink()
    restarted = JsonlLog(tmp_path / "feedback.jsonl", durable_backend=backend)
    restarted.hydrate()
    assert restarted.read_latest("qa_id")["q1"]["rating"] == 5
```

Give it a `fail_next` flag to assert your `strict` choice behaves as intended
under an outage. See [`tests/conftest.py`](../tests/conftest.py) for the version
this repo uses.

---

## jobscout — `jobscout/store/disposition.py` (partial fit)

Be honest about the boundary here: jobscout's disposition/feedback is
**SQLite-backed**, not JSONL. `set_disposition` is an `UPDATE` on a `jds` column
(last-write-wins *in place*), and `record_sighting` is an `INSERT`. Neither is an
append-only file, so **the append/read core does not apply.**

What jobscout *does* share is the stamping helpers in `store/dao.py`:

```python
def new_id() -> str:
    return str(ULID())

def to_db(dt): return dt.isoformat() if dt is not None else None
```

`new_id()` is exactly `jsonl_log.new_ulid()`. If you want jobscout to depend on
this package at all, it's only to source those two helpers — the storage layer
stays SQLite. That's a judgment call, not a slam-dunk; a one-line `new_id`
wrapper is arguably not worth a dependency. Treat jobscout as **out of scope for
adoption** unless it grows a genuine append-only JSONL log later.

---

## Adoption checklist

- [ ] `pip install jsonl-log`, add to the consuming repo's deps
- [ ] Replace the local `_utc_now_iso` / `new_id` helpers with `utc_now_iso` / `new_ulid`
- [ ] Swap the append tail for `append_jsonl(...)` or `JsonlLog.append(...)`
- [ ] Swap `read_latest_*` walks for `read_latest` / `read_latest_list`
- [ ] Confirm on-disk record shape is unchanged (field names, version field, timestamp format)
- [ ] Delete the now-dead module-level lock + helpers
- [ ] Run the consuming repo's tests against a temp log dir

Each consumer keeps its own path construction, config access, and argument
validation. This library only owns the stamp-append-read core.

### If you also need durability (v0.2)

Do this only after the checklist above is green — durability is a second step,
not part of the swap.

- [ ] Confirm the disk is genuinely ephemeral; skip all of this if it isn't
- [ ] `pip install jsonl-log[gcs]`, add the extra to the consuming repo's deps
- [ ] Move any free-function call sites to `JsonlLog` (durability is class-only)
- [ ] Construct the backend from config, returning `None` off-cloud
- [ ] Call `bootstrap()` then `hydrate()` at startup, before any append
- [ ] Choose `strict` per log — availability vs. durability — and handle
      `DurableBackendError` where you chose `strict=True`
- [ ] Decide what an unreachable backend at startup does: fail fast, or catch
      and serve local-only
- [ ] Cap the deployment to one writer per (bucket, prefix, name)
- [ ] Add a restart test with an in-memory fake backend
- [ ] Verify the on-disk record shape still matches pre-migration rows

---

## Getting help

Open an issue on this repo, or point at the source modules above — they're the
working ground truth the library was distilled from.
