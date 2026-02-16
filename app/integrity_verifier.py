"""
Integrity verification heartbeat for event-sourced custody ledger.

Verifies chain integrity by recomputing event hashes and comparing the final
head hash to the stored last event_hash for each chain.
"""
import os
from datetime import datetime, timezone
from collections import defaultdict
from sqlalchemy import text
from app.db import get_engine
from app.crypto.event_hash import compute_event_hash, format_occurred_at_utc


def _get_anchored_chain_commitment():
    """
    Identify the most recently updated chain and return its head event commitment.
    
    Returns:
        dict with keys: chain_id, event_hash (head hash), occurred_at_utc, event_count
        or None if no chains exist
    """
    with get_engine().connect() as conn:
        # Find most recently updated chain
        latest_chain = conn.execute(
            text("""
                SELECT chain_id, MAX(occurred_at_utc) as max_occurred_at
                FROM custody_events
                GROUP BY chain_id
                ORDER BY MAX(occurred_at_utc) DESC
                LIMIT 1
            """)
        ).fetchone()

        if not latest_chain:
            return None

        chain_id = str(latest_chain.chain_id)

        # Get head event (last event) for that chain
        head_event = conn.execute(
            text("""
                SELECT event_hash, occurred_at_utc
                FROM custody_events
                WHERE chain_id = :cid
                ORDER BY occurred_at_utc DESC, event_id DESC
                LIMIT 1
            """),
            {"cid": chain_id},
        ).fetchone()

        if not head_event:
            return None

        # Count total events for this chain
        count_row = conn.execute(
            text("SELECT COUNT(*) as cnt FROM custody_events WHERE chain_id = :cid"),
            {"cid": chain_id},
        ).fetchone()

        return {
            "chain_id": chain_id,
            "event_hash": head_event.event_hash,
            "occurred_at_utc": head_event.occurred_at_utc.isoformat() if head_event.occurred_at_utc else None,
            "event_count": count_row.cnt if count_row else 0,
        }


def verify_integrity():
    """
    Load all custody_events grouped by chain_id, recompute head hash for each chain,
    and compare to stored last event_hash.

    Returns:
        dict with keys:
            - verified_at: UTC timestamp string
            - chains_checked: int
            - status: "PASS" or "FAIL"
            - details: optional list of mismatch info (chain_id, expected, actual)
    """
    verified_at = datetime.now(timezone.utc).isoformat()
    chains_checked = 0
    mismatches = []

    with get_engine().connect() as conn:
        # Load all events grouped by chain_id
        events_rows = conn.execute(
            text("""
                SELECT
                    chain_id,
                    event_id,
                    event_type,
                    actor,
                    payload_hash,
                    previous_event_hash,
                    event_hash,
                    occurred_at_utc,
                    actor_id,
                    session_id,
                    source_system,
                    system_suggestion,
                    options_presented,
                    human_selection,
                    decision_timestamp
                FROM custody_events
                ORDER BY chain_id, occurred_at_utc ASC, event_id ASC
            """)
        ).fetchall()

        # Group by chain_id
        chains = defaultdict(list)
        for row in events_rows:
            chains[str(row.chain_id)].append(row)

        # Verify each chain
        for chain_id, events in chains.items():
            chains_checked += 1
            if not events:
                continue

            # Sort deterministically (already sorted by SQL, but ensure)
            events_sorted = sorted(
                events,
                key=lambda e: (e.occurred_at_utc, e.event_id)
            )

            # Walk chain and recompute hashes
            recomputed_head_hash = None
            prior_recomputed_hash = None

            for idx, event in enumerate(events_sorted):
                # Format occurred_at_utc for hash computation
                occurred_at_utc_str = format_occurred_at_utc(event.occurred_at_utc)

                # Verify previous_event_hash continuity (first event should have None)
                if idx == 0:
                    if event.previous_event_hash is not None:
                        mismatches.append({
                            "chain_id": chain_id,
                            "event_id": str(event.event_id),
                            "reason": "previous_event_hash_not_null_for_first_event",
                            "stored": event.previous_event_hash,
                        })
                else:
                    # For subsequent events, stored previous_event_hash should match prior recomputed hash
                    if event.previous_event_hash != prior_recomputed_hash:
                        mismatches.append({
                            "chain_id": chain_id,
                            "event_id": str(event.event_id),
                            "reason": "previous_event_hash_mismatch",
                            "expected": prior_recomputed_hash,
                            "stored": event.previous_event_hash,
                        })

                # Recompute event_hash using recomputed prior hash (not stored previous_event_hash)
                recomputed_hash = compute_event_hash(
                    chain_id=chain_id,
                    event_type=event.event_type,
                    actor=event.actor,
                    occurred_at_utc=occurred_at_utc_str,
                    payload_hash=event.payload_hash or "",
                    previous_event_hash=prior_recomputed_hash,
                    actor_id=getattr(event, "actor_id", None),
                    session_id=getattr(event, "session_id", None),
                    source_system=getattr(event, "source_system", None),
                    system_suggestion=getattr(event, "system_suggestion", None),
                    options_presented=getattr(event, "options_presented", None),
                    human_selection=getattr(event, "human_selection", None),
                    decision_timestamp=getattr(event, "decision_timestamp", None),
                )

                # Verify this event's hash matches stored
                if recomputed_hash != event.event_hash:
                    mismatches.append({
                        "chain_id": chain_id,
                        "event_id": str(event.event_id),
                        "reason": "hash_mismatch",
                        "computed": recomputed_hash,
                        "stored": event.event_hash,
                    })

                # Update for next iteration
                prior_recomputed_hash = recomputed_hash
                recomputed_head_hash = recomputed_hash

            # Compare recomputed head hash to stored last event_hash
            if events_sorted:
                last_event = events_sorted[-1]
                if recomputed_head_hash != last_event.event_hash:
                    mismatches.append({
                        "chain_id": chain_id,
                        "event_id": str(last_event.event_id),
                        "reason": "head_hash_mismatch",
                        "computed_head": recomputed_head_hash,
                        "stored_head": last_event.event_hash,
                    })

    status = "PASS" if not mismatches else "FAIL"
    result = {
        "verified_at": verified_at,
        "chains_checked": chains_checked,
        "status": status,
    }
    if mismatches:
        result["details"] = mismatches

    # External anchoring: get anchored chain commitment if verification passed
    if status == "PASS":
        anchored_commitment = _get_anchored_chain_commitment()
        if anchored_commitment:
            result["anchored_commitment"] = anchored_commitment

    return result


