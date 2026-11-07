"""Record of downloaded files, so unchanged files are not downloaded again."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class Manifest:
    def __init__(self, file: Path) -> None:
        self.file = file
        self.entries: dict[str, dict[str, Any]] = json.loads(file.read_text()) if file.is_file() else {}

    def is_current(self, key: str, url: str, local_path: Path) -> bool:
        """True if this exact revision was downloaded and the file still exists."""
        entry = self.entries.get(key)
        return entry is not None and entry["url"] == url and local_path.is_file()

    def etag(self, key: str) -> str | None:
        entry = self.entries.get(key)
        return entry.get("etag") if entry else None

    def __contains__(self, key: str) -> bool:
        return key in self.entries

    def record(self, key: str, url: str, etag: str | None, path: str) -> None:
        self.entries[key] = {"url": url, "etag": etag, "path": path, "time": int(time.time())}

    def save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.entries, indent=1, ensure_ascii=False))
        tmp.replace(self.file)
