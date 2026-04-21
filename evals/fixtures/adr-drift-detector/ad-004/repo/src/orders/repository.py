from db.connection import open_connection


def find_order(order_id: str):
    with open_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, total FROM orders WHERE id = %s", (order_id,))
            return cur.fetchone()
