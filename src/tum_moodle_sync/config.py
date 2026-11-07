"""Configuration from config.env and environment variables (environment wins)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ENV_FILE = Path("config.env")


@dataclass(frozen=True)
class Config:
    user: str | None
    password: str | None
    dest: Path
    state_dir: Path
    interval_minutes: int

    @classmethod
    def load(
        cls,
        env_file: Path = DEFAULT_ENV_FILE,
        *,
        dest: Path | None = None,
        state_dir: Path | None = None,
        interval_minutes: int | None = None,
    ) -> Config:
        """Build the config. Explicit arguments (CLI flags) override everything."""
        values = {**read_env_file(env_file), **os.environ}
        return cls(
            user=values.get("TUM_USER") or None,
            password=values.get("TUM_PASSWORD") or None,
            dest=(dest or Path(values.get("MOODLE_DIR") or "moodle")).expanduser(),
            state_dir=(state_dir or Path(values.get("MOODLE_STATE_DIR") or ".state")).expanduser(),
            interval_minutes=(
                interval_minutes if interval_minutes is not None
                else int(values.get("SYNC_INTERVAL") or 0)
            ),
        )


def read_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines. No variable expansion, so '$' in passwords is kept."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values
