"""Shared fixtures: no auth-disable switch exists, so tests authenticate for
real. This is the point -- the gate is exercised on every existing endpoint
test rather than bypassed."""

from base64 import b64encode

import pytest
from amplifier_app_log_viewer.auth import AuthConfig
from amplifier_app_log_viewer.server import create_app


def basic_auth_client(app, username: str = "", password: str = "test-pw"):
    """Build a test client that presents valid HTTP Basic credentials.

    Shared by the `client` fixture below and by tests/test_server.py's
    ad-hoc `create_app(...)` calls that need their own custom `roots=`.
    """
    c = app.test_client()
    creds = f"{username}:{password}".encode()
    c.environ_base["HTTP_AUTHORIZATION"] = "Basic " + b64encode(creds).decode()
    return c


@pytest.fixture
def auth_cfg():
    return AuthConfig(
        mode="password", secret="test-secret", ttl_seconds=604800, password="test-pw"
    )


@pytest.fixture
def app(auth_cfg, tmp_path):
    # Explicit (empty) roots -- never fall through to the real default roots
    # (~/.amplifier/projects, ~/.amplifier-agent/state/workspaces), which on
    # a real dev machine can be enormous and make every auth-only test scan
    # gigabytes of unrelated session data.
    return create_app([tmp_path], auth=auth_cfg)


@pytest.fixture
def client(app):
    """Test client that presents valid Basic credentials on every request."""
    return basic_auth_client(app)


@pytest.fixture
def anon_client(app):
    """Test client with no credentials."""
    return app.test_client()
