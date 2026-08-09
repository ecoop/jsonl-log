# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Real-GCS integration tests for the durable backend.

Gated on ``GCS_TEST_BUCKET``. CI never runs this suite by default; local
dev sets ``GCS_TEST_BUCKET=<your-personal-bucket>`` to exercise the real
compose/consolidate paths. Each test scopes its objects under a
per-run ULID prefix and cleans them up in a finalizer so successive runs
don't accumulate junk.

Requires ``pip install jsonl-log[gcs]`` and Application Default
Credentials that can read/write objects in the bucket.
"""

from __future__ import annotations

import os

import pytest

from jsonl_log import GcsBackend, JsonlLog, new_ulid

_BUCKET = os.getenv("GCS_TEST_BUCKET")

pytestmark = pytest.mark.skipif(
    not _BUCKET,
    reason="set GCS_TEST_BUCKET=<bucket> to enable real-GCS integration tests",
)


@pytest.fixture
def gcs_backend():
    """Real GcsBackend under a per-run ULID prefix; deletes everything on teardown."""
    prefix = f"jsonl-log-integration-tests/{new_ulid()}/"
    backend = GcsBackend(_BUCKET, prefix=prefix)
    yield backend

    # Teardown: enumerate and delete every object under our prefix.
    from google.cloud import storage

    client = storage.Client()
    for blob in client.list_blobs(_BUCKET, prefix=prefix):
        blob.delete()


def test_real_gcs_roundtrip(gcs_backend):
    for i in range(5):
        gcs_backend.append("roundtrip.jsonl", f'{{"n": {i}}}\n')

    text = gcs_backend.read_all("roundtrip.jsonl")
    assert text == "".join(f'{{"n": {i}}}\n' for i in range(5))


def test_real_gcs_hydrate_after_restart(gcs_backend, tmp_path):
    # Container A writes.
    log_a = JsonlLog(
        tmp_path / "a" / "feedback.jsonl",
        stamp_time=False,
        durable_backend=gcs_backend,
        durable_name="feedback.jsonl",
    )
    log_a.append({"qa_id": "q1", "rating": 5})
    log_a.append({"qa_id": "q2", "rating": 3})

    # Container B starts on a different local path; hydrate pulls state down.
    log_b = JsonlLog(
        tmp_path / "b" / "feedback.jsonl",
        stamp_time=False,
        durable_backend=gcs_backend,
        durable_name="feedback.jsonl",
    )
    log_b.hydrate()

    rows = log_b.read_all()
    assert [(r["qa_id"], r["rating"]) for r in rows] == [("q1", 5), ("q2", 3)]


def test_real_gcs_consolidation_end_to_end(tmp_path):
    # Fresh backend with a low consolidation threshold so this test doesn't
    # do a thousand appends.
    prefix = f"jsonl-log-integration-tests/{new_ulid()}/"
    backend = GcsBackend(_BUCKET, prefix=prefix, consolidate_every=5)

    try:
        for i in range(7):
            backend.append("log.jsonl", f'{{"n": {i}}}\n')

        # After 7 appends with threshold 5, consolidation ran once and the
        # counter reset. Regardless of the compose/rewrite history, the
        # final content must reflect all 7 rows in order.
        text = backend.read_all("log.jsonl")
        assert text == "".join(f'{{"n": {i}}}\n' for i in range(7))
    finally:
        from google.cloud import storage

        client = storage.Client()
        for blob in client.list_blobs(_BUCKET, prefix=prefix):
            blob.delete()
