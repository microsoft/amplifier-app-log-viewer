"""Session discovery and hierarchy building with incremental scanning."""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Session:
    """Session metadata."""

    id: str
    project_slug: str
    timestamp: str
    parent_id: str | None
    children: list["Session"]
    events_path: Path
    transcript_path: Path
    name: str | None = None
    description: str | None = None
    status: str | None = None
    bundle: str | None = None
    labels: list | None = None


@dataclass
class Project:
    """Project metadata."""

    slug: str
    path: Path
    sessions: list[Session]


@dataclass
class SessionTree:
    """Complete session tree."""

    projects: list[Project]
    session_index: dict[str, Session]


@dataclass
class ScanState:
    """State for incremental scanning."""

    # mtime tracking for incremental updates
    project_mtimes: dict[str, float] = field(default_factory=dict)
    session_mtimes: dict[str, float] = field(default_factory=dict)

    # Scan status
    is_scanning: bool = False
    last_scan_duration: float = 0.0
    sessions_scanned: int = 0
    sessions_cached: int = 0


# Global scan state for incremental updates
_scan_state = ScanState()


def get_scan_state() -> ScanState:
    """Get the current scan state for status reporting."""
    return _scan_state


def scan_projects(
    amplifier_home: Path | None = None,
    existing_tree: SessionTree | None = None,
    max_age_days: int | None = None,
) -> SessionTree:
    """
    Scan ~/.amplifier/projects/ and build session tree.

    Uses incremental scanning - only re-reads metadata for sessions
    whose directories have been modified since last scan.

    Args:
        amplifier_home: Path to ~/.amplifier directory (default: ~/.amplifier)
        existing_tree: Previous tree to update incrementally (optional)
        max_age_days: Only include sessions whose directory mtime is within
                      this many days. None (default) scans all sessions.

    Returns:
        SessionTree with all projects and sessions (empty if projects dir doesn't exist)
    """
    global _scan_state

    _scan_state.is_scanning = True
    _scan_state.sessions_scanned = 0
    _scan_state.sessions_cached = 0
    scan_start = time.time()

    try:
        if amplifier_home is None:
            amplifier_home = Path.home() / ".amplifier"
        projects_dir = amplifier_home / "projects"

        # Return empty tree if projects directory doesn't exist yet
        if not projects_dir.exists():
            return SessionTree(projects=[], session_index={})

        # Compute age cutoff for recency filtering
        age_cutoff = (
            time.time() - (max_age_days * 86400) if max_age_days is not None else None
        )

        # Reuse existing tree's index by reference (read-only lookup, no copy needed)
        existing_sessions: dict[str, Session] = (
            existing_tree.session_index if existing_tree else {}
        )

        projects = []
        session_index = {}

        # Scan each project directory
        for project_dir in sorted(projects_dir.iterdir()):
            if not project_dir.is_dir():
                continue

            project_slug = project_dir.name
            sessions_dir = project_dir / "sessions"

            if not sessions_dir.exists():
                continue

            # Check if project directory has been modified
            try:
                project_mtime = sessions_dir.stat().st_mtime
            except OSError:
                continue

            project_sessions = []

            # Scan sessions for this project
            for session_dir in sessions_dir.iterdir():
                if not session_dir.is_dir():
                    continue

                session_id = session_dir.name

                # Check if we can reuse existing session data
                try:
                    session_mtime = session_dir.stat().st_mtime
                except OSError:
                    continue

                # Skip sessions older than max_age_days
                if age_cutoff is not None and session_mtime < age_cutoff:
                    continue

                cached_mtime = _scan_state.session_mtimes.get(session_id)

                # Reuse existing session if directory hasn't changed
                if (
                    cached_mtime is not None
                    and session_mtime <= cached_mtime
                    and session_id in existing_sessions
                ):
                    session = existing_sessions[session_id]
                    # Reset children (will rebuild relationships later)
                    session.children = []
                    project_sessions.append(session)
                    session_index[session_id] = session
                    _scan_state.sessions_cached += 1
                    continue

                # Need to read metadata for this session
                _scan_state.sessions_scanned += 1
                _scan_state.session_mtimes[session_id] = session_mtime

                metadata_path = session_dir / "metadata.json"
                events_path = session_dir / "events.jsonl"
                transcript_path = session_dir / "transcript.jsonl"

                # Parse metadata — extract only the fields we need
                parent_id = None
                timestamp = ""
                name = None
                description = None
                status = None
                bundle = None
                labels = None

                if metadata_path.exists():
                    try:
                        with open(metadata_path, encoding="utf-8") as f:
                            raw = json.load(f)
                            parent_id = raw.get("parent_session_id")
                            timestamp = raw.get("created", "")
                            name = raw.get("name")
                            description = raw.get("description")
                            status = raw.get("status")
                            bundle = raw.get("bundle")
                            labels = raw.get("labels")
                    except (json.JSONDecodeError, OSError):
                        # Use fallback values
                        pass

                # Create session object
                session = Session(
                    id=session_id,
                    project_slug=project_slug,
                    timestamp=timestamp,
                    parent_id=parent_id,
                    children=[],
                    events_path=events_path,
                    transcript_path=transcript_path,
                    name=name,
                    description=description,
                    status=status,
                    bundle=bundle,
                    labels=labels,
                )

                project_sessions.append(session)
                session_index[session_id] = session

            # Sort sessions by session ID (client can re-sort as needed)
            project_sessions.sort(key=lambda s: s.id)

            # Create project object
            project = Project(
                slug=project_slug,
                path=project_dir,
                sessions=project_sessions,
            )
            projects.append(project)

            # Update project mtime
            _scan_state.project_mtimes[project_slug] = project_mtime

        # Build parent-child relationships
        for session in session_index.values():
            if session.parent_id and session.parent_id in session_index:
                parent = session_index[session.parent_id]
                parent.children.append(session)

        # Prune stale entries from scan state (directories that no longer exist)
        live_session_ids = set(session_index.keys())
        for sid in list(_scan_state.session_mtimes):
            if sid not in live_session_ids:
                del _scan_state.session_mtimes[sid]
        live_project_slugs = {p.slug for p in projects}
        for slug in list(_scan_state.project_mtimes):
            if slug not in live_project_slugs:
                del _scan_state.project_mtimes[slug]

        return SessionTree(projects=projects, session_index=session_index)

    finally:
        _scan_state.is_scanning = False
        _scan_state.last_scan_duration = time.time() - scan_start


def get_session(session_id: str, tree: SessionTree) -> Session | None:
    """Fast lookup via session_index."""
    return tree.session_index.get(session_id)


def get_session_hierarchy(session_id: str, tree: SessionTree) -> list[Session]:
    """
    Get session ancestry: [root, ..., parent, session].

    Used for breadcrumb navigation.

    Args:
        session_id: Session UUID
        tree: SessionTree

    Returns:
        List of sessions from root to target session
    """
    session = get_session(session_id, tree)
    if not session:
        return []

    hierarchy = [session]

    # Walk up to root
    current = session
    while current.parent_id:
        parent = get_session(current.parent_id, tree)
        if not parent:
            break
        hierarchy.insert(0, parent)
        current = parent

    return hierarchy
