"""The backend serves the chat widget so other sites can embed it with one script tag."""

import pytest
from fastapi.testclient import TestClient

from mpd_assistant.api.main import WIDGET_UI_DIR, Services, create_app

SITE = "https://www.masterprodev.com"


def client(origins=(SITE,)):
    return TestClient(create_app(Services(chat=None, sessions=None, identity=None, cors_origins=tuple(origins))))


def test_script_and_stylesheet_are_served_for_cross_site_embedding():
    c = client()
    js, css = c.get("/widget/chat-widget.js"), c.get("/widget/chat-widget.css")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"] and "MasterProDev chat widget" in js.text
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    assert js.headers["cross-origin-resource-policy"] == "cross-origin" and "max-age=300" in js.headers["cache-control"]


def test_the_hosted_page_uses_the_widget_with_a_strict_policy():
    page = client().get("/widget")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp and "frame-ancestors 'none'" in csp
    assert 'src="/widget/chat-widget.js"' in page.text and 'data-mode="full"' in page.text
    assert 'href="/widget/widget-page.css"' in page.text and client().get("/widget/widget-page.css").status_code == 200


@pytest.mark.parametrize("path", ["/widget/index.html", "/widget/..%2Fmain.py", "/widget/%2e%2e/app.py", "/widget/secrets"])
def test_nothing_else_under_widget_is_reachable(path):
    assert client().get(path).status_code == 404


def test_the_widget_defaults_to_the_server_it_was_loaded_from():
    code = (WIDGET_UI_DIR / "chat-widget.js").read_text(encoding="utf-8")
    assert "new URL(script.src" in code and 'getAttribute("data-api")' in code


def test_only_listed_sites_may_call_the_api_from_a_browser():
    c = client()
    ask = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    allowed = c.options("/v2/chat", headers={"Origin": SITE, **ask})
    assert allowed.status_code == 200 and allowed.headers["access-control-allow-origin"] == SITE
    assert "access-control-allow-credentials" not in allowed.headers
    refused = c.options("/v2/chat", headers={"Origin": "https://evil.example", **ask})
    assert "access-control-allow-origin" not in refused.headers
