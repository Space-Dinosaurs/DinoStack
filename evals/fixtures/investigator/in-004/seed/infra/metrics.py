"""Event-store reads.

fetch_events_in_window uses a half-open interval [start, end) against the
events table's `ts` column. The events table is written to by the ingest
pipeline; late-arriving events (from mobile clients with clock skew) are
stamped with the server's receipt timestamp via a trigger the ingest team
owns.
"""

from infra.db import query


def fetch_events_in_window(start, end):
    sql = "SELECT id, kind, ts FROM events WHERE ts >= %s AND ts < %s"
    return query(sql, (start, end))
