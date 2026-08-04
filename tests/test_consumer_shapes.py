# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Fidelity tests: reproduce each real consumer's record shape via the library.

These aren't testing the library so much as proving the extraction is faithful —
that pitchcraft's ledger rows and rulebook's interaction-log rows can be
produced and queried through `jsonl_log` without changing their on-disk shape.
"""

from __future__ import annotations

from jsonl_log import JsonlLog, append_jsonl, read_latest


def test_pitchcraft_decisions_ledger_shape(tmp_path):
    # persistence/decisions_ledger.py: stamps schema_version + minted id +
    # Z-second timestamp, returns the id for use as a back-reference.
    ledger = JsonlLog(tmp_path / "decisions_ledger.jsonl", stamp_id=True, schema_version=2)
    entry_id = ledger.append(
        {
            "user_id": "01USER",
            "persona": "wile",
            "persona_uuid": "01PERSONA",
            "jd_context": {"company": "Acme", "role_title": "QA"},
            "decision": {"choice_id": "substitute"},
            "applied_edit": {"kind": "substitute"},
            "side_effects": [],
        }
    )
    (row,) = ledger.read_all()
    assert row["id"] == entry_id and len(entry_id) == 26
    assert row["schema_version"] == 2
    assert row["timestamp"].endswith("Z")
    assert row["persona"] == "wile"


def test_pitchcraft_da_notes_batch_shares_one_timestamp(tmp_path):
    # persistence/da_notes_log.py: all notes in one call share a timestamp;
    # each note still gets its own minted id. The caller stamps the batch time
    # once and pre-sets it on every row, so auto-stamping leaves it untouched.
    from jsonl_log import utc_now_iso

    log = JsonlLog(tmp_path / "da_notes_log.jsonl", stamp_id=True, schema_version=2)
    notes = [{"section": "summary"}, {"section": "skills"}, {"section": "impact"}]
    ts = utc_now_iso()
    ids = [log.append({**n, "timestamp": ts}) for n in notes]

    rows = log.read_all()
    assert {r["timestamp"] for r in rows} == {ts}   # one shared batch timestamp
    assert len({r["id"] for r in rows}) == 3        # distinct minted ids
    assert all(i is not None for i in ids)


def test_rulebook_feedback_last_write_wins(tmp_path):
    # rulebook interaction_log.py: caller-supplied qa_id key, "v" version,
    # isoformat timestamp, no minted id; read_latest_feedback = last row wins,
    # skipping legacy string-rating rows.
    log = JsonlLog(
        tmp_path / "feedback.jsonl",
        schema_version=3,
        version_field="v",
        timespec="auto",
        z=False,
    )
    log.append({"qa_id": "q1", "rating": 2, "tags": []})
    log.append({"qa_id": "q1", "rating": 5, "tags": ["helpful"]})  # user changed vote

    latest = log.read_latest_list(
        "qa_id",
        where=lambda r: not isinstance(r["rating"], str),
        sort_desc="timestamp",
    )
    assert len(latest) == 1
    assert latest[0]["rating"] == 5
    assert latest[0]["v"] == 3
    assert "id" not in latest[0]


def test_rulebook_low_level_functions_map_directly(tmp_path):
    # rulebook's _append_jsonl + read_latest_curation, using free functions only.
    path = tmp_path / "gold_curation.jsonl"
    append_jsonl(path, {"v": 1, "qa_id": "q1", "included": True})
    append_jsonl(path, {"v": 1, "qa_id": "q1", "included": False})
    curation = {k: v["included"] for k, v in read_latest(path, "qa_id").items()}
    assert curation == {"q1": False}
