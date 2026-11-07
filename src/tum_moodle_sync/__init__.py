"""Sync all files from TUM Moodle (www.moodle.tum.de) into a local folder.

Works without the Moodle mobile app / web service tokens: it logs in through
the TUM Shibboleth IdP like a browser would and then uses the same AJAX
endpoints and pages the Moodle web UI uses.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

BASE = "https://www.moodle.tum.de"
LOGIN_URL = (
    BASE + "/Shibboleth.sso/Login?providerId=https%3A%2F%2Ftumidp.lrz.de%2Fidp%2Fshibboleth"
    "&target=https%3A%2F%2Fwww.moodle.tum.de%2Fauth%2Fshibboleth%2Findex.php"
)
UA = "Mozilla/5.0 (X11; Linux x86_64) tum-moodle-sync/0.1"

# pluginfile areas that are never course material
IGNORED_AREAS = re.compile(r"/(theme_\w+|core_admin|user|course/overviewfiles|block_\w+)/")
PLUGINFILE_RE = re.compile(r"""https://www\.moodle\.tum\.de/(?:webservice/)?pluginfile\.php/[^"'<>\s]+""")

ASSIGN_AREAS = {"assignsubmission_file": "Abgabe", "assignfeedback_file": "Feedback",
                "assignfeedback_editpdf": "Feedback"}

log = logging.getLogger("tum-moodle-sync")


class LoginError(Exception):
    pass


# --------------------------------------------------------------------------- helpers


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)


def safe_name(s: str, maxlen: int = 120) -> str:
    s = s.replace(":", "")
    s = re.sub(r'[<>"/\\|?*\x00-\x1f]', "_", s).strip().rstrip(".")
    s = re.sub(r"\s+", " ", s)
    return (s or "_")[:maxlen]


def strip_query(url: str) -> str:
    return url.split("?", 1)[0].split("#", 1)[0]


# --------------------------------------------------------------------------- session


class Moodle:
    def __init__(self, state_dir: Path, delay: float = 0.3):
        self.state_dir = state_dir
        self.cookie_file = state_dir / "cookies.json"
        self.delay = delay
        self.sesskey: str | None = None
        self.client = httpx.Client(
            headers={"User-Agent": UA, "Accept-Language": "de,en;q=0.8"},
            timeout=httpx.Timeout(60, connect=20),
            follow_redirects=True,
        )
        self._load_cookies()

    # cookies ---------------------------------------------------------------
    def _load_cookies(self) -> None:
        if not self.cookie_file.is_file():
            return
        try:
            for c in json.loads(self.cookie_file.read_text()):
                self.client.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
        except Exception as e:  # corrupt cache -> just log in again
            log.warning("ignoring cookie cache: %s", e)

    def save_cookies(self) -> None:
        data = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self.client.cookies.jar
            if "moodle.tum.de" in c.domain
        ]
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.cookie_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.chmod(0o600)
        tmp.replace(self.cookie_file)

    # login -----------------------------------------------------------------
    def check_session(self) -> bool:
        r = self.client.get(BASE + "/my/courses.php")
        m = re.search(r'"sesskey":"([^"]+)"', r.text)
        if r.url.host == "www.moodle.tum.de" and m and "login/logout.php" in r.text:
            self.sesskey = m.group(1)
            return True
        return False

    def login(self, user: str, password: str) -> None:
        log.info("logging in as %s via login.tum.de", user)
        self.client.cookies.clear()
        r = self.client.get(LOGIN_URL)
        sent_credentials = False
        for _ in range(12):
            if r.url.host == "www.moodle.tum.de" and "login/logout.php" in r.text:
                break
            soup = BeautifulSoup(r.text, "html.parser")
            form = soup.find("form")
            if form is None:
                raise LoginError(f"no form on {r.url} (HTTP {r.status_code})")
            data: dict[str, str] = {}
            for inp in form.find_all(["input", "button", "select"]):
                name = inp.get("name")
                if not name:
                    continue
                typ = (inp.get("type") or "text").lower()
                if typ in ("checkbox", "radio") and not inp.has_attr("checked"):
                    continue
                if typ == "submit" and name != "_eventId_proceed":
                    continue
                data.setdefault(name, inp.get("value", ""))
            # Shibboleth localStorage probe (normally filled in by JS)
            if "shib_idp_ls_supported" in data:
                data["shib_idp_ls_supported"] = "false"
                for k in list(data):
                    if k.startswith("shib_idp_ls_success"):
                        data[k] = "false"
            if "j_username" in data:
                if sent_credentials:
                    err = soup.select_one(".form-error, .alert-danger, .error, output")
                    msg = err.get_text(" ", strip=True) if err else "credentials rejected"
                    raise LoginError(f"login.tum.de: {msg}")
                data["j_username"] = user
                data["j_password"] = password
                data["_eventId_proceed"] = ""
                sent_credentials = True
            action = urljoin(str(r.url), form.get("action") or str(r.url))
            method = (form.get("method") or "get").lower()
            r = self.client.post(action, data=data) if method == "post" else self.client.get(action, params=data)
        if not self.check_session():
            raise LoginError(f"login flow ended at {r.url} without a Moodle session")
        self.save_cookies()
        log.info("login ok")

    def ensure_session(self, user: str | None, password: str | None) -> None:
        if self.check_session():
            log.info("reusing cached session")
            return
        if not (user and password):
            raise LoginError("session expired and TUM_USER/TUM_PASSWORD not set")
        self.login(user, password)

    # requests --------------------------------------------------------------
    def get(self, url: str, **kw) -> httpx.Response:
        time.sleep(self.delay)
        return self.client.get(url, **kw)

    def ajax(self, method: str, args: dict):
        time.sleep(self.delay)
        r = self.client.post(
            f"{BASE}/lib/ajax/service.php",
            params={"sesskey": self.sesskey, "info": method},
            json=[{"index": 0, "methodname": method, "args": args}],
        )
        r.raise_for_status()
        res = r.json()
        if isinstance(res, dict) and res.get("error"):  # e.g. invalid sesskey
            raise RuntimeError(f"{method}: {res.get('error')}")
        res = res[0]
        if res.get("error"):
            raise RuntimeError(f"{method}: {res['exception'].get('message')}")
        return res["data"]

    # moodle data -----------------------------------------------------------
    def courses(self) -> list[dict]:
        d = self.ajax(
            "core_course_get_enrolled_courses_by_timeline_classification",
            {"offset": 0, "limit": 0, "classification": "all", "sort": "fullname",
             "customfieldname": "", "customfieldvalue": ""},
        )
        return d["courses"]

    def course_state(self, cid: int) -> dict:
        return json.loads(self.ajax("core_courseformat_get_state", {"courseid": cid}))

    def pluginfiles(self, url: str, area: str | None = None) -> list[str]:
        """All pluginfile links on a page (optionally restricted to a component/filearea)."""
        r = self.get(url)
        links = []
        for u in PLUGINFILE_RE.findall(r.text.replace("&amp;", "&")):
            if IGNORED_AREAS.search(u):
                continue
            if area and f"/{area}/" not in u:
                continue
            u = strip_query(u)
            if u not in links:
                links.append(u)
        return links


