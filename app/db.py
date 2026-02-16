"""
Single source of truth for database connection.
App ALWAYS connects to the Docker Postgres container at 127.0.0.1:55432 (TCP only).
No env override, no fallback — avoids connection ambiguity with other Postgres instances.

Schema validation disposes any existing engine and creates a fresh one so it always
checks the same DB that psql/ensure-postgres.ps1 use (no stale metadata).
"""
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Explicit TCP: 127.0.0.1:55432 (host port maps to 5432 in container). No Unix socket.
DATABASE_URL = "postgresql+psycopg2://postgres:postgres@127.0.0.1:55432/decision_engine?application_name=decision_engine_app"

# Connection info for startup logging and schema validation errors (no secrets)
DB_HOST = "127.0.0.1"
DB_PORT = 55432
DB_NAME = "decision_engine"
DB_CONTAINER_NAME = "decision-engine-db"


def get_db_config() -> dict:
    """Return host, port, database for logging. No secrets."""
    return {"host": DB_HOST, "port": DB_PORT, "database": DB_NAME}


def get_psycopg2_conn():
    """Return a psycopg2 connection to the Docker Postgres container (127.0.0.1:55432)."""
    import psycopg2
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user="postgres",
        password="postgres",
    )


_engine = None
_SessionLocal = None


def get_engine():
    """Create and return the SQLAlchemy engine on first use (lazy). Avoids import-time engine creation."""
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, future=True)
    return _engine


def get_db():
    """Yield a DB session. Session factory is created lazily and bound to the lazy engine."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Expected audit-hardening columns on custody_events (fail fast if missing)
REQUIRED_TABLES = ("custody_chains", "custody_events", "ingestion_events")
REQUIRED_CUSTODY_EVENTS_COLUMNS = (
    "actor_id",
    "session_id",
    "source_system",
    "system_suggestion",
    "options_presented",
    "human_selection",
    "decision_timestamp",
)


def _check_schema() -> list[str]:
    """Return list of missing tables/columns. Empty if schema is valid."""
    missing = []
    # Tables: literal IN list (constants only). Columns: select all for custody_events, check in Python (avoids ANY/param binding under psycopg2).
    tables_in = ", ".join(repr(t) for t in REQUIRED_TABLES)
    with get_engine().connect() as conn:
        r = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name IN ({})".format(tables_in)
            )
        )
        found_tables = {row[0] for row in r}
        for t in REQUIRED_TABLES:
            if t not in found_tables:
                missing.append(f"Table missing: {t}")

        if "custody_events" in found_tables:
            r = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'custody_events'"
                )
            )
            found_cols = {row[0] for row in r}
            for c in REQUIRED_CUSTODY_EVENTS_COLUMNS:
                if c not in found_cols:
                    missing.append(f"Column missing on custody_events: {c}")
    return missing


def validate_schema() -> None:
    """
    Validate schema once against a fresh connection. No retries — fail fast so
    results match what psql shows (avoids stale engine/metadata on Windows+Docker).
    """
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
        _engine = None
        _SessionLocal = None

    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT current_database(), inet_server_addr(), inet_server_port()")
        ).fetchone()
        print(
            "[DB] current_database={!r} inet_server_addr={!r} inet_server_port={!r}".format(
                row[0], row[1], row[2]
            ),
            file=sys.stderr,
        )
    missing = _check_schema()
    if missing:
        raise RuntimeError(
            "Schema validation failed. "
            "database={!r} host={!r} port={} container={!r}. "
            "Missing: {}. "
            "Run: .\\scripts\\ensure-postgres.ps1".format(
                DB_NAME, DB_HOST, DB_PORT, DB_CONTAINER_NAME, "; ".join(missing)
            )
        )
