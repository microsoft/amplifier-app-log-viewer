"""Tests for server.py functionality."""

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