# --------------------------------------------------------------------------- sync


@dataclass
class Item:
    key: str        # stable id for manifest (cmid + path inside module)
    url: str        # pluginfile url (contains revision number)
    rel: Path       # path relative to course dir


def file_tail(url: str, after: str) -> str:
    """Path after e.g. 'mod_folder/content/<rev>/' in a pluginfile URL (keeps subfolders)."""
    path = urlparse(url).path
    m = re.search(re.escape(after) + r"/\d+/(.+)$", path)
    return unquote(m.group(1)) if m else unquote(path.rsplit("/", 1)[-1])


def module_items(m: Moodle, cm: dict, section_dir: Path) -> list[Item]:
    mod, cmid, name = cm["module"], cm["id"], safe_name(cm["name"])
    items: list[Item] = []
    if mod == "resource":
        r = m.client.get(f"{BASE}/mod/resource/view.php", params={"id": cmid, "redirect": 1}, follow_redirects=False)
        time.sleep(m.delay)
        if r.status_code in (301, 302, 303) and "pluginfile.php" in r.headers.get("location", ""):
            urls = [strip_query(r.headers["location"])]
        else:  # embedded / unusual display mode: scrape the page
            urls = m.pluginfiles(f"{BASE}/mod/resource/view.php?id={cmid}", "mod_resource/content")
        for u in urls:
            fn = safe_name(file_tail(u, "mod_resource/content"))
            items.append(Item(f"{cmid}:{fn}", u, section_dir / fn))
    elif mod == "folder":
        for u in m.pluginfiles(f"{BASE}/mod/folder/view.php?id={cmid}", "mod_folder/content"):
            sub = Path(*[safe_name(p) for p in file_tail(u, "mod_folder/content").split("/")])
            items.append(Item(f"{cmid}:{sub}", u, section_dir / name / sub))
    elif mod in ("assign", "page", "book", "lesson", "workshop", "data", "glossary"):
        for u in m.pluginfiles(f"{BASE}/mod/{mod}/view.php?id={cmid}"):
            fn = safe_name(unquote(urlparse(u).path.rsplit("/", 1)[-1]))
            area = next((v for k, v in ASSIGN_AREAS.items() if f"/{k}/" in u), "")
            rel = Path(area, fn) if area else Path(fn)
            items.append(Item(f"{cmid}:{rel}", u, section_dir / name / rel))
    return items


