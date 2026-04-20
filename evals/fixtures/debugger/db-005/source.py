"""HTTP client with configurable timeout.

The client reads its timeout from the app config and passes it through
to the underlying transport as a millisecond value.
"""
import yaml


def load_client_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def make_client(config: dict):
    timeout_ms = int(config["http"]["timeout_ms"])
    return HttpClient(timeout_ms=timeout_ms)


class HttpClient:
    def __init__(self, timeout_ms: int):
        # Transport expects milliseconds; store as-is.
        self.timeout_ms = timeout_ms

    def get(self, url: str):
        # Pseudocode: transport.send(url, timeout_ms=self.timeout_ms)
        ...
