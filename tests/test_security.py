"""Local security: Host check, Origin check, CSRF token, response headers."""

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from tests.conftest import ORIGIN, TEST_PORT


@pytest.fixture
def secure_client(app):
    """App with one harmless POST endpoint to exercise the protections."""

    @app.post("/__test/echo")
    async def echo(request: Request):
        return {"ok": True}

    with TestClient(app, base_url=ORIGIN) as c:
        yield c


def token(app):
    return app.state.csrf_token


# ---------------------------------------------------------------- Host header

@pytest.mark.parametrize("host", ["evil.example:8765", "127.0.0.1:9999", "192.168.1.5:8765", "attacker.localhost"])
def test_foreign_host_rejected(secure_client, host):
    r = secure_client.get("/", headers={"host": host})
    assert r.status_code == 400
    assert "127.0.0.1" in r.text and 'dir="rtl"' in r.text


@pytest.mark.parametrize("host", [f"127.0.0.1:{TEST_PORT}", f"localhost:{TEST_PORT}"])
def test_local_hosts_allowed(secure_client, host):
    assert secure_client.get("/health", headers={"host": host}).status_code == 200


# ---------------------------------------------------------------- Origin / cross-site

def test_post_without_origin_rejected(secure_client, app):
    r = secure_client.post("/__test/echo", data={"csrf_token": token(app)})
    assert r.status_code == 403


@pytest.mark.parametrize("origin", ["http://evil.example", "null", f"http://127.0.0.1:{TEST_PORT + 1}",
                                    "https://127.0.0.1:8765"])
def test_post_from_foreign_origin_rejected(secure_client, app, origin):
    r = secure_client.post("/__test/echo", data={"csrf_token": token(app)}, headers={"origin": origin})
    assert r.status_code == 403


def test_cross_site_fetch_metadata_rejected(secure_client, app):
    r = secure_client.post("/__test/echo", data={"csrf_token": token(app)},
                           headers={"origin": ORIGIN, "sec-fetch-site": "cross-site"})
    assert r.status_code == 403


def test_referer_used_when_origin_missing(secure_client, app):
    r = secure_client.post("/__test/echo", data={"csrf_token": token(app)},
                           headers={"referer": f"{ORIGIN}/payments"})
    assert r.status_code == 200


# ---------------------------------------------------------------- CSRF token

def test_post_without_token_rejected_with_hebrew_page(secure_client):
    r = secure_client.post("/__test/echo", data={"x": "1"}, headers={"origin": ORIGIN})
    assert r.status_code == 403
    assert "רענן את הדף" in r.text


def test_post_with_wrong_token_rejected(secure_client):
    r = secure_client.post("/__test/echo", data={"csrf_token": "forged"}, headers={"origin": ORIGIN})
    assert r.status_code == 403


def test_post_with_form_token_accepted(secure_client, app):
    r = secure_client.post("/__test/echo", data={"csrf_token": token(app)},
                           headers={"origin": ORIGIN, "sec-fetch-site": "same-origin"})
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_post_with_header_token_accepted(secure_client, app):
    r = secure_client.post("/__test/echo", json={}, headers={"origin": ORIGIN, "x-csrf-token": token(app)})
    assert r.status_code == 200


def test_multipart_form_token_accepted(secure_client, app):
    r = secure_client.post("/__test/echo", data={"csrf_token": token(app)},
                           files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")}, headers={"origin": ORIGIN})
    assert r.status_code == 200


def test_token_is_embedded_in_pages(client, app):
    html = client.get("/").text
    assert f'<meta name="csrf-token" content="{token(app)}">' in html


def test_each_app_instance_has_its_own_token(config, clock):
    from app.main import create_app
    assert create_app(config, clock).state.csrf_token != create_app(config, clock).state.csrf_token


# ---------------------------------------------------------------- headers

def test_security_headers_on_html(client):
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_static_files_get_nosniff_but_no_csp(client):
    r = client.get("/static/css/app.css")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in r.headers