def send_heartbeat_email(result_dict):
    """
    Send integrity verification heartbeat email using smtplib.

    Reads SMTP config from environment variables:
        SMTP_HOST
        SMTP_PORT
        SMTP_USERNAME
        SMTP_PASSWORD
        HEARTBEAT_TO
        HEARTBEAT_FROM

    Args:
        result_dict: Result dict from verify_integrity()
    """
    from email.message import EmailMessage
    import smtplib

    # Read config from environment
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    heartbeat_to = os.getenv("HEARTBEAT_TO")
    heartbeat_from = os.getenv("HEARTBEAT_FROM")

    if not all([smtp_host, smtp_username, smtp_password, heartbeat_to, heartbeat_from]):
        raise ValueError(
            "Missing required environment variables: "
            "SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, HEARTBEAT_TO, HEARTBEAT_FROM"
        )

    # Build email
    msg = EmailMessage()
    msg["From"] = heartbeat_from
    msg["To"] = heartbeat_to

    verified_at = result_dict["verified_at"]
    status = result_dict["status"]

    # Subject format
    if status == "PASS":
        msg["Subject"] = f"[OK][ANCHOR] Integrity Verification — {verified_at}"
    else:
        msg["Subject"] = f"[URGENT][FAIL] Integrity Verification — {verified_at}"

    # Body
    body_lines = [
        f"Verified at: {verified_at}",
        f"Chains checked: {result_dict['chains_checked']}",
        f"Status: {status}",
    ]

    if result_dict.get("details"):
        body_lines.append("")
        body_lines.append("Mismatches:")
        for mismatch in result_dict["details"]:
            body_lines.append(f"  Chain: {mismatch['chain_id']}")
            body_lines.append(f"  Event ID: {mismatch['event_id']}")
            body_lines.append(f"  Reason: {mismatch['reason']}")
            if "computed" in mismatch:
                body_lines.append(f"  Computed: {mismatch['computed'][:32]}...")
                body_lines.append(f"  Stored: {mismatch['stored'][:32] if mismatch.get('stored') else 'NULL'}...")
            elif "computed_head" in mismatch:
                body_lines.append(f"  Computed head: {mismatch['computed_head'][:32]}...")
                body_lines.append(f"  Stored head: {mismatch['stored_head'][:32] if mismatch.get('stored_head') else 'NULL'}...")
            elif "expected" in mismatch:
                body_lines.append(f"  Expected: {mismatch['expected'][:32] if mismatch.get('expected') else 'NULL'}...")
                body_lines.append(f"  Stored: {mismatch['stored'][:32] if mismatch.get('stored') else 'NULL'}...")
            body_lines.append("")

    # Anchored Chain Commitment (only if PASS)
    if result_dict.get("anchored_commitment"):
        commitment = result_dict["anchored_commitment"]
        body_lines.append("")
        body_lines.append("Anchored Chain Commitment:")
        body_lines.append(f"  Chain ID: {commitment['chain_id']}")
        body_lines.append(f"  Head Hash: {commitment['event_hash']}")
        body_lines.append(f"  Head Event Timestamp: {commitment['occurred_at_utc']}")
        body_lines.append(f"  Total Events: {commitment['event_count']}")

    msg.set_content("\n".join(body_lines))

    # Send email
    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        smtp.starttls()
        smtp.login(smtp_username, smtp_password)
        smtp.send_message(msg)
