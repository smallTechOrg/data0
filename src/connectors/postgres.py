"""External PostgreSQL dataset connector (C36, BETA, flag-gated).

`connection_check()` / `discover_tables()` / `discover_relationships()` /
`pull_table()` all run over `psycopg2`, each wrapped in a hard wall-clock
timeout (via a worker thread's `.result(timeout=...)`, not `signal.alarm` —
this needs to work on Windows dev too) because `psycopg2`'s own
`connect_timeout` does not cover every stall (e.g. a firewall silently
dropping packets after the TCP handshake).

The raw URI (with the password) is read ONLY here, inside `_get_connection()`,
sourced from `self._uri.raw()`. Every error surfaced to the caller is
sanitized through `self._uri.display()` (+ password string-replacement on the
driver's own exception text) so credentials never leak into a log line, an API
response, or a raised exception message.

This is a one-time snapshot-pull connector — `pull_table` is the only "query"
surface, and it is invoked exactly once per requested table at
`POST /connections/import` / `POST /connections/{id}/resync` time. There is no
live query path and no persistent connection the agent talks to mid-run.
"""
from __future__ import annotations

import concurrent.futures
from urllib.parse import urlsplit

import pandas as pd

from connectors.base import DatasetConnectionError, DatasetConnector

# Hard wall-clock cap around each connect/introspect/pull call. Module-level so
# tests can monkeypatch it down to keep the timeout-path test fast.
_CONNECT_TIMEOUT_SECONDS = 8

# Row cap for a single `pull_table` snapshot — matches the spirit of this app's
# 100 MB file-size target (spec/roadmap.md -> Key Constraints) without a
# byte-accurate SQL-side size probe. See
# spec/capabilities/external-db-connectors.md -> "Bounded snapshot pull".
_MAX_PULL_ROWS = 500_000

_FK_QUERY = (
    "SELECT tc.table_name, kcu.column_name, ccu.table_name, ccu.column_name "
    "FROM information_schema.table_constraints tc "
    "JOIN information_schema.key_column_usage kcu "
    "  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
    "JOIN information_schema.constraint_column_usage ccu "
    "  ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema "
    "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'"
)


class PostgresConnector(DatasetConnector):
    """Serves an external `postgresql` database; introspects live via `psycopg2`."""

    def __init__(self, server: dict) -> None:
        super().__init__(server)
        self._conn = None

    # --- connection lifecycle ----------------------------------------------

    def _get_connection(self):
        """Open (and cache) the one connection this connector instance uses.

        Reused across `connection_check` -> `discover_tables` ->
        `discover_relationships` -> `pull_table` within a single request
        (`POST /connections/check` / `POST /connections/import`), per the
        capability spec's "SAME connection already opened" contract.
        """
        if self._conn is None:
            import psycopg2  # deferred: keep the driver optional until used

            try:
                self._conn = psycopg2.connect(self._uri.raw(), connect_timeout=5)
            except Exception as exc:  # noqa: BLE001 — sanitized before it leaves this method
                raise DatasetConnectionError(
                    self._sanitize(f"Could not connect to {self._uri.display()}: {exc}")
                )
        return self._conn

    def connect(self):
        return self._get_connection()

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001 — best-effort close
                pass
            self._conn = None

    # --- DatasetConnector interface -----------------------------------------

    def connection_check(self) -> None:
        """Connect + `SELECT 1` within a hard timeout; raise a sanitized error on failure."""

        def probe() -> None:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()

        self._with_timeout(probe, "connect to")

    def discover_tables(self) -> list[dict]:
        """Introspect `information_schema` for base tables in the `public` schema."""

        def introspect() -> list[dict]:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"
            )
            names = [r[0] for r in cur.fetchall()]
            tables: list[dict] = []
            for name in names:
                cur.execute(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                    (name,),
                )
                cols = cur.fetchall()
                tables.append(
                    {
                        "table_name": name,
                        "column_names": [c[0] for c in cols],
                        "schema": [
                            {"name": c[0], "dtype": c[1], "nullable": c[2] == "YES"}
                            for c in cols
                        ],
                        "row_count": None,
                    }
                )
            return tables

        return self._with_timeout(introspect, "introspect")

    def discover_relationships(self) -> list[dict]:
        """Foreign keys from `information_schema` (nice-to-have — never blocks import)."""

        def introspect() -> list[dict]:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(_FK_QUERY)
            return [
                {"from_table": r[0], "from_column": r[1], "to_table": r[2], "to_column": r[3]}
                for r in cur.fetchall()
            ]

        try:
            return self._with_timeout(introspect, "introspect relationships")
        except DatasetConnectionError:
            return []
        except Exception:  # noqa: BLE001 — relationships are best-effort only
            return []

    def pull_table(self, table_name: str, filter: str | None = None) -> pd.DataFrame:
        """`SELECT * FROM "<table>" [WHERE <filter>] LIMIT <row cap>` on the open connection."""

        def fetch() -> pd.DataFrame:
            conn = self._get_connection()
            safe_table = table_name.replace('"', '""')
            query = f'SELECT * FROM "{safe_table}"'
            if filter:
                query += f" WHERE {filter}"
            query += f" LIMIT {_MAX_PULL_ROWS}"
            return pd.read_sql(query, conn)

        return self._with_timeout(fetch, f"pull table {table_name!r} from")

    # --- helpers -------------------------------------------------------------

    def _with_timeout(self, fn, verb: str):
        """Run `fn` on a worker thread with a hard wall-clock timeout.

        A thread-based timeout (not `signal.alarm`, which is POSIX-only) so
        this works in the Windows dev environment too.
        """
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(fn).result(timeout=_CONNECT_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            raise DatasetConnectionError(
                f"Timed out trying to {verb} {self._uri.display()}."
            )
        except DatasetConnectionError:
            raise
        except Exception as exc:  # noqa: BLE001 — sanitized before it leaves this method
            raise DatasetConnectionError(
                self._sanitize(f"Could not {verb} {self._uri.display()}: {exc}")
            )

    def _sanitize(self, msg: str) -> str:
        """Scrub the raw URI + password out of a driver error message."""
        raw = self._uri.raw()
        if raw:
            msg = msg.replace(raw, self._uri.display())
        password = urlsplit(raw).password if raw else None
        if password:
            msg = msg.replace(password, "***")
        return msg
