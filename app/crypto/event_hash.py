import hashlib
from datetime import timezone


def format_occurred_at_utc(value) -> str:
    """
    Canonical UTC string for occurred_at_utc. Use at event creation and during verify.
    None and empty string both become ""; datetime is converted to UTC and formatted.
    """
    if value is None or value == "":
        return ""
    if hasattr(value, "astimezone") and hasattr(value, "isoformat"):
        # datetime-like: ensure UTC, then canonical string
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    return str(value).strip() if value else ""


def _norm(value) -> str:
    """Normalize for hashing: None and empty treated identically as ""."""
    if value is None or value == "":
        return ""
    return str(value)


def compute_event_hash(
    *,
    chain_id: str,
    event_type: str,
    actor: str,
    occurred_at_utc,  # str or datetime; will be normalized via format_occurred_at_utc
    payload_hash: str,
    previous_event_hash: str | None,
    actor_id: str | None = None,
    session_id: str | None = None,
    source_system: str | None = None,
    system_suggestion: str | None = None,
    options_presented: str | None = None,
    human_selection: str | None = None,
    decision_timestamp=None,  # str or datetime; normalized like occurred_at_utc
) -> str:
    """
    Canonical custody event hash. All inputs are normalized to strings;
    None and empty are treated identically. occurred_at_utc must be formatted
    with format_occurred_at_utc before hashing (no raw datetime).
    Legacy: if actor_id, session_id, source_system are all empty, uses 6-part hash
    for backward compatibility with events created before audit hardening.
    """
    if hasattr(occurred_at_utc, "astimezone") or hasattr(occurred_at_utc, "isoformat"):
        occurred_at_utc = format_occurred_at_utc(occurred_at_utc)
    if decision_timestamp is not None and (
        hasattr(decision_timestamp, "astimezone") or hasattr(decision_timestamp, "isoformat")
    ):
        decision_ts_str = format_occurred_at_utc(decision_timestamp)
    else:
        decision_ts_str = _norm(decision_timestamp)

    parts = [
        _norm(chain_id),
        _norm(event_type),
        _norm(actor),
        _norm(occurred_at_utc),
        _norm(payload_hash),
        _norm(previous_event_hash),
    ]

    use_extended = any(
        _norm(actor_id) or _norm(session_id) or _norm(source_system)
    )
    if use_extended:
        parts.extend([
            _norm(actor_id),
            _norm(session_id),
            _norm(source_system),
            _norm(system_suggestion),
            _norm(options_presented),
            _norm(human_selection),
            decision_ts_str,
        ])

    canonical_string = "|".join(parts)
    return hashlib.sha256(canonical_string.encode("utf-8")).hexdigest()
