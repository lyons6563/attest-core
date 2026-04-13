"""
Tests for app.crypto.event_hash — pure functions, no DB required.

Verifies:
- compute_event_hash is deterministic for the same inputs
- compute_event_hash changes when any field changes (no silent collisions)
- format_occurred_at_utc normalises datetime objects and string forms
- Legacy 6-part hash is used when actor_id/session_id/source_system are absent
- Extended hash is used when any audit field is present
"""

import sys
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.crypto.event_hash import compute_event_hash, format_occurred_at_utc


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def base_kwargs():
    return {
        "chain_id": "chain-abc",
        "event_type": "TRANSMITTED",
        "actor": "plan_sponsor",
        "occurred_at_utc": "2024-01-15T12:00:00Z",
        "payload_hash": "deadbeef" * 8,
        "previous_event_hash": None,
    }


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_same_inputs_same_hash(base_kwargs):
    h1 = compute_event_hash(**base_kwargs)
    h2 = compute_event_hash(**base_kwargs)
    assert h1 == h2


def test_returns_64_char_hex(base_kwargs):
    h = compute_event_hash(**base_kwargs)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# Sensitivity — each changed field must produce a different hash
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("chain_id", "chain-XYZ"),
    ("event_type", "VERIFIED"),
    ("actor", "recordkeeper"),
    ("occurred_at_utc", "2024-06-01T00:00:00Z"),
    ("payload_hash", "cafebabe" * 8),
    ("previous_event_hash", "aabbccdd" * 8),
])
def test_changing_field_changes_hash(base_kwargs, field, value):
    original = compute_event_hash(**base_kwargs)
    modified = compute_event_hash(**{**base_kwargs, field: value})
    assert original != modified, f"Hash did not change when {field!r} was modified"


# ---------------------------------------------------------------------------
# Legacy vs extended hash mode
# ---------------------------------------------------------------------------

def test_extended_hash_when_actor_id_present(base_kwargs):
    legacy = compute_event_hash(**base_kwargs)
    extended = compute_event_hash(**base_kwargs, actor_id="user-123")
    assert legacy != extended


def test_extended_hash_when_session_id_present(base_kwargs):
    legacy = compute_event_hash(**base_kwargs)
    extended = compute_event_hash(**base_kwargs, session_id="sess-abc")
    assert legacy != extended


def test_extended_hash_when_source_system_present(base_kwargs):
    legacy = compute_event_hash(**base_kwargs)
    extended = compute_event_hash(**base_kwargs, source_system="payroll-api")
    assert legacy != extended


def test_extended_hash_stable_across_calls(base_kwargs):
    h1 = compute_event_hash(**base_kwargs, actor_id="u1", session_id="s1", source_system="sys")
    h2 = compute_event_hash(**base_kwargs, actor_id="u1", session_id="s1", source_system="sys")
    assert h1 == h2


# ---------------------------------------------------------------------------
# None / empty equivalence
# ---------------------------------------------------------------------------

def test_none_and_empty_string_treated_equally(base_kwargs):
    h_none = compute_event_hash(**{**base_kwargs, "previous_event_hash": None})
    h_empty = compute_event_hash(**{**base_kwargs, "previous_event_hash": ""})
    assert h_none == h_empty


# ---------------------------------------------------------------------------
# format_occurred_at_utc
# ---------------------------------------------------------------------------

def test_format_utc_datetime():
    dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    result = format_occurred_at_utc(dt)
    assert "2024-01-15" in result
    assert result.endswith("Z")


def test_format_naive_datetime_treated_as_utc():
    dt = datetime(2024, 1, 15, 12, 0, 0)   # naive
    result = format_occurred_at_utc(dt)
    assert "2024-01-15" in result


def test_format_non_utc_datetime_converts_to_utc():
    tz_plus5 = timezone(timedelta(hours=5))
    dt = datetime(2024, 1, 15, 17, 0, 0, tzinfo=tz_plus5)  # 17:00+05 = 12:00Z
    result = format_occurred_at_utc(dt)
    assert "12:00:00" in result
    assert result.endswith("Z")


def test_format_none_returns_empty():
    assert format_occurred_at_utc(None) == ""


def test_format_empty_string_returns_empty():
    assert format_occurred_at_utc("") == ""


def test_format_string_passthrough():
    s = "2024-01-15T12:00:00Z"
    assert format_occurred_at_utc(s) == s


# ---------------------------------------------------------------------------
# Hash chain integrity (replay test)
# ---------------------------------------------------------------------------

def test_chain_of_two_events_links_correctly(base_kwargs):
    """Second event's previous_event_hash must equal the first event's hash."""
    first_hash = compute_event_hash(**base_kwargs)
    second_hash = compute_event_hash(
        chain_id=base_kwargs["chain_id"],
        event_type="VERIFIED",
        actor="recordkeeper",
        occurred_at_utc="2024-01-15T12:01:00Z",
        payload_hash=base_kwargs["payload_hash"],
        previous_event_hash=first_hash,
    )
    # Verify: recomputing with same inputs gives same result
    assert compute_event_hash(
        chain_id=base_kwargs["chain_id"],
        event_type="VERIFIED",
        actor="recordkeeper",
        occurred_at_utc="2024-01-15T12:01:00Z",
        payload_hash=base_kwargs["payload_hash"],
        previous_event_hash=first_hash,
    ) == second_hash
