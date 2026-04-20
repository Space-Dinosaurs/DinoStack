"""Minimal health + version endpoints. No user input, no external I/O."""
from flask import Flask, jsonify

app = Flask(__name__)

APP_VERSION = "1.4.2"
BUILD_SHA = "9a3f1c0"


@app.route("/health")
def health():
    return jsonify({"ok": True})


@app.route("/version")
def version():
    return jsonify({"version": APP_VERSION, "build": BUILD_SHA})


@app.route("/ping")
def ping():
    return "pong"


if __name__ == "__main__":
    app.run()
