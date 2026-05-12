"""
Regression test: Dockerfile.swebench must include urllib3 and sibling
requests-stack packages so that SWE-bench-lite corpus tasks (e.g.
requests-3362) do not fail with ModuleNotFoundError at score-phase pytest time.

Finding: smoke v9 failed with `ModuleNotFoundError: No module named 'urllib3'`
because the image only had pytest + pytest-timeout.
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
