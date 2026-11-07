"""Plain data objects passed between the API, the extractors and the syncer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Course:
    id: int
    name: str


@dataclass(frozen=True)
class Section:
    id: int
    number: int
    title: str

    @property
    def label(self) -> str:
        """Folder label, e.g. '02 20. Oktober - 26. Oktober'."""
        return f"{self.number:02d} {self.title}".strip()


@dataclass(frozen=True)
class Module:
    """A course module ("activity"), e.g. a resource, folder or assignment."""

    id: int
    kind: str
    name: str
    section: Section


@dataclass(frozen=True)
class RemoteFile:
    """A downloadable file belonging to a module.

    key:  stable identity of the file inside its module (used in the manifest)
    url:  pluginfile URL; contains a revision number that changes on re-upload
    path: local path relative to the section folder
    """

    key: str
    url: str
    path: Path
