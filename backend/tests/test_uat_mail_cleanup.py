"""`uat_env.py --reset` and `--destroy` delete captured Customer Account mail.

A capture file holds a verification or password-reset link, and that link is a live
credential for whatever account it was issued against. Two things follow, and both are
tested here rather than left to the reviewer:

* a reset must actually remove them, so yesterday's links are not readable during today's
  pass and a case cannot pass against the wrong message;
* the deletion must be confined to the UAT directory, because a helper that removes
  `*.json` from wherever it is pointed is one misconfiguration away from deleting
  something else.

The safety check compares resolved parents rather than trusting the constant, so
re-pointing `UAT_MAIL_DIR` at a convenient directory is refused instead of obeyed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UAT_ENV_PATH = REPO_ROOT / "scripts" / "uat_env.py"


def load_uat_env():
    """Import `scripts/uat_env.py` by path. It is a script, not an installed module."""
    spec = importlib.util.spec_from_file_location("uat_env_under_test", UAT_ENV_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def uat_env(tmp_path, monkeypatch):
    """The script, with its UAT directory moved into a temporary one.

    Nothing in this file may touch the real `data/uat/`. A test that deletes captured mail
    has to prove it deletes the right captured mail.
    """
    module = load_uat_env()
    uat_dir = tmp_path / "uat"
    uat_dir.mkdir()
    monkeypatch.setattr(module, "UAT_DIR", uat_dir)
    monkeypatch.setattr(module, "UAT_MAIL_DIR", uat_dir / "account_mail")
    return module


def captured(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text('{"template_key": "account.verify_email"}', encoding="utf-8")
    return path


def test_a_missing_directory_is_not_an_error(uat_env):
    assert not uat_env.UAT_MAIL_DIR.exists()
    assert uat_env.clear_captured_mail() == 0


def test_every_captured_message_is_removed_and_counted(uat_env):
    for index in range(3):
        captured(uat_env.UAT_MAIL_DIR, f"26092{index}T101010000000-verify_email-a@example.com.json")

    assert uat_env.clear_captured_mail() == 3
    assert not uat_env.UAT_MAIL_DIR.exists()


def test_an_emptied_directory_is_removed_but_a_used_one_is_kept(uat_env):
    captured(uat_env.UAT_MAIL_DIR, "260921T101010000000-verify_email-a@example.com.json")
    (uat_env.UAT_MAIL_DIR / "notes.txt").write_text("left by hand", encoding="utf-8")

    assert uat_env.clear_captured_mail() == 1
    # The directory stays, because something that is not a capture is still in it. A
    # cleanup helper that removes a file it did not write is a cleanup helper nobody
    # should run.
    assert uat_env.UAT_MAIL_DIR.exists()
    assert (uat_env.UAT_MAIL_DIR / "notes.txt").exists()


def test_only_json_captures_are_deleted(uat_env):
    captured(uat_env.UAT_MAIL_DIR, "260921T101010000000-verify_email-a@example.com.json")
    keep = uat_env.UAT_MAIL_DIR / "keep.md"
    keep.write_text("not a capture", encoding="utf-8")

    assert uat_env.clear_captured_mail() == 1
    assert keep.exists()


def test_a_directory_outside_the_uat_directory_is_refused(uat_env, tmp_path, monkeypatch):
    elsewhere = tmp_path / "somewhere_else" / "account_mail"
    victim = captured(elsewhere, "260921T101010000000-verify_email-a@example.com.json")
    monkeypatch.setattr(uat_env, "UAT_MAIL_DIR", elsewhere)

    with pytest.raises(uat_env.SafetyError):
        uat_env.clear_captured_mail()

    assert victim.exists(), "the refusal must happen before anything is deleted"


def test_the_development_capture_directory_is_not_the_uat_one():
    """The two must not be the same directory, in the shipped constants.

    `data/account_mail` is the development default and is not managed by the UAT reset.
    If they were ever pointed at each other, a UAT reset would silently delete a
    developer's captured mail.
    """
    module = load_uat_env()
    development = REPO_ROOT / "data" / "account_mail"
    assert module.UAT_MAIL_DIR.resolve() != development.resolve()
    assert module.UAT_MAIL_DIR.parent.resolve() == module.UAT_DIR.resolve()
