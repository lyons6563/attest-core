from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import shutil
import hashlib
import uuid

from fastapi import FastAPI, UploadFile, File, Request
from app.db import get_psycopg2_conn, get_db_config, validate_schema
from app.routes.custody_events import router as custody_events_router
from app.crypto.event_hash import compute_event_hash, format_occurred_at_utc


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: log DB connection target and fail fast if schema is missing."""
    cfg = get_db_config()
    print(f"[DB] host={cfg['host']!r} port={cfg['port']} database={cfg['database']!r}")
    validate_schema()
    print("[DB] Schema OK (tables and audit columns present)")
    yield
    # shutdown: nothing to close (connections are per-request)


app = FastAPI(lifespan=lifespan)
app.include_router(custody_events_router)

# ----------------------------
# Storage
# ----------------------------
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# ----------------------------
# Health
# ----------------------------
@app.get("/")
def health():
    return {"status": "alive"}

# ----------------------------
# INGEST (CHAIN-FIRST)
# ----------------------------
@app.post("/ingest")
def ingest(request: Request, file: UploadFile = File(...)):
    # Identity: every action attributable to one actor, one session, one system
    actor_id = request.headers.get("X-Actor-Id") or "system"
    session_id = request.headers.get("X-Session-Id") or str(uuid.uuid4())
    source_system = request.headers.get("X-Source-System") or "ingest-api"

    conn = get_psycopg2_conn()
    cur = conn.cursor()

    try:
        # 1. Save file
        file_path = DATA_DIR / file.filename
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 2. Count rows
        row_count = sum(
            1 for _ in open(file_path, "r", encoding="utf-8", errors="ignore")
        )

        # 3. Hash file (root truth)
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            hasher.update(f.read())
        file_hash = hasher.hexdigest()

        # 4. Create custody chain (Postgres owns UUID)
        cur.execute(
            """
            INSERT INTO custody_chains (
                root_file_hash,
                status
            )
            VALUES (%s, %s)
            RETURNING chain_id;
            """,
            (file_hash, "OPEN")
        )
        custody_chain_id = cur.fetchone()[0]

        # 5. Insert ingestion event
        cur.execute(
            """
            INSERT INTO ingestion_events (
                filename,
                file_hash,
                row_count,
                custody_chain_id
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """,
            (file.filename, file_hash, row_count, custody_chain_id)
        )
        ingestion_id = cur.fetchone()[0]

        # 6. First custody event: TRANSMITTED. Append-only: event_hash computed
        #    before INSERT; no UPDATE/DELETE on custody_events.
        occurred_at_utc_dt = datetime.now(timezone.utc)
        occurred_at_utc_str = format_occurred_at_utc(occurred_at_utc_dt)
        event_hash = compute_event_hash(
            chain_id=str(custody_chain_id),
            event_type="TRANSMITTED",
            actor="plan_sponsor",
            occurred_at_utc=occurred_at_utc_str,
            payload_hash=file_hash,
            previous_event_hash=None,
            actor_id=actor_id,
            session_id=session_id,
            source_system=source_system,
        )
        cur.execute(
            """
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
                source_system
            )
            VALUES (%s, 'TRANSMITTED', 'plan_sponsor', %s, NULL, %s, %s, %s, %s, %s);
            """,
            (custody_chain_id, file_hash, event_hash, occurred_at_utc_dt, actor_id, session_id, source_system)
        )

        conn.commit()

        return {
            "status": "ingested",
            "filename": file.filename,
            "row_count": row_count,
            "file_hash": file_hash,
            "custody_chain_id": str(custody_chain_id),
            "ingestion_id": str(ingestion_id),
        }

    finally:
        cur.close()
        conn.close()
