"""The staff console and the chat widget: how the console is served, and static guarantees about both scripts."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mpd_assistant.api.main import ADMIN_UI_DIR, Services, create_app
from mpd_assistant.business.admin import AdminService
from mpd_assistant.business.escalations import EscalationService, InMemoryEscalations

ROOT = Path(__file__).resolve().parents[2]
WIDGET_JS = ROOT / "web" / "widget" / "chat-widget.js"
ADMIN_JS = ADMIN_UI_DIR / "admin.js"


def app_with_admin(enabled=True):
    admin = AdminService(EscalationService(repo=InMemoryEscalations()), InMemoryEscalations()) if enabled else None
    return create_app(Services(chat=None, sessions=None, identity=None, admin=admin, admin_token="staff"))


# --- serving the console -----------------------------------------------------------------
def test_console_is_served_with_a_strict_policy():
    client = TestClient(app_with_admin())
    page = client.get("/admin")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"] and "Staff Console" in page.text
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp and "frame-ancestors 'none'" in csp
    assert page.headers["cache-control"] == "no-store"
    js, css = client.get("/admin/admin.js"), client.get("/admin/admin.css")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]


def test_console_serves_nothing_else_and_vanishes_without_staff_access():
    client = TestClient(app_with_admin())
    for path in ("/admin/index.html", "/admin/..%2Fmain.py", "/admin/secrets", "/admin/%2e%2e/app.py"):
        assert client.get(path).status_code == 404, path
    off = TestClient(app_with_admin(enabled=False))
    assert off.get("/admin").status_code == 404 and off.get("/admin/admin.js").status_code == 404


def test_console_page_has_no_inline_script_or_style():
    html = (ADMIN_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and "<style" not in html and "onclick" not in html.lower()


def test_console_assets_are_shipped_as_package_data():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "api/static/**/*" in pyproject
    assert {p.name for p in ADMIN_UI_DIR.iterdir()} >= {"index.html", "admin.js", "admin.css"}


# --- static guarantees for both scripts --------------------------------------------------
@pytest.mark.parametrize("script", [WIDGET_JS, ADMIN_JS], ids=["widget", "console"])
def test_scripts_never_build_markup_from_text(script):
    source = script.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)  # comments may mention the banned words
    code = re.sub(r"(?<![:\"'])//[^\n]*", "", code)
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert banned not in code, f"{script.name} uses {banned}"


@pytest.mark.parametrize("script", [WIDGET_JS, ADMIN_JS], ids=["widget", "console"])
def test_every_api_path_a_script_calls_exists(script):
    app = app_with_admin()
    templates = [r.path for r in app.routes if hasattr(r, "path")]
    patterns = [re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", t) + "$") for t in templates]
    called = set(re.findall(r'"(/v2/[A-Za-z0-9_/\-{}]*)', script.read_text(encoding="utf-8")))
    assert called, "no API calls found"
    for path in called:
        if path.endswith("/"):  # a prefix the script completes at run time, such as /v2/admin/quotes/ + reference
            assert any(t.startswith(path) for t in templates), path
        else:
            assert any(p.match(path) for p in patterns), path


def test_widget_account_panel_covers_the_account_api():
    code = WIDGET_JS.read_text(encoding="utf-8")
    for needed in ("/v2/account/stepup/start", "/v2/account/stepup/verify", "/v2/integrations/google/start", "/v2/integrations/google/disconnect",
                   "/v2/memory/consent", "/v2/memory/forget", "/v2/account/export", "/v2/account/delete", "/end"):
        assert needed in code, needed
    assert "noopener" in code  # the Google tab cannot reach back into the page


def test_console_calls_the_admin_routes_with_the_staff_token_only():
    code = ADMIN_JS.read_text(encoding="utf-8")
    assert "Authorization" in code and "localStorage" not in code  # the token lives in the tab, not on disk
    for needed in ("/v2/admin/overview", "/v2/admin/escalations", "/v2/admin/quotes", "/v2/admin/patterns", "/v2/admin/undelivered", "/v2/admin/people"):
        assert needed in code, needed
