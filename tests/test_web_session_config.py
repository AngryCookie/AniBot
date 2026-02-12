import importlib

from fastapi import Request
from fastapi.testclient import TestClient


def _base_env(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("SESSION_ENCRYPTION_KEY", "Vp6mXFZXrj2tzwdxS8v_fMSEWk5ER5Yj8LQ6HOA3JrQ=")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test_web_session_config.db")


def test_session_same_site_parsing_accepts_known_values(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("SESSION_SAME_SITE", "StRiCt")

    import web.config as web_config

    importlib.reload(web_config)
    assert web_config.settings.session_same_site == "strict"


def test_session_same_site_parsing_rejects_invalid_value(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("SESSION_SAME_SITE", "549")

    import web.config as web_config

    try:
        importlib.reload(web_config)
        assert False, "Expected RuntimeError for invalid SESSION_SAME_SITE"
    except RuntimeError as exc:
        assert "SESSION_SAME_SITE" in str(exc)




def test_session_max_age_rejects_non_int(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("SESSION_MAX_AGE_SECONDS", "abc")

    import web.config as web_config

    try:
        importlib.reload(web_config)
        assert False, "Expected RuntimeError for invalid SESSION_MAX_AGE_SECONDS"
    except RuntimeError as exc:
        assert "SESSION_MAX_AGE_SECONDS" in str(exc)

def test_session_middleware_receives_same_site_as_string(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("SESSION_SAME_SITE", "lax")
    monkeypatch.setenv("APP_ENV", "development")

    import web.config as web_config
    import web.security as web_security
    import web.main as web_main

    importlib.reload(web_config)
    importlib.reload(web_security)
    importlib.reload(web_main)

    middleware = next(m for m in web_main.app.user_middleware if m.cls.__name__ == "SessionMiddleware")
    same_site = middleware.kwargs.get("same_site")

    assert isinstance(same_site, str)
    assert same_site == "lax"


def test_debug_session_payload_hides_tokens(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")

    import web.config as web_config
    import web.security as web_security
    import web.main as web_main

    importlib.reload(web_config)
    importlib.reload(web_security)
    importlib.reload(web_main)

    @web_main.app.get("/__test__/seed-session")
    async def _seed_session(request: Request):
        request.session["access_token"] = "hidden"
        request.session["refresh_token"] = "hidden"
        request.session["expires_at"] = 123
        request.session["discord_user_id"] = "42"
        return {"ok": True}

    with TestClient(web_main.app) as client:
        seed = client.get("/__test__/seed-session")
        assert seed.status_code == 200

        response = client.get("/api/debug/session")
        assert response.status_code == 200
        payload = response.json()

    assert "access_token" not in payload
    assert "refresh_token" not in payload
    assert "access_token" in payload["session_keys"]
    assert "refresh_token" in payload["session_keys"]
