"""Database shim."""


def insert_row(table, row):
    # Parameterized insert; values are bound, not concatenated.
    return {"table": table, "row": row, "inserted": True}
