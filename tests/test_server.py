"""Tests for server.py functionality."""

import json

import pytest
from amplifier_app_log_viewer.server import create_app


class TestBasePath:
    """Test base_path configuration."""

    def test_base_path_default_empty(self):
        """Test that default base_path is empty string (root path)."""
        app = create_app()
        assert app.config.get("APPLICATION_ROOT") == ""

    def test_base_path_with_valid_path(self):
        """Test that valid base_path is correctly set."""
        app = create_app(base_path="/log-viewer")
        assert app.config["APPLICATION_ROOT"] == "/log-viewer"

    def test_base_path_trailing_slash_removed(self):
        """Test that trailing slash is stripped from base_path."""
        app = create_app(base_path="/log-viewer/")
        assert app.config["APPLICATION_ROOT"] == "/log-viewer"

    def test_base_path_with_multiple_segments(self):
        """Test base_path with multiple path segments."""
        app = create_app(base_path="/services/log-viewer")
        assert app.config["APPLICATION_ROOT"] == "/services/log-viewer"

    def test_base_path_missing_leading_slash_raises_error(self):
        """Test that base_path without leading slash raises ValueError."""
        with pytest.raises(ValueError, match="must start with '/'"):
            create_app(base_path="log-viewer")

    def test_base_path_with_path_traversal_raises_error(self):
        """Test that base_path with '..' raises ValueError for security."""
        with pytest.raises(ValueError, match="cannot contain '\\.\\.'"):
            create_app(base_path="/../../etc")

    def test_base_path_with_embedded_path_traversal_raises_error(self):
        """Test that base_path with embedded '..' raises ValueError."""
        with pytest.raises(ValueError, match="cannot contain '\\.\\.'"):
            create_app(base_path="/log-viewer/../etc")

    def test_base_path_with_special_characters_allowed(self):
        """Test that special characters (except '..') are allowed."""
        # These should be valid (reverse proxy will handle them)
        app = create_app(base_path="/log-viewer_v2")
        assert app.config["APPLICATION_ROOT"] == "/log-viewer_v2"

        app = create_app(base_path="/log-viewer.test")
        assert app.config["APPLICATION_ROOT"] == "/log-viewer.test"

    def test_base_path_empty_string_explicitly(self):
        """Test that explicitly passing empty string works."""
        app = create_app(base_path="")
        assert app.config.get("APPLICATION_ROOT") == ""

    def test_base_path_only_slash(self):
        """Test that base_path of just '/' becomes empty string."""
        app = create_app(base_path="/")
        # Trailing slash is stripped, leaving empty string
        assert app.config["APPLICATION_ROOT"] == ""


@pytest.fixture
def tmp_root_with_sessions(tmp_path):
    """A tiny, self-contained log root with an events+transcript session and
    a transcript-only session -- used to exercise the new transcript routes
    and capability flags without touching any real log directory."""
    root = tmp_path / "logs"

    events_session = root / "proj" / "sessions" / "events-session"
    events_session.mkdir(parents=True)
    (events_session / "events.jsonl").write_text(
        json.dumps(
            {
                "ts": "2025-01-01T00:00:00Z",
                "lvl": "INFO",
                "event": "test:e",
                "session_id": "events-session",
            }
        )
        + "\n"
    )
    (events_session / "transcript.jsonl").write_text(
        json.dumps({"role": "user", "content": "hi"}) + "\n"
    )
    (events_session / "metadata.json").write_text(
        json.dumps({"created": "2025-01-01T00:00:00Z"})
    )

    transcript_only = root / "proj" / "sessions" / "transcript-only-session"
    transcript_only.mkdir(parents=True)
    (transcript_only / "transcript.jsonl").write_text(
        json.dumps({"role": "assistant", "content": "hello"}) + "\n"
    )

    return root


class TestRoots:
    """create_app() root-parameter back-compat and multi-root support."""

    def test_create_app_accepts_scalar_root(self, tmp_path):
        """create_app("/some/dir") still works (back-compat)."""
        app = create_app(str(tmp_path))
        assert app is not None

    def test_create_app_accepts_root_list(self, tmp_path):
        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        root_a.mkdir()
        root_b.mkdir()

        app = create_app([root_a, root_b])
        assert app is not None


class TestTranscriptRoutes:
    """New /api/transcript/* routes (spec section 7.2)."""

    def test_transcript_list_route(self, tmp_root_with_sessions):
        app = create_app([tmp_root_with_sessions])
        client = app.test_client()

        response = client.get("/api/transcript/list?session=events-session")
        data = response.get_json()

        assert response.status_code == 200
        assert data["has_transcript"] is True
        assert len(data["messages"]) == 1
        assert data["messages"][0]["role"] == "user"

    def test_transcript_message_route(self, tmp_root_with_sessions):
        app = create_app([tmp_root_with_sessions])
        client = app.test_client()

        list_response = client.get("/api/transcript/list?session=events-session")
        line = list_response.get_json()["messages"][0]["line"]

        response = client.get(f"/api/transcript/events-session/{line}")
        data = response.get_json()

        assert response.status_code == 200
        assert data["role"] == "user"
        assert data["line"] == line

    def test_transcript_routes_404_unknown_session(self, tmp_root_with_sessions):
        app = create_app([tmp_root_with_sessions])
        client = app.test_client()

        response = client.get("/api/transcript/list?session=does-not-exist")
        assert response.status_code == 404

        response = client.get("/api/transcript/does-not-exist/0")
        assert response.status_code == 404


class TestEventsCapabilities:
    """/api/events/list must report has_events/has_transcript (spec 7.1)."""

    def test_events_list_reports_capabilities(self, tmp_root_with_sessions):
        app = create_app([tmp_root_with_sessions])
        client = app.test_client()

        response = client.get("/api/events/list?session=events-session")
        data = response.get_json()

        assert data["has_events"] is True
        assert data["has_transcript"] is True


class TestSessionMetadataRoute:
    """Regression guard for server.py:476 (AttributeError on events_path=None)."""

    def test_session_metadata_route_with_no_events(self, tmp_root_with_sessions):
        app = create_app([tmp_root_with_sessions])
        client = app.test_client()

        response = client.get("/api/session/transcript-only-session/metadata")

        assert response.status_code == 200
        data = response.get_json()
        assert data["session_id"] == "transcript-only-session"
