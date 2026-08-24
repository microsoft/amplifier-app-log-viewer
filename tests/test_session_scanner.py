"""Tests for session_scanner module."""

import json
import os
from pathlib import Path

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


def test_scan_projects_shim_still_works(mock_amplifier_home):
    """DEPRECATED shim must still work via the existing fixture (backward-compat proof)."""
    tree = session_scanner.scan_projects(mock_amplifier_home)

    assert len(tree.projects) == 2
    assert len(tree.session_index) == 6


# ---------------------------------------------------------------------------
# resolve_roots()
# ---------------------------------------------------------------------------


def test_resolve_roots_defaults(monkeypatch):
    """No args -> the two DEFAULT_ROOTS, in order."""
    monkeypatch.delenv(session_scanner.ROOTS_ENV_VAR, raising=False)

    roots = session_scanner.resolve_roots()

    assert roots == [
        (Path.home() / ".amplifier" / "projects").expanduser().resolve(),
        (Path.home() / ".amplifier-agent" / "state" / "workspaces")
        .expanduser()
        .resolve(),
    ]


def test_resolve_roots_env_var(monkeypatch, tmp_path):
    """os.pathsep-split, ~ expanded, order preserved."""
    root_b = tmp_path / "root-b"
    env_value = os.pathsep.join(["~/env-root-a", str(root_b)])
    monkeypatch.setenv(session_scanner.ROOTS_ENV_VAR, env_value)

    roots = session_scanner.resolve_roots()

    assert roots == [
        (Path.home() / "env-root-a").expanduser().resolve(),
        root_b.resolve(),
    ]


def test_resolve_roots_explicit_wins(monkeypatch, tmp_path):
    """explicit beats env beats defaults; duplicates deduped."""
    monkeypatch.setenv(session_scanner.ROOTS_ENV_VAR, str(tmp_path / "env-root"))
    explicit_root = tmp_path / "explicit-root"

    roots = session_scanner.resolve_roots([explicit_root, explicit_root])

    assert roots == [explicit_root.resolve()]


# ---------------------------------------------------------------------------
# locate_session_files()
# ---------------------------------------------------------------------------


def test_locate_prefers_root_events_over_nested(tmp_path):
    """Decision-1 guard: the SAME preference must never silently flip.

    A session with BOTH a root events.jsonl and a nested
    context-intelligence/events.jsonl must resolve to the root file (and
    merge both metadata.json candidates, root first).
    """
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    root_events = session_dir / "events.jsonl"
    root_events.write_text(json.dumps({"event": "root", "lvl": "INFO"}) + "\n")
    root_meta = session_dir / "metadata.json"
    root_meta.write_text(json.dumps({"created": "2025-01-01T00:00:00Z"}))

    nested_dir = session_dir / "context-intelligence"
    nested_dir.mkdir()
    (nested_dir / "events.jsonl").write_text(json.dumps({"event": "nested"}) + "\n")
    nested_meta = nested_dir / "metadata.json"
    nested_meta.write_text(json.dumps({"started_at": "2025-01-01T00:00:00Z"}))

    files = session_scanner.locate_session_files(session_dir)

    assert files.events_path == root_events
    assert files.metadata_paths == [root_meta, nested_meta]


def test_locate_falls_back_to_nested_events(tmp_path):
    """Only context-intelligence/events.jsonl present -> found; co-located
    metadata is used when no root metadata exists."""
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    nested_dir = session_dir / "context-intelligence"
    nested_dir.mkdir()
    nested_events = nested_dir / "events.jsonl"
    nested_events.write_text(json.dumps({"event": "nested"}) + "\n")
    nested_meta = nested_dir / "metadata.json"
    nested_meta.write_text(json.dumps({"started_at": "2025-01-01T00:00:00Z"}))

    files = session_scanner.locate_session_files(session_dir)

    assert files.events_path == nested_events
    assert files.metadata_paths == [nested_meta]


def test_locate_no_events_is_valid(tmp_path):
    """Transcript-only session -> events_path is None, transcript_path set."""
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    transcript = session_dir / "transcript.jsonl"
    transcript.write_text(json.dumps({"role": "user", "content": "hi"}) + "\n")

    files = session_scanner.locate_session_files(session_dir)

    assert files.events_path is None
    assert files.transcript_path == transcript


