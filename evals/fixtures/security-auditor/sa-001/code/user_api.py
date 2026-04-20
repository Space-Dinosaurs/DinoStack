"""User lookup API endpoint."""
import sqlite3
from flask import Flask, request, jsonify

app = Flask(__name__)
DB_PATH = "/var/app/users.db"


def get_db():
    return sqlite3.connect(DB_PATH)


@app.route("/api/users/search")
def search_users():
    q = request.args.get("q", "")
    conn = get_db()
    cur = conn.cursor()
    # Build a LIKE query against the username column.
    sql = "SELECT id, username, email FROM users WHERE username LIKE '%" + q + "%'"
    cur.execute(sql)
    rows = cur.fetchall()
    conn.close()
    results = [{"id": r[0], "username": r[1], "email": r[2]} for r in rows]
    return jsonify(results)


@app.route("/api/users/<int:user_id>")
def get_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, email FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify({"id": row[0], "username": row[1], "email": row[2]})


if __name__ == "__main__":
    app.run()
