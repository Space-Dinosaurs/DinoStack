"""Database connection module.

NOTE: uses sqlite3 in production. The ADR requires PostgreSQL but the
migration has not been completed.
"""
import sqlite3


def open_connection(path: str = "/var/data/app.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn
