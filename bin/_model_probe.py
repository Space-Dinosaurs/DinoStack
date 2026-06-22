"""
Purpose: Shared HTTP helper that probes an OpenAI-compatible /v1/models
         endpoint and returns the list of model-id strings. Extracted from
         bin/agentic-models so that bin/agentic-team discover can reuse the
         same probe logic without going through a Pi/omp-gated path.

Public API:
    probe_models(url, key=None, timeout=10) -> list[str]
        Returns model-id strings on success; returns [] on any network/parse
        failure (does NOT sys.exit - callers decide how to handle absence).

Upstream deps: Python 3.11 stdlib (json, urllib).

Downstream consumers: bin/agentic-models (can import this instead of its
                      inline copy), bin/agentic-team (discover subcommand).

Failure modes: Any urllib or json error is caught and returns [] with an
               optional warning to stderr. Callers must treat [] as
               "models unknown" rather than "no models available".

Performance: One HTTP GET per call. ~200 ms on a warm probe. Caller sets
             timeout; default is 10 s.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def probe_models(
    url: str,
    key: str | None = None,
    timeout: int = 10,
) -> list[str]:
    """GET <url>/v1/models and return model-id strings.

    Parameters
    ----------
    url:
        OpenAI-compatible base URL WITHOUT a trailing /v1 suffix.
        A single trailing '/' is stripped automatically.
    key:
        Optional Bearer token. Omit or pass None for unauthenticated probes.
    timeout:
        HTTP timeout in seconds. Default: 10.

    Returns
    -------
    List of model-id strings, or [] on any failure (network, auth, parse).
    Errors are printed to stderr as a single warning line; callers should
    treat [] as "models unknown".
    """
    if not url:
        return []
    base = (url[:-1] if url.endswith("/") else url) + "/v1/models"
    req = urllib.request.Request(base, method="GET")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001 - broad catch intentional for probe
        print(f"agentic-team discover: model probe failed for {url!r}: {exc}", file=sys.stderr)
        return []
    data = payload.get("data", [])
    return [m["id"] for m in data if "id" in m]
