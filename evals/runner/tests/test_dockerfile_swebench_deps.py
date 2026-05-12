"""
Regression tests for Dockerfile.swebench.

test_dockerfile_includes_urllib3_etc:
  Finding: smoke v9 failed with `ModuleNotFoundError: No module named 'urllib3'`
  because the image only had pytest + pytest-timeout.
  Fix: added urllib3 chardet certifi idna to the RUN pip install layer.

test_dockerfile_uses_python_3_9:
  Finding: smoke v10 hit `AttributeError: module 'collections' has no attribute
  'MutableMapping'` in requests-3362 test conftest. The task is from 2016 and
  uses collections.MutableMapping which was removed in Python 3.10.
  Fix: base image changed from python:3.11-slim to python:3.9-slim (v1.3.0).

test_dockerfile_has_required_labels:
  Verifies org.opencontainers labels are present.

test_dockerfile_has_pip_install:
  Verifies the RUN pip install layer is present.
"""

import pathlib

DOCKERFILE = pathlib.Path(__file__).parent.parent / "Dockerfile.swebench"

REQUIRED_PACKAGES = ["urllib3", "chardet", "certifi", "idna"]


def test_dockerfile_includes_urllib3_etc():
    """Dockerfile.swebench must pip-install the requests transitive dep stack."""
    content = DOCKERFILE.read_text()
    missing = [pkg for pkg in REQUIRED_PACKAGES if pkg not in content]
    assert not missing, (
        f"Dockerfile.swebench is missing these packages: {missing}. "
        "Add them to the RUN pip install layer so score-phase pytest can "
        "import them without network access."
    )


def test_dockerfile_uses_python_3_9():
    """
    Regression: smoke v10 hit collections.MutableMapping AttributeError in
    requests-3362 conftest because python:3.11 removed the attribute in 3.10.
    The FROM line must use python:3.9 (or python:3.9-slim / python:3.9-alpine)
    for compatibility with legacy SWE-bench-lite tasks.
    """
    content = DOCKERFILE.read_text()
    from_lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip().upper().startswith("FROM")
    ]
    assert from_lines, "Dockerfile.swebench has no FROM instruction."
    first_from = from_lines[0]
    assert "3.9" in first_from, (
        f"Dockerfile.swebench FROM line does not use Python 3.9: {first_from!r}. "
        "Legacy SWE-bench tasks (e.g. requests-3362) require Python 3.9 because "
        "collections.MutableMapping was removed in Python 3.10."
    )


def test_dockerfile_has_required_labels():
    """Dockerfile.swebench must declare OCI image labels."""
    content = DOCKERFILE.read_text()
    assert "org.opencontainers.image.title" in content
    assert "org.opencontainers.image.version" in content


def test_dockerfile_has_pip_install():
    """Dockerfile.swebench must have a RUN pip install layer."""
    content = DOCKERFILE.read_text()
    assert "pip install" in content
