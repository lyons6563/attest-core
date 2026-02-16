#!/usr/bin/env python3
"""
Check that the Decision Engine database is ready:
- All required tables exist (custody_chains, custody_events, ingestion_events)
- Audit-hardening columns exist on custody_events

Exit 0 and print "READY" if all checks pass; exit 1 and print what's missing otherwise.
"""
import sys

REQUIRED_TABLES = ("custody_chains", "custody_events", "ingestion_events")
REQUIRED_AUDIT_COLUMNS = (
    "actor_id",
    "session_id",
    "source_system",
    "system_suggestion",
    "options_presented",
    "human_selection",
    "decision_timestamp",
)


def main():
    try:
        import psycopg2
    except ImportError:
        print("ERROR - psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    conn_params = {
        "host": "127.0.0.1",
        "port": 55432,
        "dbname": "decision_engine",
        "user": "postgres",
        "password": "postgres",
    }

    try:
        conn = psycopg2.connect(**conn_params)
    except Exception as e:
        print(f"ERROR - Could not connect to Postgres: {e}", file=sys.stderr)
        print("  Check that Postgres is running on 127.0.0.1:55432 (e.g. run .\\scripts\\ensure-postgres.ps1)", file=sys.stderr)
        sys.exit(1)

    missing = []
    cur = conn.cursor()

    # 1. Check required tables exist
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = ANY(%s);
        """,
        (list(REQUIRED_TABLES),),
    )
    found_tables = {row[0] for row in cur.fetchall()}
    for t in REQUIRED_TABLES:
        if t not in found_tables:
            missing.append(f"Table missing: {t}")

    # 2. Check audit-hardening columns on custody_events (only if table exists)
    if "custody_events" in found_tables:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'custody_events'
              AND column_name = ANY(%s);
            """,
            (list(REQUIRED_AUDIT_COLUMNS),),
        )
        found_columns = {row[0] for row in cur.fetchall()}
        for c in REQUIRED_AUDIT_COLUMNS:
            if c not in found_columns:
                missing.append(f"Column missing on custody_events: {c}")

    cur.close()
    conn.close()

    if missing:
        print("ERROR - Decision engine not ready. The following are missing:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        print("  Run base schema and audit hardening: .\\scripts\\ensure-postgres.ps1", file=sys.stderr)
        sys.exit(1)

    print("READY - decision engine initialized")
    sys.exit(0)


if __name__ == "__main__":
    main()
