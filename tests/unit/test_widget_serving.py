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


def test_company_content_is_served_and_matches_the_company_documents():
    import importlib.util
    import json
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "build_company_content.py"
    spec = importlib.util.spec_from_file_location("build_company_content", script)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    served = client().get("/widget/company.json")
    assert served.status_code == 200 and "application/json" in served.headers["content-type"]
    content = served.json()
    assert content == builder.build(), "company.json is out of date: run python scripts/build_company_content.py"
    assert content["name"] and content["tagline"] and content["overview"] and content["subtitle"]
    assert [p["number"] for p in content["pillars"]] == list(range(1, 13)) and all(p["name"] and p["summary"] for p in content["pillars"])
    assert json.loads((WIDGET_UI_DIR / "company.json").read_text(encoding="utf-8")) == content


def test_the_hosted_page_places_the_chat_beside_the_company_content():
    c = client()
    page = c.get("/widget").text
    assert 'id="hero"' in page and 'id="pillars"' in page and 'id="chat-slot"' in page and 'data-mount="#chat-slot"' in page
    landing = c.get("/widget/landing.js")
    assert landing.status_code == 200 and "javascript" in landing.headers["content-type"] and "company.json" in landing.text


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
