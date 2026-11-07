"""Helpers for Moodle file URLs (pluginfile.php) and local file names."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

PLUGINFILE_LINK = re.compile(r"""https://www\.moodle\.tum\.de/(?:webservice/)?pluginfile\.php/[^"'<>\s]+""")

# File areas that never contain course material (theme images, avatars, ...).
IGNORED_AREAS = re.compile(r"/(theme_\w+|core_admin|user|course/overviewfiles|block_\w+)/")


def find_links(html: str, area: str | None = None) -> list[str]:
    """Unique pluginfile links in a page, optionally limited to one file area."""
    links: list[str] = []
    for url in PLUGINFILE_LINK.findall(html.replace("&amp;", "&")):
        if IGNORED_AREAS.search(url) or (area and f"/{area}/" not in url):
            continue
        url = strip_query(url)
        if url not in links:
            links.append(url)
    return links


def path_in_area(url: str, area: str) -> str:
    """File path after '<area>/<revision>/', keeping subfolders.

    .../mod_folder/content/3/sub/a.pdf  ->  'sub/a.pdf'
    """
    path = urlparse(url).path
    match = re.search(re.escape(area) + r"/\d+/(.+)$", path)
    return unquote(match.group(1)) if match else filename(url)


def filename(url: str) -> str:
    return unquote(urlparse(url).path.rsplit("/", 1)[-1])


def strip_query(url: str) -> str:
    return url.split("#", 1)[0].split("?", 1)[0]


def safe_name(name: str, max_length: int = 120) -> str:
    """Make a Moodle title usable as a file or folder name."""
    name = name.replace(":", "")
    name = re.sub(r'[<>"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(".")
    name = re.sub(r"\s+", " ", name)
    return (name or "_")[:max_length]
