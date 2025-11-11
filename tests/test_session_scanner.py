"""Tests for session_scanner module."""

import json

import pytest
from amplifier_app_log_viewer import session_scanner


@pytest.fixture
def mock_amplifier_home(tmp_path):
    """Create mock ~/.amplifier structure."""
    amplifier_home = tmp_path / ".amplifier"
    projects_dir = amplifier_home / "projects"

    # Create two projects
    for project_slug in ["project-1", "project-2"]:
        project_dir = projects_dir / project_slug
        sessions_dir = project_dir / "sessions"
        sessions_dir.mkdir(parents=True)

        # Create sessions for each project
        for i in range(3):
            session_id = f"session-{project_slug}-{i}"
            session_dir = sessions_dir / session_id
            session_dir.mkdir()

            # Create metadata
            metadata = {
                "session_id": session_id,
                "timestamp": f"2025-11-10T15:30:{i:02d}Z",
                "parent_session_id": None if i == 0 else f"session-{project_slug}-0",
            }

            metadata_file = session_dir / "metadata.json"
            metadata_file.write_text(json.dumps(metadata))

            # Create empty events file
            (session_dir / "events.jsonl").touch()
            (session_dir / "transcript.jsonl").touch()

    return amplifier_home


def test_scan_projects(mock_amplifier_home):
    """Test scanning projects directory."""
    tree = session_scanner.scan_projects(mock_amplifier_home)

    assert len(tree.projects) == 2
    assert tree.projects[0].slug in ["project-1", "project-2"]
    assert len(tree.session_index) == 6  # 3 sessions per project


def test_get_session(mock_amplifier_home):
    """Test getting a specific session."""
    tree = session_scanner.scan_projects(mock_amplifier_home)

    session = session_scanner.get_session("session-project-1-0", tree)
    assert session is not None
    assert session.id == "session-project-1-0"
    assert session.project_slug == "project-1"


def test_get_session_not_found(mock_amplifier_home):
    """Test getting non-existent session."""
    tree = session_scanner.scan_projects(mock_amplifier_home)

    session = session_scanner.get_session("nonexistent", tree)
    assert session is None


def test_session_hierarchy(mock_amplifier_home):
    """Test building session hierarchy."""
    tree = session_scanner.scan_projects(mock_amplifier_home)

    # Get child session
    hierarchy = session_scanner.get_session_hierarchy("session-project-1-1", tree)

    # Should have parent first, then child
    assert len(hierarchy) == 2
    assert hierarchy[0].id == "session-project-1-0"  # Parent
    assert hierarchy[1].id == "session-project-1-1"  # Child


def test_scan_projects_missing_directory(tmp_path):
    """Test scanning when projects directory doesn't exist returns empty tree."""
    tree = session_scanner.scan_projects(tmp_path / "nonexistent")
    assert len(tree.projects) == 0
    assert len(tree.session_index) == 0


def test_session_children_populated(mock_amplifier_home):
    """Test that parent sessions have children populated."""
    tree = session_scanner.scan_projects(mock_amplifier_home)

    parent = session_scanner.get_session("session-project-1-0", tree)
    assert parent is not None
    assert len(parent.children) == 2  # Sessions 1 and 2 are children
