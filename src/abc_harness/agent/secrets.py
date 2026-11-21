"""API keys from `.env` (AGENTS.md hard rule 5).

Keys are read into a `Secrets` object and handed to the one client that needs
each of them. They are never copied into `os.environ`, so no subprocess can
inherit them, and `Secrets.redact` scrubs their values from anything the
harness writes. Only entries named like a credential are scrubbed: other
`.env` lines are settings, and a value such as "deepseek" must not blank out
model names.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_ENV_FILE = Path(".env")
REDACTED = "[REDACTED]"
# Values shorter than this are not treated as secrets when redacting, so a
# placeholder such as "x" cannot blank out every "x" in a trace.
MIN_SECRET_LENGTH = 8
# Entry names treated as credentials, e.g. DEEPSEEK_API_KEY, GITHUB_TOKEN, DB_PASSWORD.
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH", re.IGNORECASE)


class MissingSecret(KeyError):
    """Raised when a required key is in neither `.env` nor the environment."""


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines. Blank lines and lines starting with # are ignored."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key.isidentifier():
            raise ValueError(f"{path}:{number}: expected KEY=VALUE")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


class Secrets:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = {k: v for k, v in values.items() if v}

    @classmethod
    def load(cls, path: Path = DEFAULT_ENV_FILE, names: tuple[str, ...] = ("ANTHROPIC_API_KEY",)) -> Secrets:
        """Read `.env`, falling back to the process environment for the given names."""
        values = parse_env_file(path)
        for name in names:
            if name not in values and os.environ.get(name):
                values[name] = os.environ[name]
        return cls(values)

    def get(self, name: str) -> str:
        try:
            return self._values[name]
        except KeyError:
            raise MissingSecret(f"{name} is not set; add it to .env (see .env.example)") from None

    def has(self, name: str) -> bool:
        return name in self._values

    def redact(self, text: str) -> str:
        for name, value in self._values.items():
            if SECRET_NAME.search(name) and len(value) >= MIN_SECRET_LENGTH:
                text = text.replace(value, REDACTED)
        return text

    def __repr__(self) -> str:
        return f"Secrets({sorted(self._values)})"
