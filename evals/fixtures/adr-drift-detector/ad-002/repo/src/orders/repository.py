from db.connection import open_connection


def find_order(order_id: str):
    conn = open_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, total FROM orders WHERE id = ?", (order_id,))
    row = cur.fetchone()
    conn.close()
    return row
