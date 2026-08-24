"""Tests for amplifier_app_log_viewer.auth -- the PAM/password auth gate.

No auth-disable switch exists, so every test authenticates for real (see
conftest.py's `client`/`anon_client` fixtures). This is the point: the gate
is exercised on every existing endpoint test rather than bypassed.
"""

import time

import pytest
from amplifier_app_log_viewer.auth import (
    AuthConfig,
    authenticate_pam,
    create_session_cookie,
    validate_next_path,
    verify_session_cookie,
)
from amplifier_app_log_viewer.server import create_app
from itsdangerous import TimestampSigner


class TestValidateNextPath:
    @pytest.mark.parametrize(
        "unsafe",
        [
            "//evil.com",
            "\\\\evil",
            "javascript:x",
            "http://x",
            "/a/../../b",
            "/a\x01b",
        ],
    )
    def test_rejects_unsafe_values(self, unsafe):
        assert validate_next_path(unsafe) == "/"

    def test_allows_safe_path_with_query(self):
        assert validate_next_path("/deck?x=1") == "/deck?x=1"


class TestGateBasics:
    def test_anonymous_api_request_is_401_json(self, anon_client):
        response = anon_client.get("/api/status")
        assert response.status_code == 401
        assert response.get_json()["error"]

    def test_anonymous_browser_request_redirects_to_login(self, anon_client):
        response = anon_client.get("/")
        assert response.status_code == 302
        assert response.headers["Location"] == "/login?next=%2F"

    def test_static_asset_is_exempt(self, anon_client):
        response = anon_client.get("/static/app.js")
        assert response.status_code == 200

    def test_suffix_bypass_regression_guard(self, anon_client):
        """A session literally named 'probe.js' must NOT bypass the gate --
        this is the muxplex CVE class (GHSA-7c6r-fvrh-9qp4's sibling bug).
        Endpoint-based exemption means the trailing '.js' has zero effect."""
        response = anon_client.get("/api/events/probe.js/1")
        assert response.status_code == 401

    def test_login_page_is_exempt(self, anon_client):
        response = anon_client.get("/login")
        assert response.status_code == 200

    def test_clickjacking_headers_present(self, anon_client):
        """Every response carries anti-framing headers (L4)."""
        response = anon_client.get("/login")
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Content-Security-Policy"] == "frame-ancestors 'none'"

    def test_login_next_value_is_html_escaped(self, anon_client):
        """A malicious ?next= must render HTML-escaped in the login page, so a
        future template change that disabled autoescape can't turn it into
        stored/reflected XSS (I1 belt-and-suspenders regression guard)."""
        response = anon_client.get(
            "/login", query_string={"next": '/"><script>alert(1)</script>'}
        )
        assert response.status_code == 200
        # The raw, un-escaped script tag must NOT appear in the rendered HTML.
        assert b"<script>alert(1)</script>" not in response.data
        # ...and the escaped form must, proving the value was actually rendered
        # (not merely absent because it was rejected upstream).
        assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in response.data


class TestLogout:
    def test_logout_get_is_rejected(self, client):
        """GET must not log out -- it's state-changing and would be CSRF-
        triggerable via <img src=".../auth/logout"> (L1). The authenticated
        client reaches routing (past the gate), which returns 405 for GET."""
        response = client.get("/auth/logout")
        assert response.status_code == 405

    def test_logout_post_clears_cookie_and_redirects(self, client):
        response = client.post("/auth/logout")
        assert response.status_code == 303
        assert response.headers["Location"] == "/login"
        set_cookie = response.headers.get("Set-Cookie", "")
        assert "amplifier_log_viewer_session=" in set_cookie
        # delete_cookie emits an immediate expiry.
        assert "Max-Age=0" in set_cookie or "Expires=" in set_cookie


class TestLoginFlow:
    def test_correct_password_sets_cookie_and_redirects(self, anon_client):
        response = anon_client.post(
            "/login", data={"username": "", "password": "test-pw", "next": "/"}
        )
        assert response.status_code == 303
        set_cookie = response.headers.get("Set-Cookie", "")
        assert "amplifier_log_viewer_session" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=Strict" in set_cookie

    def test_wrong_password_redirects_to_error_no_cookie(self, anon_client):
        response = anon_client.post(
            "/login", data={"username": "", "password": "wrong", "next": "/"}
        )
        assert response.status_code == 303
        assert response.headers["Location"] == "/login?error=1"
        assert "Set-Cookie" not in response.headers

    def test_open_redirect_next_is_refused(self, anon_client):
        response = anon_client.post(
            "/login",
            data={"username": "", "password": "test-pw", "next": "//evil.com"},
        )
        assert response.status_code == 303
        assert response.headers["Location"] == "/"


class TestCookieVerification:
    def test_cookie_from_different_secret_is_rejected(self, anon_client):
        forged = (
            TimestampSigner("some-other-secret")
            .sign("amplifier-log-viewer-session")
            .decode()
        )
        anon_client.set_cookie("amplifier_log_viewer_session", forged)
        response = anon_client.get("/api/status")
        assert response.status_code == 401

    def test_expired_cookie_fails_verification(self):
        cookie = create_session_cookie("test-secret")
        time.sleep(2)
        assert verify_session_cookie("test-secret", cookie, ttl_seconds=1) is False


class TestBasicAuth:
    def test_basic_with_wrong_password_is_terminal_401(self, app):
        import base64

        c = app.test_client()
        c.environ_base["HTTP_AUTHORIZATION"] = (
            "Basic " + base64.b64encode(b":wrong").decode()
        )
        response = c.get("/api/status")
        assert response.status_code == 401


class TestPamUsernameGate:
    def test_wrong_username_never_reaches_pam_authenticate(self, monkeypatch):
        import pam

        def _boom(*_args, **_kwargs):
            raise AssertionError(
                "pam.authenticate must not be called for a mismatched username"
            )

        monkeypatch.setattr(pam, "authenticate", _boom)
        assert authenticate_pam("not-the-running-user", "x") is False


class TestBasePathVariant:
    def test_anonymous_request_redirects_under_base_path(self):
        cfg = AuthConfig(
            mode="password",
            secret="test-secret",
            ttl_seconds=604800,
            password="test-pw",
        )
        app = create_app(auth=cfg, base_path="/lv")
        client = app.test_client()

        response = client.get("/lv/")
        assert response.status_code == 302
        assert response.headers["Location"].startswith("/lv/login")


class TestSecureCookieFlag:
    def test_forwarded_proto_header_is_never_trusted(self, app):
        from amplifier_app_log_viewer.auth import _should_mark_secure

        with app.test_request_context(
            "/api/status", headers={"X-Forwarded-Proto": "https"}
        ):
            cfg = AuthConfig(
                mode="password",
                secret="test-secret",
                ttl_seconds=604800,
                password="test-pw",
                behind_tls_proxy=False,
            )
            assert _should_mark_secure(cfg) is False
