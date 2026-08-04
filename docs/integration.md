# Integration Guide

How to adopt `jsonl-log` in a Python application. The [README](../README.md)
explains *what* the library does; this doc explains *how* to swap each existing
hand-rolled log over to it.

**Provenance:** this package was extracted from three codebases that had each
reimplemented the same append-only JSONL shape. The mappings below are the
literal before/after for each one.

---

## Install

```bash
pip install "jsonl-log @ git+https://github.com/ecoop/jsonl-log@v0.1.0"
```

One runtime dependency (`python-ulid`). No optional extras — the whole surface
is in the base install.

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

- [ ] `pip install "jsonl-log @ git+…@v0.1.0"`, add to the consuming repo's deps
- [ ] Replace the local `_utc_now_iso` / `new_id` helpers with `utc_now_iso` / `new_ulid`
- [ ] Swap the append tail for `append_jsonl(...)` or `JsonlLog.append(...)`
- [ ] Swap `read_latest_*` walks for `read_latest` / `read_latest_list`
- [ ] Confirm on-disk record shape is unchanged (field names, version field, timestamp format)
- [ ] Delete the now-dead module-level lock + helpers
- [ ] Run the consuming repo's tests against a temp log dir

Each consumer keeps its own path construction, config access, and argument
validation. This library only owns the stamp-append-read core.

---

## Getting help

Open an issue on this repo, or point at the source modules above — they're the
working ground truth the library was distilled from.
