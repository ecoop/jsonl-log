# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Tests for GcsBackend against a fake google.cloud.storage client.

The fake here records every blob operation (upload / compose / download /
delete) so tests can assert not only the final store state but the exact
sequence of GCS calls the backend made. Follows llm-cost-governor's
monkeypatch-``_client`` pattern so ``google-cloud-storage`` is never
actually imported.
"""

from __future__ import annotations

import sys

import pytest

from jsonl_log import GcsBackend

# ── Fake google.cloud.storage client ─────────────────────────────────────────

class _FakeStore:
    """Records blob state and every operation issued against it."""

    def __init__(self) -> None:
        self.blobs: dict[str, str] = {}
        self.content_types: dict[str, str] = {}
        # Each op is (verb, blob_name, extra) — extra is a tuple whose
        # shape depends on verb. Tests grep this list.
        self.ops: list[tuple[str, str, tuple]] = []


class _FakeBlob:
    def __init__(self, store: _FakeStore, name: str) -> None:
        self._store = store
        self.name = name

    def exists(self) -> bool:
        return self.name in self._store.blobs

    def upload_from_string(self, text: str, content_type: str | None = None) -> None:
        self._store.blobs[self.name] = text
        if content_type is not None:
            self._store.content_types[self.name] = content_type
        self._store.ops.append(("upload", self.name, (content_type,)))

    def download_as_text(self) -> str:
        self._store.ops.append(("download", self.name, ()))
        return self._store.blobs[self.name]

    def compose(self, sources) -> None:
        combined = "".join(self._store.blobs[s.name] for s in sources)
        self._store.blobs[self.name] = combined
        self._store.ops.append(("compose", self.name, tuple(s.name for s in sources)))

    def delete(self) -> None:
        del self._store.blobs[self.name]
        self._store.ops.append(("delete", self.name, ()))


class _FakeBucket:
    def __init__(self, store: _FakeStore) -> None:
        self._store = store

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self._store, name)


class _FakeClient:
    def __init__(self, store: _FakeStore) -> None:
        self._store = store

    def bucket(self, name: str) -> _FakeBucket:
        return _FakeBucket(self._store)


@pytest.fixture
def gcs_backend():
    """A GcsBackend whose lazy client is pre-populated with a fake."""
    backend = GcsBackend("test-bucket")
    store = _FakeStore()
    backend._client = _FakeClient(store)  # bypass the lazy google.cloud import
    return backend, store


# ── Tests ────────────────────────────────────────────────────────────────────

def test_gcs_client_is_lazy():
    # Constructing GcsBackend must NOT import google.cloud.storage. If it
    # did, this suite could not run on machines without the extra installed.
    sys.modules.pop("google.cloud.storage", None)
    _ = GcsBackend("some-bucket")
    assert "google.cloud.storage" not in sys.modules


def test_gcs_read_missing_returns_none(gcs_backend):
    backend, _store = gcs_backend
    assert backend.read_all("absent.jsonl") is None


def test_gcs_read_returns_composed_content(gcs_backend):
    backend, store = gcs_backend
    store.blobs["seed.jsonl"] = '{"n": 1}\n{"n": 2}\n'
    assert backend.read_all("seed.jsonl") == '{"n": 1}\n{"n": 2}\n'


def test_gcs_append_first_time_creates_target(gcs_backend):
    backend, store = gcs_backend
    backend.append("log.jsonl", '{"n": 1}\n')

    assert store.blobs == {"log.jsonl": '{"n": 1}\n'}
    # First-time path: single upload to target, no temp, no compose.
    assert [op[0] for op in store.ops] == ["upload"]
    assert store.ops[0][1] == "log.jsonl"


def test_gcs_append_subsequent_composes(gcs_backend):
    backend, store = gcs_backend
    backend.append("log.jsonl", '{"n": 1}\n')
    store.ops.clear()  # focus on the second call

    backend.append("log.jsonl", '{"n": 2}\n')

    verbs = [op[0] for op in store.ops]
    assert verbs == ["upload", "compose", "delete"]
    # The compose merged [target, temp] into target.
    compose_op = next(op for op in store.ops if op[0] == "compose")
    assert compose_op[1] == "log.jsonl"
    target_src, temp_src = compose_op[2]
    assert target_src == "log.jsonl"
    assert temp_src.startswith("log.jsonl.tmp.")
    # And the composed target now holds BOTH lines in order.
    assert store.blobs["log.jsonl"] == '{"n": 1}\n{"n": 2}\n'


def test_gcs_append_temp_object_is_deleted_after_compose(gcs_backend):
    backend, store = gcs_backend
    for i in range(5):
        backend.append("log.jsonl", f'{{"n": {i}}}\n')
    # After N appends the only object should be the target — every temp
    # was deleted immediately after its compose.
    assert list(store.blobs) == ["log.jsonl"]


def test_gcs_append_prefix_is_prepended_to_object_name(gcs_backend):
    backend, store = gcs_backend
    backend._prefix = "logs/rulebook/"  # simulate GcsBackend(..., prefix=...)

    backend.append("feedback.jsonl", '{"qa_id": "a"}\n')

    assert list(store.blobs) == ["logs/rulebook/feedback.jsonl"]


def test_gcs_consolidation_triggers_at_threshold(gcs_backend):
    backend, store = gcs_backend
    backend._consolidate_every = 3

    for i in range(3):
        backend.append("log.jsonl", f'{{"n": {i}}}\n')

    # The 3rd append must have consolidated — download of target, then a
    # fresh upload of target. Both happen AFTER the compose+delete of that
    # append's temp object.
    verbs_targets = [(op[0], op[1]) for op in store.ops]
    # Consolidation signature is the last two ops on the target.
    assert verbs_targets[-2:] == [("download", "log.jsonl"), ("upload", "log.jsonl")]

    # Content-wise, the target still holds all three rows.
    assert store.blobs["log.jsonl"] == '{"n": 0}\n{"n": 1}\n{"n": 2}\n'

    # Counter reset — a 4th append should NOT immediately consolidate.
    store.ops.clear()
    backend.append("log.jsonl", '{"n": 3}\n')
    verbs = [op[0] for op in store.ops]
    assert "download" not in verbs
    assert verbs.count("upload") == 1  # just the temp upload


def test_gcs_consolidation_does_not_trigger_below_threshold(gcs_backend):
    backend, store = gcs_backend
    backend._consolidate_every = 5

    for i in range(4):
        backend.append("log.jsonl", f'{{"n": {i}}}\n')

    verbs = [op[0] for op in store.ops]
    assert "download" not in verbs  # consolidation would have caused a download


def test_gcs_append_content_type_is_ndjson(gcs_backend):
    backend, store = gcs_backend
    backend.append("log.jsonl", '{"n": 1}\n')  # first-time: direct upload
    backend.append("log.jsonl", '{"n": 2}\n')  # subsequent: temp upload + compose

    # Every upload — target on first append AND temps on later appends —
    # tags application/x-ndjson.
    upload_ctypes = [op[2][0] for op in store.ops if op[0] == "upload"]
    assert upload_ctypes == ["application/x-ndjson", "application/x-ndjson"]
