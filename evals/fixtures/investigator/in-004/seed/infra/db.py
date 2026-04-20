"""DB shim. Stand-in for the real psycopg connection pool."""


def query(sql, params):
    # Live query path elided.
    raise NotImplementedError


def upsert_daily(day, counts):
    raise NotImplementedError
