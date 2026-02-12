import importlib
import logging

from fastapi import Request
from fastapi.testclient import TestClient


def _base_env(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("SESSION_ENCRYPTION_KEY", "Vp6mXFZXrj2tzwdxS8v_fMSEWk5ER5Yj8LQ6HOA3JrQ=")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test_web_oauth_session_flow.db")
    monkeypatch.setenv("DISCORD_CLIENT_ID", "client-id")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "http://localhost:8000/auth/callback")


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *_args, **_kwargs):
        return _FakeResponse(
            {
                "access_token": "discord-access-token",
                "refresh_token": "discord-refresh-token",
                "expires_in": 3600,
            }
        )


def test_auth_callback_sets_cookie_and_debug_sees_cookie(monkeypatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("WEB_BASE_URL", "http://localhost:8000")

    import web.config as web_config
    import web.security as web_security
    import web.main as web_main

    importlib.reload(web_config)
    importlib.reload(web_security)
    importlib.reload(web_main)

    monkeypatch.setattr(web_main.httpx, "AsyncClient", _FakeAsyncClient)

    async def _fake_fetch_user(_token: str):
        return {"id": "42"}

    async def _fake_fetch_user_guilds(_token: str):
        return [{"id": "777", "permissions": str(0x28)}]

    monkeypatch.setattr(web_main, "fetch_user", _fake_fetch_user)
    monkeypatch.setattr(web_main, "fetch_user_guilds", _fake_fetch_user_guilds)

    @web_main.app.get("/__test__/seed-oauth")
    async def _seed_oauth(request: Request):
        request.session["oauth_state"] = "state-123"
        return {"ok": True}

    with TestClient(web_main.app, base_url="http://localhost:8000") as client:
        seed = client.get("/__test__/seed-oauth")
        assert seed.status_code == 200

        callback = client.get("/auth/callback?code=abc&state=state-123", follow_redirects=False)
        assert callback.status_code == 302
        assert callback.headers.get("location") == "/app.html?guild_id=777"
        assert "set-cookie" in {k.lower() for k in callback.headers.keys()}

        debug = client.get("/api/debug/session")
        assert debug.status_code == 200
        payload = debug.json()
        assert payload["cookie_present"] is True
        assert payload["access_token_failure_reason"] is None


def test_auth_callback_logs_host_mismatch(monkeypatch, caplog):
    _base_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WEB_BASE_URL", "http://localhost:8000")

    import web.config as web_config
    import web.security as web_security
    import web.main as web_main

    importlib.reload(web_config)
    importlib.reload(web_security)
    importlib.reload(web_main)

    monkeypatch.setattr(web_main.httpx, "AsyncClient", _FakeAsyncClient)

    async def _fake_fetch_user(_token: str):
        return {"id": "42"}

    async def _fake_fetch_user_guilds(_token: str):
        return [{"id": "777", "permissions": str(0x28)}]

    monkeypatch.setattr(web_main, "fetch_user", _fake_fetch_user)
    monkeypatch.setattr(web_main, "fetch_user_guilds", _fake_fetch_user_guilds)

    @web_main.app.get("/__test__/seed-oauth-2")
    async def _seed_oauth_2(request: Request):
        request.session["oauth_state"] = "state-456"
        return {"ok": True}

    with TestClient(web_main.app, base_url="http://127.0.0.1:8000") as client:
        client.get("/__test__/seed-oauth-2")
        with caplog.at_level(logging.WARNING):
            response = client.get("/auth/callback?code=abc&state=state-456", follow_redirects=False)

    assert response.status_code == 302
    messages = [record.message for record in caplog.records]
    assert any("oauth.callback.host_mismatch" in msg for msg in messages)
