# Attest

**Attest** is an append-only decision provenance core that produces tamper-evident, independently verifiable decision records.

---

## The problem it solves

Organizations need a defensible record of who decided what, when, and on what inputs—for regulatory examination, internal audit, and legal discovery. Without a cryptographically bound, append-only log, decision trails can be altered or disputed. Attest provides a single, verifiable source of truth: each decision is hashed, linked to the previous event in a chain, and exportable as a portable proof pack that any party can verify without trusting the originating system.

---

## Core principles

- **Append-only.** No UPDATE or DELETE on decision events. Corrections are new events that reference the prior event; the history is immutable.
- **Hash-chained.** Each event’s `event_hash` is computed from a canonical representation (chain_id, event_type, actor, payload_hash, previous_event_hash, timestamps, and audit fields). The stored `previous_event_hash` links to the prior event. Breaking or rewriting any link invalidates the chain.
- **Deterministic.** Ordering is fixed (e.g. `occurred_at_utc ASC`, `event_id ASC`). Hash computation uses normalized strings and canonical UTC timestamps so the same inputs yield the same hash everywhere.
- **Portable proof pack.** A chain can be exported as a ZIP (events, receipt, verification result). Third parties can recompute hashes and check `previous_event_hash` continuity without access to the live database.

---

## Architecture overview

- **Ledger.** PostgreSQL holds three tables: `custody_chains` (one row per logical chain, with `root_file_hash`, `status`), `custody_events` (append-only events with `event_hash`, `previous_event_hash`, and audit columns), and `ingestion_events` (ingestion metadata). The app connects to a single database instance; no env-based drift (fixed host/port).
- **Chain.** A chain is a sequence of events sharing a `chain_id`. Events have types such as `TRANSMITTED`, `RECEIVED`, `AI_DECISION_ATTESTED`. Each event stores a `payload_hash` (e.g. hash of input or structured payload) and its `event_hash`; `previous_event_hash` ties to the prior event’s `event_hash`.
- **Verification.** Integrity is checked by replay: load events in deterministic order, recompute each `event_hash` using the same canonical function and the *recomputed* prior hash, and compare the final head hash to the stored last `event_hash`. A heartbeat job can run this across all chains and optionally report an anchored chain commitment (e.g. for external timestamping).

---

## Quick start

**Requirements:** Windows, PowerShell, Docker Desktop, Python 3.9+.

1. **Set up the database** (from project root):

   ```powershell
   .\scripts\ensure-postgres.ps1
   ```

   This script ensures Docker is running, creates/recreates the Postgres container on host port **55432**, runs base schema and audit-hardening migrations, and verifies required tables and columns. On success it prints **READY**.

2. **Start the API:**

   ```powershell
   pip install fastapi uvicorn sqlalchemy psycopg2-binary
   uvicorn app.main:app --reload
   ```

   The app binds to the database at `127.0.0.1:55432`, validates schema on startup, and serves at `http://127.0.0.1:8000` (docs at `/docs`).

---

## How verification works

1. **Per-chain (API).** `GET /chains/{chain_id}/verify` loads all events for that chain in deterministic order, then for each event: formats `occurred_at_utc` canonically, recomputes `event_hash` using `previous_event_hash` from the *recomputed* prior event (not the stored value), and checks that the recomputed hash equals the stored `event_hash`. It also checks that the first event has `previous_event_hash` null and that every later event’s stored `previous_event_hash` matches the prior event’s recomputed hash. The response is `verified` (boolean) and a list of `failures` (index, event_id, reason).

2. **Bulk (heartbeat).** The integrity verifier module loads all events grouped by `chain_id`, runs the same recomputation logic for every chain, and returns a global status (PASS/FAIL) and optional mismatch details. On PASS, it can compute an “anchored chain commitment” (most recently updated chain, head hash, event count) for inclusion in heartbeat emails or external anchoring.

3. **Portable pack.** `GET /chains/{chain_id}/evidence.zip` returns a ZIP containing event data, a receipt (chronological decision summary), and a verification result. Anyone with the canonical hash function can re-run verification on the exported data without the database.

---

## What this is NOT

- **Not a model.** Attest does not run or train ML models. It records and chains attestations about decisions (e.g. human approve/override, model version, stimulus/output hashes). The payload is hashed and stored; the system does not interpret model outputs.
- **Not reconciliation software.** It does not match transactions, balance books, or resolve discrepancies between systems. It provides a single, append-only, hash-chained log of decision events for provenance and audit.
