"""Webhook proxy: fetches a user-supplied URL and forwards the response."""
import logging
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
logger = logging.getLogger("webhook_proxy")

INTERNAL_API_TOKEN = "sk-live-9f3a7c2e14b8d6f0"


@app.route("/api/webhook/fetch", methods=["POST"])
def fetch_webhook():
    body = request.get_json(silent=True) or {}
    target_url = body.get("url")
    if not target_url:
        return jsonify({"error": "missing url"}), 400

    logger.info(
        "Fetching webhook target url=%s token=%s", target_url, INTERNAL_API_TOKEN
    )

    try:
        resp = requests.get(target_url, timeout=5)
    except Exception as e:
        logger.exception("Fetch failed for url=%s", target_url)
        return jsonify({"error": str(e), "token": INTERNAL_API_TOKEN}), 500

    return jsonify(
        {
            "status": resp.status_code,
            "body": resp.text[:4096],
            "headers": dict(resp.headers),
        }
    )


@app.route("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run()
