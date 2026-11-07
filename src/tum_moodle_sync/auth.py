"""Login through the TUM Shibboleth identity provider (login.tum.de).

The IdP is a chain of plain HTML forms (localStorage probe, username/password,
optional attribute-release consent, SAML response). We submit each form like a
browser would until we land back on Moodle with a session.
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from tum_moodle_sync.session import MoodleSession

LOGIN_URL = (
    "https://www.moodle.tum.de/Shibboleth.sso/Login"
    "?providerId=https%3A%2F%2Ftumidp.lrz.de%2Fidp%2Fshibboleth"
    "&target=https%3A%2F%2Fwww.moodle.tum.de%2Fauth%2Fshibboleth%2Findex.php"
)
MAX_FORM_STEPS = 12

log = logging.getLogger(__name__)


class LoginError(Exception):
    pass


def ensure_logged_in(session: MoodleSession, user: str | None, password: str | None) -> None:
    """Reuse the cached session if it is still valid, otherwise log in."""
    if session.is_logged_in():
        log.info("reusing cached session")
        return
    if not (user and password):
        raise LoginError("no valid session and TUM_USER / TUM_PASSWORD are not set")
    login(session, user, password)


def login(session: MoodleSession, user: str, password: str) -> None:
    log.info("logging in as %s via login.tum.de", user)
    http = session.http
    http.cookies.clear()
    response = http.get(LOGIN_URL)
    credentials_sent = False

    for _ in range(MAX_FORM_STEPS):
        if session.read_sesskey(response):
            session.save_cookies()
            log.info("login ok")
            return

        soup = BeautifulSoup(response.text, "html.parser")
        form = soup.find("form")
        if not isinstance(form, Tag):
            raise LoginError(f"unexpected page without form: {response.url} (HTTP {response.status_code})")

        fields = form_fields(form)
        prepare_localstorage_probe(fields)
        if "j_username" in fields:
            if credentials_sent:  # we are back on the login form -> rejected
                raise LoginError(f"login.tum.de: {error_message(soup)}")
            fields.update(j_username=user, j_password=password, _eventId_proceed="")
            credentials_sent = True

        response = submit(http, response, form, fields)

    raise LoginError(f"login did not finish after {MAX_FORM_STEPS} steps (last page: {response.url})")


def form_fields(form: Tag) -> dict[str, str]:
    """Values a browser would send when submitting the form."""
    fields: dict[str, str] = {}
    for element in form.find_all(["input", "button", "select"]):
        name = element.get("name")
        if not name:
            continue
        kind = str(element.get("type") or "text").lower()
        if kind in ("checkbox", "radio") and not element.has_attr("checked"):
            continue
        if kind == "submit" and name != "_eventId_proceed":
            continue
        fields.setdefault(str(name), str(element.get("value") or ""))
    return fields


def prepare_localstorage_probe(fields: dict[str, str]) -> None:
    """The first IdP page normally runs JS to test localStorage; answer 'unsupported'."""
    if "shib_idp_ls_supported" not in fields:
        return
    fields["shib_idp_ls_supported"] = "false"
    for name in fields:
        if name.startswith("shib_idp_ls_success"):
            fields[name] = "false"


def error_message(soup: BeautifulSoup) -> str:
    element = soup.select_one(".form-error, .alert-danger, .error, output")
    return element.get_text(" ", strip=True) if element else "credentials rejected"


def submit(http: httpx.Client, page: httpx.Response, form: Tag, fields: dict[str, str]) -> httpx.Response:
    action = urljoin(str(page.url), str(form.get("action") or page.url))
    if str(form.get("method") or "get").lower() == "post":
        return http.post(action, data=fields)
    return http.get(action, params=fields)

