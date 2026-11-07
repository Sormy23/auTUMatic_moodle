"""Read-only queries against Moodle, returning model objects."""

from __future__ import annotations

import json

from tum_moodle_sync import pluginfile
from tum_moodle_sync.models import Course, Module, Section
from tum_moodle_sync.session import MoodleSession

NO_SECTION = Section(id=0, number=0, title="")


class MoodleAPI:
    def __init__(self, session: MoodleSession) -> None:
        self.session = session

    def courses(self) -> list[Course]:
        """All courses the user is enrolled in (past, current and future)."""
        data = self.session.ajax(
            "core_course_get_enrolled_courses_by_timeline_classification",
            {"offset": 0, "limit": 0, "classification": "all", "sort": "fullname",
             "customfieldname": "", "customfieldvalue": ""},
        )
        return [Course(id=c["id"], name=c["fullname"]) for c in data["courses"]]

    def modules(self, course: Course) -> list[Module]:
        """Visible modules of a course, in page order, with their section."""
        state = json.loads(self.session.ajax("core_courseformat_get_state", {"courseid": course.id}))
        sections = {
            s["id"]: Section(id=int(s["id"]), number=int(s.get("number") or 0), title=s.get("title") or "")
            for s in state["section"]
        }
        return [
            Module(id=cm["id"], kind=cm["module"], name=cm["name"], section=sections.get(cm["sectionid"], NO_SECTION))
            for cm in state["cm"]
            if cm.get("uservisible", True)
        ]

    def resource_file_url(self, module_id: int) -> str | None:
        """Direct file URL of a resource, taken from the redirect Moodle sends."""
        response = self.session.get(
            "/mod/resource/view.php", params={"id": module_id, "redirect": 1}, follow_redirects=False
        )
        location = response.headers.get("location", "")
        if response.is_redirect and "pluginfile.php" in location:
            return pluginfile.strip_query(location)
        return None

    def file_links(self, module: Module, area: str | None = None) -> list[str]:
        """File links on a module's page (e.g. folder contents, assignment attachments)."""
        response = self.session.get(f"/mod/{module.kind}/view.php", params={"id": module.id})
        return pluginfile.find_links(response.text, area)
