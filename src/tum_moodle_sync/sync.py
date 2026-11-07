"""Mirror all course files into the destination folder."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from tum_moodle_sync.api import MoodleAPI
from tum_moodle_sync.downloader import download
from tum_moodle_sync.extractors import files_of
from tum_moodle_sync.manifest import Manifest
from tum_moodle_sync.models import Course, RemoteFile
from tum_moodle_sync.pluginfile import safe_name

log = logging.getLogger(__name__)


@dataclass
class Stats:
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0

    def __str__(self) -> str:
        return f"new={self.new}, updated={self.updated}, unchanged={self.unchanged}, failed={self.failed}"


@dataclass(frozen=True)
class PlannedFile:
    key: str      # manifest key: "<course>:<module>:<file key>"
    file: RemoteFile
    dest: Path


class Syncer:
    def __init__(self, api: MoodleAPI, dest: Path, manifest: Manifest, dry_run: bool = False) -> None:
        self.api = api
        self.dest = dest
        self.manifest = manifest
        self.dry_run = dry_run
        self.stats = Stats()

    def sync(self, courses: list[Course]) -> Stats:
        for course in courses:
            try:
                self.sync_course(course)
            except Exception as e:
                self.stats.failed += 1
                log.error("course %s failed: %s", course.name, e)
        return self.stats

    def sync_course(self, course: Course) -> None:
        log.info("== %s (%s)", course.name, course.id)
        for planned in self.plan(course):
            self.sync_file(planned)
        if not self.dry_run:
            self.manifest.save()

    def plan(self, course: Course) -> list[PlannedFile]:
        """All files of a course with their local destination."""
        course_dir = self.dest / safe_name(course.name)
        planned: list[PlannedFile] = []
        taken: set[Path] = set()
        for module in self.api.modules(course):
            try:
                files = files_of(self.api, module)
            except Exception as e:
                self.stats.failed += 1
                log.error("could not list %s '%s': %s", module.kind, module.name, e)
                continue
            for file in files:
                dest = course_dir / safe_name(module.section.label) / file.path
                if dest in taken:  # two modules in one section with the same file name
                    dest = dest.with_name(f"{dest.stem} ({module.id}){dest.suffix}")
                taken.add(dest)
                planned.append(PlannedFile(f"{course.id}:{module.id}:{file.key}", file, dest))
        return planned

    def sync_file(self, planned: PlannedFile) -> None:
        key, url, dest = planned.key, planned.file.url, planned.dest
        if self.manifest.is_current(key, url, dest):
            self.stats.unchanged += 1
            return

        is_update = key in self.manifest
        log.info("%s %s", "↻" if is_update else "+", dest.relative_to(self.dest))
        if self.dry_run:
            self._count(is_update)
            return

        try:
            part, etag = download(self.api.session, url, dest)
        except Exception as e:
            self.stats.failed += 1
            log.error("download failed %s: %s", url, e)
            return

        if is_update and etag and etag == self.manifest.etag(key) and dest.is_file():
            part.unlink()  # new revision number, identical content
            self.stats.unchanged += 1
        else:
            part.replace(dest)
            self._count(is_update)
        self.manifest.record(key, url, etag, str(dest.relative_to(self.dest)))

    def _count(self, is_update: bool) -> None:
        if is_update:
            self.stats.updated += 1
        else:
            self.stats.new += 1
