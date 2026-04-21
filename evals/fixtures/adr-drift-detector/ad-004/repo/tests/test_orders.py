"""Test fixtures use sqlite3; allowed per ADR-0001."""
import sqlite3

import pytest


@pytest.fixture
def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE orders (id TEXT PRIMARY KEY, total REAL)")
    conn.execute("INSERT INTO orders VALUES ('o1', 42.5)")
    conn.commit()
    yield conn
    conn.close()


def test_memory_db_roundtrip(memory_db):
    cur = memory_db.execute("SELECT id, total FROM orders WHERE id = 'o1'")
    row = cur.fetchone()
    assert row == ("o1", 42.5)
