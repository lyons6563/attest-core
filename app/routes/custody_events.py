from datetime import datetime, timezone
import uuid
import hashlib
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from app.db import get_db
from app.crypto.event_hash import compute_event_hash, format_occurred_at_utc
import json
import csv
import zipfile
import io

router = APIRouter()

# custody_events is append-only: no UPDATE or DELETE paths. event_hash is
# always computed before INSERT. Corrections are new events referencing prior
# event_id; overwrites are not supported.

# Deterministic ordering for chain verification, receipt, and evidence (no ties).
EVENTS_ORDER_SQL = """
    ORDER BY occurred_at_utc ASC, event_id ASC
"""


def _run_verification(chain_id: str, events: list) -> tuple[bool, list]:
    failures = []
    prior_event_hash = None
    prior_occurred_at_utc = None

    for index, event in enumerate(events):
        # Canonical UTC string (same as at event creation)
        occurred_at_utc_str = format_occurred_at_utc(event.occurred_at_utc)

        # EVENT_OUT_OF_ORDER: timeline sanity check
        if prior_occurred_at_utc is not None:
            if occurred_at_utc_str < prior_occurred_at_utc:
                failures.append({
                    "index": index,
                    "event_id": str(event.event_id),
                    "reason": "event_out_of_order: occurred_at_utc earlier than previous event"
                })

        # Recompute event_hash (identity + decision fields when present;
        # legacy events without them use 6-part hash).
        computed_hash = compute_event_hash(
            chain_id=chain_id,
            event_type=event.event_type,
            actor=event.actor,
            occurred_at_utc=occurred_at_utc_str,
            payload_hash=event.payload_hash,
            previous_event_hash=event.previous_event_hash,
            actor_id=getattr(event, "actor_id", None),
            session_id=getattr(event, "session_id", None),
            source_system=getattr(event, "source_system", None),
            system_suggestion=getattr(event, "system_suggestion", None),
            options_presented=getattr(event, "options_presented", None),
            human_selection=getattr(event, "human_selection", None),
            decision_timestamp=getattr(event, "decision_timestamp", None),
        )

        stored_hash = event.event_hash
        if computed_hash != stored_hash:
            failures.append({
                "index": index,
                "event_id": str(event.event_id),
                "reason": (
                    "hash_mismatch: recomputed hash does not match stored "
                    f"(computed={computed_hash[:16]}..., stored={stored_hash[:16] if stored_hash else 'NULL'}...)"
                ),
            })

        # previous_event_hash continuity
        if index == 0:
            if event.previous_event_hash is not None:
                failures.append({
                    "index": index,
                    "event_id": str(event.event_id),
                    "reason": "previous_event_hash must be null for first event",
                })
        else:
            if event.previous_event_hash != prior_event_hash:
                failures.append({
                    "index": index,
                    "event_id": str(event.event_id),
                    "reason": (
                        "chain_break: previous_event_hash does not equal prior event_hash "
                        f"(expected {prior_event_hash[:16] if prior_event_hash else 'NULL'}...)"
                    ),
                })

        # Remember current event for next iteration
        prior_occurred_at_utc = occurred_at_utc_str
        prior_event_hash = event.event_hash

    verified = len(failures) == 0
    return verified, failures


class ReceivedEventRequest(BaseModel):
    actor: str
    payload_hash: str
    actor_id: str | None = None  # always populated for audit; default from actor when omitted
    session_id: str | None = None  # always populated for audit; default new UUID when omitted
    source_system: str | None = None  # always populated for audit; default "api" when omitted
    system_suggestion: str | None = None
    options_presented: str | None = None
    human_selection: str | None = None
    decision_timestamp: datetime | None = None


class RecordEventRequest(BaseModel):
    event_type: str
    actor_id: str
    session_id: str
    source_system: str
    payload_hash: str
    system_suggestion: str | None = None
    options_presented: str | None = None
    human_selection: str | None = None
    occurred_at_utc: str  # ISO format string


