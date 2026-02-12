import importlib
import time
from types import SimpleNamespace


def _load_security_module(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("SESSION_ENCRYPTION_KEY", "Vp6mXFZXrj2tzwdxS8v_fMSEWk5ER5Yj8LQ6HOA3JrQ=")

    import web.config as web_config
    import web.security as web_security

    importlib.reload(web_config)
    importlib.reload(web_security)
    return web_security


def test_get_access_token_accepts_valid_session(monkeypatch):
    security = _load_security_module(monkeypatch)
    encrypted = security.encrypt_token("token-123")
    request = SimpleNamespace(session={"access_token": encrypted, "expires_at": int(time.time()) + 3600})

    assert security.get_access_token(request) == "token-123"


def test_get_access_token_rejects_expired_session(monkeypatch):
    security = _load_security_module(monkeypatch)
    encrypted = security.encrypt_token("token-123")
    request = SimpleNamespace(session={"access_token": encrypted, "expires_at": int(time.time()) - 1})

    try:
        security.get_access_token(request)
        assert False, "Expected HTTPException for expired session"
    except Exception as exc:  # HTTPException without importing fastapi in test
        assert getattr(exc, "status_code", None) == 401
        assert request.session == {}
