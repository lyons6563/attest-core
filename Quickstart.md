# Decision Engine — Quickstart

Get the app running in two steps. No Docker knowledge required; the script sets up the database for you.

---

## What you need

- **Windows** with **PowerShell**
- **Docker Desktop** installed and running (the script will tell you if it is not)
- **Python 3.9+** with pip (for running the app)

---

## Step 1 — Set up the database

Open PowerShell, go to the project folder (the one that contains `app\` and `scripts\`), and run:

```powershell
.\scripts\ensure-postgres.ps1
```

**What this does:**

- Checks that Docker Desktop is running (if not, you get a clear message to start it)
- Stops and removes any existing database container, then creates a fresh one
- Exposes Postgres on **127.0.0.1:5433** (so the app always connects to this Docker database)
- Runs the base schema and audit hardening migrations
- Verifies that required tables and columns exist

**When it works:** You see **READY** at the end and a reminder to start the app.

**If something fails:** You see **FAIL** and a short message explaining what went wrong and what to do next. Fix that, then run the same command again. Safe to run multiple times.

---

## Step 2 — Start the app

In the same project folder, run:

```powershell
uvicorn app.main:app --reload
```

**What this does:**

- Starts the FastAPI app
- On startup it logs: **host**, **port**, and **database name** (127.0.0.1, 5433, decision_engine)
- Validates the database schema; if anything is missing, the app exits with a clear error and tells you to run `.\scripts\ensure-postgres.ps1` again

**When it works:** You see something like:

```
[DB] host='127.0.0.1' port=5433 database='decision_engine'
[DB] Schema OK (tables and audit columns present)
```

Then open **http://127.0.0.1:8000** and **http://127.0.0.1:8000/docs**.

---

## Summary

| Step | Command | Purpose |
|------|---------|--------|
| 1 | `.\scripts\ensure-postgres.ps1` | Set up Postgres in Docker and run migrations. Prints READY or FAIL. |
| 2 | `uvicorn app.main:app --reload` | Start the app. It connects to 127.0.0.1:5433 and checks the schema on startup. |

**First time:** Install dependencies once:

```powershell
pip install fastapi uvicorn sqlalchemy psycopg2-binary
```

**Next time:** Just run Step 1 (if you need a fresh or correct database), then Step 2. No manual Docker or migration steps required.

**If schema validation fails right after migrations (especially on Windows with `--reload`):** `uvicorn --reload` can cause the app to see a stale schema. Run the app once without `--reload` after running the script, e.g. `uvicorn app.main:app`, or run `.\scripts\ensure-postgres.ps1` again and then start with `--reload`.