@router.post("/chains/{chain_id}/received")
def add_received_event(
    chain_id: str,
    req: ReceivedEventRequest,
    db = Depends(get_db),
):
    # 1. Verify chain exists
    chain = db.execute(
        text("SELECT chain_id FROM custody_chains WHERE chain_id = :cid"),
        {"cid": chain_id}
    ).fetchone()

    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    # 2. Fetch latest event
    prev = db.execute(
        text("""
            SELECT event_hash
            FROM custody_events
            WHERE chain_id = :cid
            ORDER BY occurred_at_utc DESC
            LIMIT 1
        """),
        {"cid": chain_id}
    ).fetchone()

    if not prev or not prev.event_hash:
        raise HTTPException(status_code=400, detail="Previous event missing hash")

    previous_event_hash = prev.event_hash

    # 3. Identity always populated (safe defaults). Append-only: single INSERT
    #    with event_hash computed above; no UPDATE/DELETE on custody_events.
    actor_id = req.actor_id or req.actor
    session_id = req.session_id or str(uuid.uuid4())
    source_system = req.source_system or "api"
    occurred_at_utc_dt = datetime.now(timezone.utc)
    occurred_at_utc_str = format_occurred_at_utc(occurred_at_utc_dt)
    decision_ts = req.decision_timestamp or occurred_at_utc_dt
    decision_ts_str = format_occurred_at_utc(decision_ts) if decision_ts else ""

    event_hash = compute_event_hash(
        chain_id=chain_id,
        event_type="RECEIVED",
        actor=req.actor,
        occurred_at_utc=occurred_at_utc_str,
        payload_hash=req.payload_hash,
        previous_event_hash=previous_event_hash,
        actor_id=actor_id,
        session_id=session_id,
        source_system=source_system,
        system_suggestion=req.system_suggestion,
        options_presented=req.options_presented,
        human_selection=req.human_selection,
        decision_timestamp=decision_ts,
    )

    inserted = db.execute(
        text("""
            INSERT INTO custody_events (
                chain_id,
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
            )
            VALUES (
                :cid,
                'RECEIVED',
                :actor,
                :payload_hash,
                :prev_hash,
                :event_hash,
                :occurred_at_utc,
                :actor_id,
                :session_id,
                :source_system,
                :system_suggestion,
                :options_presented,
                :human_selection,
                :decision_timestamp
            )
            RETURNING event_id
        """),
        {
            "cid": chain_id,
            "actor": req.actor,
            "payload_hash": req.payload_hash,
            "prev_hash": previous_event_hash,
            "event_hash": event_hash,
            "occurred_at_utc": occurred_at_utc_dt,
            "actor_id": actor_id,
            "session_id": session_id,
            "source_system": source_system,
            "system_suggestion": req.system_suggestion,
            "options_presented": req.options_presented,
            "human_selection": req.human_selection,
            "decision_timestamp": decision_ts,
        }
    ).fetchone()

    event_id = inserted.event_id
    db.commit()

    return {
        "event_id": str(event_id),
        "event_hash": event_hash,
    }


@router.post("/events/record")
def record_event(
    req: RecordEventRequest,
    db = Depends(get_db),
):
    """
    Record a single custody event (e.g., from browser extension).
    Creates or uses a chain per actor_id+source_system combination.
    Append-only: event_hash computed before INSERT.
    """
    # 1. Get or create chain for this actor_id+source_system
    # Use hash of key to avoid conflicts with real file hashes
    chain_key = f"{req.actor_id}:{req.source_system}"
    chain_key_hash = hashlib.sha256(chain_key.encode("utf-8")).hexdigest()
    
    chain = db.execute(
        text("""
            SELECT chain_id, root_file_hash
            FROM custody_chains
            WHERE root_file_hash = :key_hash
            LIMIT 1
        """),
        {"key_hash": chain_key_hash}
    ).fetchone()

    if not chain:
        # Create new chain (using hash of chain_key as root_file_hash for browser extension chains)
        chain_id_result = db.execute(
            text("""
                INSERT INTO custody_chains (root_file_hash, status)
                VALUES (:key_hash, 'OPEN')
                RETURNING chain_id
            """),
            {"key_hash": chain_key_hash}
        ).fetchone()
        chain_id = str(chain_id_result.chain_id)
    else:
        chain_id = str(chain.chain_id)

    # 2. Fetch latest event for chain continuity
    prev = db.execute(
        text("""
            SELECT event_hash
            FROM custody_events
            WHERE chain_id = :cid
            ORDER BY occurred_at_utc DESC, event_id DESC
            LIMIT 1
        """),
        {"cid": chain_id}
    ).fetchone()

    previous_event_hash = prev.event_hash if prev else None

    # 3. Parse occurred_at_utc and compute event_hash
    occurred_at_utc_dt = datetime.fromisoformat(req.occurred_at_utc.replace("Z", "+00:00"))
    occurred_at_utc_str = format_occurred_at_utc(occurred_at_utc_dt)
    decision_ts = datetime.fromisoformat(req.occurred_at_utc.replace("Z", "+00:00")) if req.human_selection else None

    event_hash = compute_event_hash(
        chain_id=chain_id,
        event_type=req.event_type,
        actor=req.actor_id,  # Use actor_id as actor for browser extension events
        occurred_at_utc=occurred_at_utc_str,
        payload_hash=req.payload_hash,
        previous_event_hash=previous_event_hash,
        actor_id=req.actor_id,
        session_id=req.session_id,
        source_system=req.source_system,
        system_suggestion=req.system_suggestion,
        options_presented=req.options_presented,
        human_selection=req.human_selection,
        decision_timestamp=decision_ts,
    )

    # 4. Insert event (append-only: single INSERT with hash)
    inserted = db.execute(
        text("""
            INSERT INTO custody_events (
                chain_id,
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
            )
            VALUES (
                :cid,
                :event_type,
                :actor,
                :payload_hash,
                :prev_hash,
                :event_hash,
                :occurred_at_utc,
                :actor_id,
                :session_id,
                :source_system,
                :system_suggestion,
                :options_presented,
                :human_selection,
                :decision_timestamp
            )
            RETURNING event_id
        """),
        {
            "cid": chain_id,
            "event_type": req.event_type,
            "actor": req.actor_id,
            "payload_hash": req.payload_hash,
            "prev_hash": previous_event_hash,
            "event_hash": event_hash,
            "occurred_at_utc": occurred_at_utc_dt,
            "actor_id": req.actor_id,
            "session_id": req.session_id,
            "source_system": req.source_system,
            "system_suggestion": req.system_suggestion,
            "options_presented": req.options_presented,
            "human_selection": req.human_selection,
            "decision_timestamp": decision_ts,
        }
    ).fetchone()

    event_id = inserted.event_id
    db.commit()

    return {
        "event_id": str(event_id),
        "event_hash": event_hash,
        "chain_id": chain_id,
    }


