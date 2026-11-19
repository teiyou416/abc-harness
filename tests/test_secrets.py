from __future__ import annotations

import os

import pytest

from abc_harness import cli
from abc_harness.secrets import MissingSecret, Secrets, parse_env_file


def test_env_file_parsing(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\n\nANTHROPIC_API_KEY="sk-quoted-value"\nexport OTHER_KEY=plain-value\nEMPTY=\n')
    assert parse_env_file(env) == {"ANTHROPIC_API_KEY": "sk-quoted-value", "OTHER_KEY": "plain-value", "EMPTY": ""}


def test_malformed_line_is_an_error(tmp_path):
    env = tmp_path / ".env"
    env.write_text("not a key value line\n")
    with pytest.raises(ValueError, match=":1:"):
        parse_env_file(env)


def test_loading_never_touches_the_process_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-from-dotenv-file\n")
    secrets = Secrets.load(env)
    assert secrets.get("ANTHROPIC_API_KEY") == "sk-from-dotenv-file"
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert "sk-from" not in repr(secrets)


def test_missing_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingSecret):
        Secrets.load(tmp_path / "absent.env").get("ANTHROPIC_API_KEY")


def test_redact_skips_short_values():
    secrets = Secrets({"A": "sk-long-secret-value", "B": "x"})
    assert secrets.redact("key sk-long-secret-value and x") == "key [REDACTED] and x"


def test_ask_without_a_key_exits_before_any_task(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = cli.main(["ask", "anything", "--env-file", str(tmp_path / "none.env"), "--runs-dir", str(tmp_path / "r")])
    assert code == 2
    assert ".env" in capsys.readouterr().err
    assert not (tmp_path / "r").exists()
