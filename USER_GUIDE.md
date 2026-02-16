# Decision Engine — User Guide

Simple steps to run the app and record custody chains.

---

## 1. Prerequisites

- **Python 3.9+** (with pip)
- **PostgreSQL** on `127.0.0.1:5433`, database `decision_engine`, user `postgres`, password `postgres`

**Start PostgreSQL (one command; requires Docker Desktop running)**

From the project root:

```powershell
.\scripts\ensure-postgres.ps1
```

This checks Docker is running, starts the `decision-engine-db` container on port 5433 if needed, runs the audit hardening migration, and verifies the `custody_events` columns. If Docker is not running, the script tells you to start Docker Desktop and try again.

**Or start Postgres manually (Docker)**

```powershell
docker run -d --name decision-engine-db -p 5433:5432 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=decision_engine postgres:15
```

**Or create the database locally**

```powershell
psql -U postgres -h 127.0.0.1 -p 5433 -c "CREATE DATABASE decision_engine;"
```

Create tables from `migrations/` if needed. The app expects `custody_chains`, `custody_events`, `ingestion_events`.

---

## 2. Run the app

From the project root:

```powershell
cd C:\Users\samly\Documents\decision-engine
pip install fastapi uvicorn sqlalchemy psycopg2-binary
uvicorn app.main:app --reload
```

- App: **http://127.0.0.1:8000**
- Docs: **http://127.0.0.1:8000/docs**

Stop: **Ctrl+C** in the terminal.

---

## 3. Simple flow with prompts

### Step 1 — Check health

**Prompt (browser or curl):**

```
GET http://127.0.0.1:8000/
```

**Expected:** `{"status":"alive"}`

---

### Step 2 — Ingest a file

**Prompt (Swagger):** Open **POST /ingest** → **Try it out** → choose a file → **Execute**.

**Prompt (curl):**

```powershell
curl -X POST "http://127.0.0.1:8000/ingest" -H "Content-Type: multipart/form-data" -F "file=@data/system_a_transactions.csv"
```

**Optional headers (identity):**

```text
X-Actor-Id: sam
X-Session-Id: your-session-uuid
X-Source-System: ingest-api
```

**Expected:** Response includes `custody_chain_id`. Copy it for the next steps.

---

### Step 3 — View the chain

**Prompt:** Replace `{chain_id}` with the UUID from Step 2.

```
GET http://127.0.0.1:8000/chains/{chain_id}
```

**Prompt (curl):**

```powershell
curl "http://127.0.0.1:8000/chains/YOUR_CHAIN_ID"
```

**Expected:** Chain metadata and list of events (e.g. one TRANSMITTED).

---

### Step 4 — Add a RECEIVED event (optional)

**Prompt (request body):**

```json
{
  "actor": "custodian",
  "payload_hash": "<same as root_file_hash from chain>",
  "actor_id": "sam",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_system": "api",
  "system_suggestion": "Optional: what the system recommended",
  "options_presented": null,
  "human_selection": "Optional: e.g. option 1"
}
```

**Prompt (Swagger):** **POST /chains/{chain_id}/received** → **Try it out** → paste `chain_id` → paste body above (edit `payload_hash`) → **Execute**.

**Prompt (curl):**

```powershell
curl -X POST "http://127.0.0.1:8000/chains/YOUR_CHAIN_ID/received" -H "Content-Type: application/json" -d "{\"actor\":\"custodian\",\"payload_hash\":\"YOUR_ROOT_FILE_HASH\"}"
```

**Expected:** `event_id` and `event_hash`.

---

### Step 5 — Verify the chain

**Prompt:**

```
GET http://127.0.0.1:8000/chains/{chain_id}/verify
```

**Prompt (curl):**

```powershell
curl "http://127.0.0.1:8000/chains/YOUR_CHAIN_ID/verify"
```

**Expected:** `"verified": true`, `"failures": []` if the chain is intact.

---

### Step 6 — Download evidence

**Prompt:**

```
GET http://127.0.0.1:8000/chains/{chain_id}/evidence.zip
```

**Prompt (curl):**

```powershell
curl -o evidence.zip "http://127.0.0.1:8000/chains/YOUR_CHAIN_ID/evidence.zip"
```

**Expected:** ZIP with `manifest.json`, `timeline.csv`, `verification.json`.

---

### Step 7 — Decision receipt (chronological view)

**Prompt:**

```
GET http://127.0.0.1:8000/chains/{chain_id}/receipt
```

**Expected:** `receipt` array with `timestamp`, `actor_id`, `action_type`, `inputs`, `outputs` per event.

---

## 4. Quick reference

| What you want        | Method & path                          |
|----------------------|----------------------------------------|
| Health               | `GET /`                                |
| Ingest file          | `POST /ingest` (form: file)            |
| View chain           | `GET /chains/{chain_id}`               |
| Add RECEIVED event   | `POST /chains/{chain_id}/received`     |
| Verify               | `GET /chains/{chain_id}/verify`       |
| Evidence ZIP         | `GET /chains/{chain_id}/evidence.zip`  |
| Decision receipt     | `GET /chains/{chain_id}/receipt`       |
| Record event (e.g. extension) | `POST /events/record`          |

**RECEIVED body (minimal):**

```json
{"actor": "custodian", "payload_hash": "<sha256-hex>"}
```

**RECEIVED body (full identity + decision):**

```json
{
  "actor": "custodian",
  "payload_hash": "<sha256-hex>",
  "actor_id": "sam",
  "session_id": "<uuid>",
  "source_system": "api",
  "system_suggestion": null,
  "options_presented": null,
  "human_selection": null
}
```

---

## 5. Troubleshooting

- **404 Chain not found** — Use the `custody_chain_id` from the ingest response.
- **DB errors** — Postgres on port 5433, database `decision_engine`, user/password `postgres`.
- **Verify failures** — Hashes don’t match; check failure `index` and `reason`.

That’s everything you need to use the Decision Engine end to end.