@router.get("/chains/{chain_id}")
def get_chain(
    chain_id: str,
    db = Depends(get_db),
):
    # 1. Verify chain exists and fetch metadata
    chain = db.execute(
        text("""
            SELECT chain_id, root_file_hash, status, created_at_utc
            FROM custody_chains
            WHERE chain_id = :cid
        """),
        {"cid": chain_id}
    ).fetchone()

    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    # 2. Fetch all events for this chain (deterministic order)
    events = db.execute(
        text("""
            SELECT
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
            WHERE chain_id = :cid
            """ + EVENTS_ORDER_SQL),
        {"cid": chain_id}
    ).fetchall()

    # 3. Build response
    return {
        "chain_id": str(chain.chain_id),
        "root_file_hash": chain.root_file_hash,
        "status": chain.status,
        "created_at_utc": chain.created_at_utc.isoformat() if chain.created_at_utc else None,
        "events": [
            {
                "event_id": str(e.event_id),
                "event_type": e.event_type,
                "actor": e.actor,
                "payload_hash": e.payload_hash,
                "previous_event_hash": e.previous_event_hash,
                "event_hash": e.event_hash,
                "occurred_at_utc": e.occurred_at_utc.isoformat() if e.occurred_at_utc else None,
                "actor_id": e.actor_id,
                "session_id": e.session_id,
                "source_system": e.source_system,
                "system_suggestion": e.system_suggestion,
                "options_presented": e.options_presented,
                "human_selection": e.human_selection,
                "decision_timestamp": e.decision_timestamp.isoformat() if getattr(e, "decision_timestamp", None) else None,
            }
            for e in events
        ],
    }


@router.get("/chains/{chain_id}/verify")
def verify_chain(
    chain_id: str,
    db = Depends(get_db),
):
    """
    Verify chain integrity: full hash recomputation and previous_event_hash
    continuity. Read-only; deterministic ordering by occurred_at_utc, event_id.
    Returns verified boolean and failures list (index, event_id, reason).
    """
    chain = db.execute(
        text("""
            SELECT chain_id, root_file_hash, status
            FROM custody_chains
            WHERE chain_id = :cid
        """),
        {"cid": chain_id}
    ).fetchone()

    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    events = db.execute(
        text("""
            SELECT
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
            WHERE chain_id = :cid
            """ + EVENTS_ORDER_SQL),
        {"cid": chain_id}
    ).fetchall()

    verified, failures = _run_verification(chain_id, events)

    return {
        "verified": verified,
        "failures": failures,
    }


