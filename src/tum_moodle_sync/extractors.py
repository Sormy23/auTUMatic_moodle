"""Find the files of a module. One function per module type.

To support a new module type, write a function and add it to EXTRACTORS.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tum_moodle_sync.api import MoodleAPI
from tum_moodle_sync.models import Module, RemoteFile
from tum_moodle_sync.pluginfile import filename, path_in_area, safe_name

# Assignment file areas and the subfolder their files go to.
ASSIGNMENT_AREAS = {
    "assignsubmission_file": "Abgabe",
    "assignfeedback_file": "Feedback",
    "assignfeedback_editpdf": "Feedback",
}


def resource_files(api: MoodleAPI, module: Module) -> list[RemoteFile]:
    """A single file, stored directly in the section folder."""
    area = "mod_resource/content"
    url = api.resource_file_url(module.id)
    urls = [url] if url else api.file_links(module, area)  # embedded display mode
    files = []
    for url in urls:
        name = safe_name(path_in_area(url, area))
        files.append(RemoteFile(key=name, url=url, path=Path(name)))
    return files


def folder_files(api: MoodleAPI, module: Module) -> list[RemoteFile]:
    """All files of a folder, kept in a subfolder named after it (with its own subfolders)."""
    area = "mod_folder/content"
    files = []
    for url in api.file_links(module, area):
        inner = Path(*(safe_name(part) for part in path_in_area(url, area).split("/")))
        files.append(RemoteFile(key=str(inner), url=url, path=Path(safe_name(module.name)) / inner))
    return files


def attached_files(api: MoodleAPI, module: Module) -> list[RemoteFile]:
    """Files linked on the module page (assignment sheets, feedback, page attachments)."""
    files = []
    for url in api.file_links(module):
        name = Path(safe_name(filename(url)))
        subfolder = next((folder for area, folder in ASSIGNMENT_AREAS.items() if f"/{area}/" in url), None)
        inner = subfolder / name if subfolder else name
        files.append(RemoteFile(key=str(inner), url=url, path=Path(safe_name(module.name)) / inner))
    return files


Extractor = Callable[[MoodleAPI, Module], list[RemoteFile]]

EXTRACTORS: dict[str, Extractor] = {
    "resource": resource_files,
    "folder": folder_files,
    **{kind: attached_files for kind in ("assign", "page", "book", "lesson", "workshop", "data", "glossary")},
}


def files_of(api: MoodleAPI, module: Module) -> list[RemoteFile]:
    """Files of a module; empty for types without files (forum, quiz, url, ...)."""
    extractor = EXTRACTORS.get(module.kind)
    return extractor(api, module) if extractor else []
