"""HTTP session for www.moodle.tum.de: cookies, throttling and the AJAX endpoint."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://www.moodle.tum.de"
MOODLE_HOST = "www.moodle.tum.de"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) tum-moodle-sync"

log = logging.getLogger(__name__)


class MoodleError(Exception):
    """Moodle returned an error for an AJAX call."""


class MoodleSession:
    def __init__(self, cookie_file: Path, delay: float = 0.3) -> None:
        self.cookie_file = cookie_file
        self.delay = delay  # seconds between requests, to be polite to the server
        self.sesskey: str | None = None
        self.http = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "de,en;q=0.8"},
            timeout=httpx.Timeout(60, connect=20),
            follow_redirects=True,
        )
        self._load_cookies()

    # -- requests -----------------------------------------------------------

    def get(self, path_or_url: str, **kwargs: Any) -> httpx.Response:
        time.sleep(self.delay)
        return self.http.get(self._url(path_or_url), **kwargs)

    def stream(self, url: str):
        time.sleep(self.delay)
        return self.http.stream("GET", url)

    def ajax(self, method: str, args: dict[str, Any]) -> Any:
        """Call a Moodle web service function through the web UI's AJAX endpoint."""
        time.sleep(self.delay)
        response = self.http.post(
            f"{BASE_URL}/lib/ajax/service.php",
            params={"sesskey": self.sesskey, "info": method},
            json=[{"index": 0, "methodname": method, "args": args}],
        )
        response.raise_for_status()
        body = response.json()
        if isinstance(body, dict):  # whole request rejected, e.g. invalid sesskey
            raise MoodleError(f"{method}: {body.get('error')}")
        result = body[0]
        if result.get("error"):
            raise MoodleError(f"{method}: {result['exception'].get('message')}")
        return result["data"]

    # -- login state --------------------------------------------------------

    def is_logged_in(self) -> bool:
        """Check the session and remember the sesskey needed for AJAX calls."""
        response = self.http.get(f"{BASE_URL}/my/courses.php")
        return self.read_sesskey(response)

    def read_sesskey(self, response: httpx.Response) -> bool:
        match = re.search(r'"sesskey":"([^"]+)"', response.text)
        if response.url.host == MOODLE_HOST and match and "login/logout.php" in response.text:
            self.sesskey = match.group(1)
            return True
        return False

    # -- cookie cache -------------------------------------------------------

    def _load_cookies(self) -> None:
        if not self.cookie_file.is_file():
            return
        try:
            for c in json.loads(self.cookie_file.read_text()):
                self.http.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
        except (ValueError, KeyError, TypeError) as e:
            log.warning("ignoring broken cookie cache: %s", e)

    def save_cookies(self) -> None:
        cookies = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self.http.cookies.jar
            if MOODLE_HOST.removeprefix("www.") in c.domain
        ]
        self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cookie_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(cookies))
        tmp.chmod(0o600)  # the cookie is as good as a login
        tmp.replace(self.cookie_file)

    @staticmethod
    def _url(path_or_url: str) -> str:
        return path_or_url if path_or_url.startswith("http") else BASE_URL + path_or_url