def test_locate_ignores_backup_files(tmp_path):
    """events.jsonl.backup present, real file absent -> events_path is None."""
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    (session_dir / "events.jsonl.backup").write_text(
        json.dumps({"event": "old"}) + "\n"
    )

    files = session_scanner.locate_session_files(session_dir)

    assert files.events_path is None


def test_locate_ignores_deep_nesting(tmp_path):
    """a/b/events.jsonl (depth 2) -> not found."""
    session_dir = tmp_path / "session"
    deep_dir = session_dir / "a" / "b"
    deep_dir.mkdir(parents=True)
    (deep_dir / "events.jsonl").write_text(json.dumps({"event": "deep"}) + "\n")

    files = session_scanner.locate_session_files(session_dir)

    assert files.events_path is None


# ---------------------------------------------------------------------------
# load_session_metadata()
# ---------------------------------------------------------------------------


def test_metadata_merge_union_and_priority(tmp_path):
    """Union of fields; root's value wins on any shared key."""
    root_meta = tmp_path / "root_metadata.json"
    root_meta.write_text(json.dumps({"created": "X", "bundle": "B"}))
    nested_meta = tmp_path / "nested_metadata.json"
    nested_meta.write_text(
        json.dumps(
            {"started_at": "Y", "parent_id": "P", "status": None, "bundle": "nested-B"}
        )
    )

    merged = session_scanner.load_session_metadata([root_meta, nested_meta])

    assert merged["created"] == "X"
    assert merged["parent_id"] == "P"
    assert merged["bundle"] == "B"  # root (higher priority) wins on shared key
    assert "status" not in merged  # null in high-priority-adjacent file stays absent


def test_metadata_empty_string_treated_as_absent(tmp_path):
    """New root's `"parent_id": ""` is correctly treated as absent."""
    root = tmp_path / "root"
    session_dir = root / "proj" / "sessions" / "sess-1"
    session_dir.mkdir(parents=True)
    nested = session_dir / "context-intelligence"
    nested.mkdir()
    (nested / "events.jsonl").write_text(json.dumps({"event": "e"}) + "\n")
    (nested / "metadata.json").write_text(
        json.dumps({"parent_id": "", "started_at": "2025-01-01T00:00:00Z"})
    )

    tree = session_scanner.scan_roots([root])
    session = session_scanner.get_session("sess-1", tree)

    assert session is not None
    assert session.parent_id is None


# ---------------------------------------------------------------------------
# scan_roots()
# ---------------------------------------------------------------------------


def test_timestamp_falls_back_to_mtime(tmp_path):
    """No metadata -> non-empty ISO timestamp, timestamp_source == 'mtime'."""
    root = tmp_path / "root"
    session_dir = root / "proj" / "sessions" / "sess-1"
    session_dir.mkdir(parents=True)
    (session_dir / "events.jsonl").touch()

    tree = session_scanner.scan_roots([root])
    session = session_scanner.get_session("sess-1", tree)

    assert session is not None
    assert session.timestamp != ""
    assert session.timestamp_source == "mtime"


def test_scan_roots_merges_colliding_container_names(tmp_path):
    """Same container name in two temp roots -> one Project, sessions from both."""
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"

    for root, session_id in [(root_a, "sess-a"), (root_b, "sess-b")]:
        session_dir = root / "shared-project" / "sessions" / session_id
        session_dir.mkdir(parents=True)
        (session_dir / "events.jsonl").touch()

    tree = session_scanner.scan_roots([root_a, root_b])

    matching = [p for p in tree.projects if p.slug == "shared-project"]
    assert len(matching) == 1
    project = matching[0]
    assert {s.id for s in project.sessions} == {"sess-a", "sess-b"}
    assert project.sources == [
        session_scanner.source_label(root_a),
        session_scanner.source_label(root_b),
    ]


def test_scan_roots_skips_missing_root(tmp_path):
    """One real root + one nonexistent -> no exception, real root scanned."""
    real_root = tmp_path / "real"
    session_dir = real_root / "proj" / "sessions" / "sess-1"
    session_dir.mkdir(parents=True)
    (session_dir / "events.jsonl").touch()

    missing_root = tmp_path / "does-not-exist"

    tree = session_scanner.scan_roots([missing_root, real_root])

    assert len(tree.session_index) == 1
    assert "sess-1" in tree.session_index