@router.get("/chains/{chain_id}/receipt")
def get_decision_receipt(
    chain_id: str,
    db = Depends(get_db),
):
    """
    Deterministic, chronological decision receipt: timestamp, actor_id, action_type,
    inputs, outputs. Order: occurred_at_utc ASC, event_id ASC (reproducible).
    Append-only: no edits; corrections are new events.
    """
    chain = db.execute(
        text("SELECT chain_id, root_file_hash FROM custody_chains WHERE chain_id = :cid"),
        {"cid": chain_id}
    ).fetchone()

    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    events = db.execute(
        text("""
            SELECT
                event_id,
                event_type,
                actor_id,
                session_id,
                source_system,
                occurred_at_utc,
                payload_hash,
                system_suggestion,
                options_presented,
                human_selection,
                decision_timestamp
            FROM custody_events
            WHERE chain_id = :cid
            """ + EVENTS_ORDER_SQL),
        {"cid": chain_id}
    ).fetchall()

    receipt = []
    for e in events:
        ts = e.occurred_at_utc.isoformat() if e.occurred_at_utc else None
        decision_ts = getattr(e, "decision_timestamp", None)
        decision_ts_str = decision_ts.isoformat() if decision_ts else ts
        receipt.append({
            "timestamp": ts,
            "actor_id": getattr(e, "actor_id", None),
            "action_type": e.event_type,
            "inputs": {
                "payload_hash": e.payload_hash,
                "system_suggestion": getattr(e, "system_suggestion", None),
                "options_presented": getattr(e, "options_presented", None),
            },
            "outputs": {
                "event_id": str(e.event_id),
                "human_selection": getattr(e, "human_selection", None),
                "decision_timestamp": decision_ts_str,
            },
        })

    return {"chain_id": str(chain_id), "receipt": receipt}


@router.get("/chains/{chain_id}/evidence.zip")
def get_evidence_zip(
    chain_id: str,
    db = Depends(get_db),
):
    """
    Stream evidence ZIP (stdlib only). Contents: manifest.json (identity +
    decision fields per event), timeline.csv (same), verification.json (same
    as /verify). Order: occurred_at_utc ASC, event_id ASC. No new tables.
    """
    chain = db.execute(
        text("""
            SELECT chain_id, root_file_hash, status
            FROM custody_chains
            WHERE chain_id = :cid
        """),
        {"cid": chain_id}
    ).fetchone()

    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    events = db.execute(
        text("""
            SELECT
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
            WHERE chain_id = :cid
            """ + EVENTS_ORDER_SQL),
        {"cid": chain_id}
    ).fetchall()

    verified, failures = _run_verification(chain_id, events)

    # manifest.json: chain metadata + events array (identity and decision clarity)
    manifest = {
        "chain_id": str(chain.chain_id),
        "root_file_hash": chain.root_file_hash,
        "status": chain.status,
        "events": [
            {
                "event_id": str(e.event_id),
                "event_type": e.event_type,
                "actor": e.actor,
                "actor_id": getattr(e, "actor_id", None),
                "session_id": getattr(e, "session_id", None),
                "source_system": getattr(e, "source_system", None),
                "occurred_at_utc": e.occurred_at_utc.isoformat() if e.occurred_at_utc else None,
                "system_suggestion": getattr(e, "system_suggestion", None),
                "options_presented": getattr(e, "options_presented", None),
                "human_selection": getattr(e, "human_selection", None),
                "decision_timestamp": e.decision_timestamp.isoformat() if getattr(e, "decision_timestamp", None) else None,
            }
            for e in events
        ],
    }

    # timeline.csv: full columns for audit
    timeline_buf = io.StringIO()
    timeline_writer = csv.writer(timeline_buf)
    timeline_writer.writerow([
        "occurred_at_utc",
        "event_type",
        "actor",
        "actor_id",
        "session_id",
        "source_system",
        "payload_hash",
        "previous_event_hash",
        "event_hash",
        "system_suggestion",
        "options_presented",
        "human_selection",
        "decision_timestamp",
    ])
    for e in events:
        _dt = getattr(e, "decision_timestamp", None)
        timeline_writer.writerow([
            e.occurred_at_utc.isoformat() if e.occurred_at_utc else "",
            e.event_type or "",
            e.actor or "",
            getattr(e, "actor_id", "") or "",
            getattr(e, "session_id", "") or "",
            getattr(e, "source_system", "") or "",
            e.payload_hash or "",
            e.previous_event_hash or "",
            e.event_hash or "",
            getattr(e, "system_suggestion", "") or "",
            getattr(e, "options_presented", "") or "",
            getattr(e, "human_selection", "") or "",
            _dt.isoformat() if _dt else "",
        ])

    # verification.json: exact same structure as GET /chains/{chain_id}/verify
    verification = {
        "verified": verified,
        "failures": failures,
    }

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("timeline.csv", timeline_buf.getvalue())
        zf.writestr("verification.json", json.dumps(verification, indent=2))

    zip_buf.seek(0)
    return StreamingResponse(
        io.BytesIO(zip_buf.read()),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=chain_{chain_id}_evidence.zip"},
    )
