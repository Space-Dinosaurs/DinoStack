# src/util/checksum.py (relevant excerpt)

import hashlib


def compute_checksum(path: str) -> str:
    """Return a SHA-256 hex digest of the file at `path`.

    Reads the whole file in one call; delegates to hashlib's native
    implementation. No Python-level loop over bytes.
    """
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha256(data).hexdigest()
