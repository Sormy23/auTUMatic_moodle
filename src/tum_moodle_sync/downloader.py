"""Download one file atomically (via a .part file)."""

from __future__ import annotations

from pathlib import Path

from tum_moodle_sync.session import MOODLE_HOST, MoodleSession

CHUNK_SIZE = 1 << 16


class SessionLostError(Exception):
    """Moodle sent us to the login page instead of the file."""


def download(session: MoodleSession, url: str, dest: Path) -> tuple[Path, str | None]:
    """Download url to '<dest>.part' and return (part file, ETag).

    The caller decides whether to move the part file into place, so an
    interrupted download never leaves a broken file behind.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with session.stream(url) as response:
            response.raise_for_status()
            if response.url.host != MOODLE_HOST or "/login/" in response.url.path:
                raise SessionLostError(f"redirected to {response.url}")
            with part.open("wb") as f:
                for chunk in response.iter_bytes(CHUNK_SIZE):
                    f.write(chunk)
            return part, response.headers.get("etag")
    except BaseException:
        part.unlink(missing_ok=True)
        raise
