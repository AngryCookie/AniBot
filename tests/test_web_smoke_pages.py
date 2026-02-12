import importlib

from fastapi.testclient import TestClient


def _create_client(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("SESSION_ENCRYPTION_KEY", "Vp6mXFZXrj2tzwdxS8v_fMSEWk5ER5Yj8LQ6HOA3JrQ=")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test_web_smoke.db")

    import web.config as web_config
    import web.security as web_security
    import web.main as web_main

    importlib.reload(web_config)
    importlib.reload(web_security)
    importlib.reload(web_main)

    return TestClient(web_main.app)


def test_html_pages_are_served(monkeypatch):
    with _create_client(monkeypatch) as client:
        for page in ("/login.html", "/app.html", "/servers.html", "/analytics.html"):
            response = client.get(page)
            assert response.status_code == 200
            assert "text/html" in response.headers.get("content-type", "")


def test_static_js_assets_are_served_as_javascript(monkeypatch):
    with _create_client(monkeypatch) as client:
        response = client.get("/static/js/app.js")
        assert response.status_code == 200
        assert "text/javascript" in response.headers.get("content-type", "")
        assert "<!doctype html>" not in response.text.lower()