class Syncer:
    def __init__(self, m: Moodle, root: Path, state_dir: Path, dry_run: bool = False):
        self.m, self.root, self.dry_run = m, root, dry_run
        self.manifest_file = state_dir / "manifest.json"
        self.manifest: dict[str, dict] = (
            json.loads(self.manifest_file.read_text()) if self.manifest_file.is_file() else {}
        )
        self.stats = {"new": 0, "updated": 0, "unchanged": 0, "failed": 0}

    def save(self) -> None:
        if self.dry_run:
            return
        tmp = self.manifest_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.manifest, indent=1, ensure_ascii=False))
        tmp.replace(self.manifest_file)

    def download(self, item: Item, dest: Path, key: str) -> None:
        prev = self.manifest.get(key)
        if prev and prev["url"] == item.url and dest.is_file():
            self.stats["unchanged"] += 1
            return
        kind = "updated" if prev else "new"
        log.info("%s %s", "↻" if prev else "+", dest.relative_to(self.root))
        if self.dry_run:
            self.stats[kind] += 1
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        try:
            time.sleep(self.m.delay)
            with self.m.client.stream("GET", item.url) as r:
                r.raise_for_status()
                if r.url.host != "www.moodle.tum.de" or "/login/" in r.url.path:
                    raise RuntimeError(f"redirected to {r.url} (session lost?)")
                etag = r.headers.get("etag")
                with part.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        f.write(chunk)
            if prev and prev.get("etag") and prev["etag"] == etag and dest.is_file():
                part.unlink()
                kind = "unchanged"
            else:
                part.replace(dest)
            self.manifest[key] = {"url": item.url, "etag": etag, "path": str(dest.relative_to(self.root)),
                                  "time": int(time.time())}
            self.stats[kind] += 1
        except Exception as e:
            part.unlink(missing_ok=True)
            self.stats["failed"] += 1
            log.error("failed %s: %s", item.url, e)

    def sync_course(self, course: dict) -> None:
        cid = course["id"]
        cdir = self.root / safe_name(course["fullname"])
        log.info("== %s (%s)", course["fullname"], cid)
        st = self.m.course_state(cid)
        sections = {s["id"]: s for s in st["section"]}
        claimed: dict[Path, str] = {}
        for cm in st["cm"]:
            if not cm.get("uservisible", True):
                continue
            sec = sections.get(cm["sectionid"], {})
            sdir = cdir / safe_name(f"{int(sec.get('number', 0)):02d} {sec.get('title', '')}".strip())
            try:
                items = module_items(self.m, cm, sdir)
            except Exception as e:
                self.stats["failed"] += 1
                log.error("failed to list %s %s: %s", cm["module"], cm["name"], e)
                continue
            for it in items:
                dest = it.rel
                if dest in claimed and claimed[dest] != it.key:  # filename clash in one section
                    dest = dest.with_name(f"{dest.stem} ({cm['id']}){dest.suffix}")
                claimed[dest] = it.key
                self.download(it, dest, f"{cid}:{it.key}")
        self.save()


# --------------------------------------------------------------------------- cli


def run_once(a: argparse.Namespace, root: Path, state: Path) -> int:
    m = Moodle(state)
    try:
        m.ensure_session(os.environ.get("TUM_USER"), os.environ.get("TUM_PASSWORD"))
        courses = m.courses()
    except (LoginError, httpx.HTTPError) as e:
        log.error("%s", e)
        return 2

    if a.list:
        for c in courses:
            print(f"{c['id']:>8}  {c['fullname']}")
        return 0

    s = Syncer(m, root, state, dry_run=a.dry_run)
    for c in courses:
        if a.course and c["id"] not in a.course:
            continue
        try:
            s.sync_course(c)
        except Exception as e:
            s.stats["failed"] += 1
            log.error("course %s failed: %s", c["fullname"], e)
    m.save_cookies()
    log.info("done: %s", ", ".join(f"{k}={v}" for k, v in s.stats.items()))
    return 1 if s.stats["failed"] else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", type=Path, help="target folder (env MOODLE_DIR, default ./moodle)")
    ap.add_argument("--state-dir", type=Path, help="session + manifest (env MOODLE_STATE_DIR, default ./.state)")
    ap.add_argument("--env-file", type=Path, default=Path("config.env"))
    ap.add_argument("--course", type=int, action="append", help="only sync these course ids")
    ap.add_argument("--list", action="store_true", help="list courses and exit")
    ap.add_argument("--dry-run", action="store_true", help="show what would be downloaded")
    ap.add_argument("--interval", type=int,
                    help="repeat every N minutes (env SYNC_INTERVAL, default 0 = run once)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    load_dotenv(a.env_file)
    if a.interval is None:
        a.interval = int(os.environ.get("SYNC_INTERVAL") or 0)

    root = (a.dest or Path(os.environ.get("MOODLE_DIR", "moodle"))).expanduser()
    state = (a.state_dir or Path(os.environ.get("MOODLE_STATE_DIR", ".state"))).expanduser()
    state.mkdir(parents=True, exist_ok=True)

    if not a.interval or a.list:
        sys.exit(run_once(a, root, state))
    while True:
        run_once(a, root, state)
        log.info("next sync in %d min", a.interval)
        time.sleep(a.interval * 60)
