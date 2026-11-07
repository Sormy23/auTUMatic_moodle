"""Command line entry point: tum-moodle-sync."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import httpx

from tum_moodle_sync.api import MoodleAPI
from tum_moodle_sync.auth import LoginError, ensure_logged_in
from tum_moodle_sync.config import DEFAULT_ENV_FILE, Config
from tum_moodle_sync.manifest import Manifest
from tum_moodle_sync.session import MoodleError, MoodleSession
from tum_moodle_sync.sync import Syncer

EXIT_OK, EXIT_PARTIAL, EXIT_LOGIN = 0, 1, 2

log = logging.getLogger("tum_moodle_sync")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="tum-moodle-sync", description="Sync all files from TUM Moodle.")
    p.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="config file (default: config.env)")
    p.add_argument("--dest", type=Path, help="target folder (MOODLE_DIR, default ./moodle)")
    p.add_argument("--state-dir", type=Path, help="session and manifest (MOODLE_STATE_DIR, default ./.state)")
    p.add_argument("--interval", type=int, help="repeat every N minutes (SYNC_INTERVAL, default 0 = once)")
    p.add_argument("--course", type=int, action="append", help="only sync this course id (repeatable)")
    p.add_argument("--list", action="store_true", help="list courses and exit")
    p.add_argument("--dry-run", action="store_true", help="show what would be downloaded")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def run_once(config: Config, args: argparse.Namespace) -> int:
    session = MoodleSession(config.state_dir / "cookies.json")
    api = MoodleAPI(session)
    try:
        ensure_logged_in(session, config.user, config.password)
        courses = api.courses()
    except (LoginError, MoodleError, httpx.HTTPError) as e:
        log.error("%s", e)
        return EXIT_LOGIN

    if args.list:
        for course in courses:
            print(f"{course.id:>8}  {course.name}")
        return EXIT_OK

    if args.course:
        courses = [c for c in courses if c.id in args.course]

    manifest = Manifest(config.state_dir / "manifest.json")
    stats = Syncer(api, config.dest, manifest, dry_run=args.dry_run).sync(courses)
    session.save_cookies()
    log.info("done: %s", stats)
    return EXIT_PARTIAL if stats.failed else EXIT_OK


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = Config.load(args.env_file, dest=args.dest, state_dir=args.state_dir, interval_minutes=args.interval)
    config.state_dir.mkdir(parents=True, exist_ok=True)

    if not config.interval_minutes or args.list:
        sys.exit(run_once(config, args))

    while True:
        run_once(config, args)
        log.info("next sync in %d min", config.interval_minutes)
        time.sleep(config.interval_minutes * 60)
