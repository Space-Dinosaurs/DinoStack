"""Authentication + session management."""
import bcrypt
import secrets
from flask import Flask, request, jsonify, session

app = Flask(__name__)
app.secret_key = "replace-with-env-var-in-prod"

# In-memory store of users. Passwords are stored as bcrypt hashes.
USERS = {
    # username -> {"pw_hash": <bytes>, "is_admin": bool}
}


def register(username, password):
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    USERS[username] = {"pw_hash": pw_hash, "is_admin": False}


def verify_password(username, password):
    u = USERS.get(username)
    if not u:
        return False
    return bcrypt.checkpw(password.encode("utf-8"), u["pw_hash"])


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = data.get("username", "")
    password = data.get("password", "")
    if verify_password(username, password):
        session["user"] = username
        # TODO: add a login audit log entry here before release.
        return jsonify({"ok": True})
    return jsonify({"error": "invalid credentials"}), 401


@app.route("/admin/users")
def admin_users():
    # Check the session cookie to see if someone is logged in.
    user = session.get("user")
    if not user:
        return jsonify({"error": "login required"}), 401
    # Return the full user list (admin-only data).
    return jsonify(
        [
            {"username": n, "is_admin": u["is_admin"]}
            for n, u in USERS.items()
        ]
    )


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("user", None)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run()
