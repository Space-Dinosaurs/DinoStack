"""Tier 2 isolator auth-preservation tests.

Verifies:
- Auth artifacts (keychain dir on macOS, .credentials.json on all platforms)
  are exposed to the fake HOME via symlink.
- home_config seeded files take precedence over symlinks.
- __exit__ cleanup removes symlinks without following them: real auth
  artifacts remain intact.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from evals.runner.isolator import Tier2HomeRedirect


@pytest.fixture
def fake_real_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fabricate a 'real' home dir with credentials + keychain so we can
    safely test the symlink path without touching the developer's actual home.
    """
    real = tmp_path / "real-home"
    (real / ".claude").mkdir(parents=True)
    (real / ".claude" / ".credentials.json").write_text('{"token":"REAL"}')
    (real / ".claude" / ".credentials.json.bak").write_text('{"token":"BAK"}')
    if sys.platform == "darwin":
        (real / "Library" / "Keychains").mkdir(parents=True)
        (real / "Library" / "Keychains" / "login.keychain-db").write_bytes(b"REALKC")

    # Patch expanduser so isolator resolves to our fake real home.
    real_str = str(real)

    def fake_expand(p: str) -> str:
        if p == "~" or p.startswith("~/"):
            return real_str + p[1:]
        return p

    monkeypatch.setattr(os.path, "expanduser", fake_expand)
    return real


def test_credentials_symlinked_into_fake_home(fake_real_home: Path) -> None:
    iso = Tier2HomeRedirect(home_config={})
    with iso as (_wt, fake_home):
        cred = fake_home / ".claude" / ".credentials.json"
        assert cred.is_symlink(), "expected credentials.json to be a symlink"
        assert cred.read_text() == '{"token":"REAL"}'
        bak = fake_home / ".claude" / ".credentials.json.bak"
        assert bak.is_symlink()


def test_home_config_takes_precedence_over_symlink(fake_real_home: Path) -> None:
    iso = Tier2HomeRedirect(home_config={".credentials.json": '{"token":"SEEDED"}'})
    with iso as (_wt, fake_home):
        cred = fake_home / ".claude" / ".credentials.json"
        assert not cred.is_symlink(), "home_config should win over symlink"
        assert cred.read_text() == '{"token":"SEEDED"}'


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS keychain only")
def test_keychain_dir_symlinked_on_macos(fake_real_home: Path) -> None:
    iso = Tier2HomeRedirect(home_config={})
    with iso as (_wt, fake_home):
        kc = fake_home / "Library" / "Keychains"
        assert kc.is_symlink()
        assert (kc / "login.keychain-db").read_bytes() == b"REALKC"


def test_cleanup_does_not_follow_symlinks(fake_real_home: Path) -> None:
    iso = Tier2HomeRedirect(home_config={})
    with iso as (_wt, _fake_home):
        pass
    # Real auth artifacts must still exist.
    assert (fake_real_home / ".claude" / ".credentials.json").read_text() == '{"token":"REAL"}'
    assert (fake_real_home / ".claude" / ".credentials.json.bak").read_text() == '{"token":"BAK"}'
    if sys.platform == "darwin":
        assert (fake_real_home / "Library" / "Keychains" / "login.keychain-db").read_bytes() == b"REALKC"
