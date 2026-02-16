from fastapi import FastAPI, UploadFile, File
from pathlib import Path
import shutil
import hashlib
import uuid

# ----------------------------
# App
# ----------------------------
app = FastAPI()

# ----------------------------
# Storage
# ----------------------------
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# ----------------------------
# Database (single source of truth: app.db)
# ----------------------------
from app.db import get_psycopg2_conn as get_conn

# ----------------------------
# Health check
# ----------------------------
@app.get("/")
def health():
    return {"status": "alive"}

# ----------------------------
# INGEST (AUTO chain + TRANSMITTED)
# ----------------------------
@app.post("/ingest")
def ingest(file: UploadFile = File(...)):
    conn = get_conn()
    cur = conn.cursor()

    try:
        # ---- 1. Save file
        file_path = DATA_DIR / file.filename
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # ---- 2. Count rows
        row_count = sum(
            1 for _ in open(file_path, "r", encoding="utf-8", errors="ignore")
        )

        # ---- 3. Hash payload
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            hasher.update(f.read())
        file_hash = hasher.hexdigest()

        # ---- 4. Create custody chain (AUTO, authoritative)
        chain_id = str(uuid.uuid4())

        cur.execute(
            """
            INSERT INTO custody_chains (
                chain_id,
                root_file_hash
            )
            VALUES (%s, %s);
            """,
            (chain_id, file_hash)
        )

        # ---- 5. Insert ingestion event (references chain)
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
            (file.filename, file_hash, row_count, chain_id)
        )
        ingestion_id = cur.fetchone()[0]

        # ---- 6. Insert TRANSMITTED custody event
        cur.execute(
            """
            INSERT INTO custody_events (
                chain_id,
                event_type,
                actor,
                payload_hash,
                previous_event_hash,
                event_hash
            )
            VALUES (
                %s,
                'TRANSMITTED',
                'plan_sponsor',
                %s,
                NULL,
                encode(
                  digest(
                    %s || 'TRANSMITTED' || 'plan_sponsor',
                    'sha256'
                  ),
                  'hex'
                )
            );
            """,
            (chain_id, file_hash, file_hash)
        )

        conn.commit()

        return {
            "status": "ingested",
            "ingestion_id": str(ingestion_id),
            "custody_chain_id": chain_id,
            "filename": file.filename,
            "row_count": row_count,
            "file_hash": file_hash
        }

    finally:
        cur.close()
        conn.close()
