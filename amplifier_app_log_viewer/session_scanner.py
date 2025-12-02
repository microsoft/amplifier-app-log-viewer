"""Session discovery and hierarchy building."""

import json
from dataclasses import dataclass
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
    metadata: dict


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


def scan_projects(amplifier_home: Path | None = None) -> SessionTree:
    """
    Scan ~/.amplifier/projects/ and build session tree.

    Args:
        amplifier_home: Path to ~/.amplifier directory (default: ~/.amplifier)

    Returns:
        SessionTree with all projects and sessions (empty if projects dir doesn't exist)
    """
    if amplifier_home is None:
        amplifier_home = Path.home() / ".amplifier"
    projects_dir = amplifier_home / "projects"

    # Return empty tree if projects directory doesn't exist yet
    if not projects_dir.exists():
        return SessionTree(projects=[], session_index={})

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

        # Scan sessions for this project
        project_sessions = []
        for session_dir in sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue

            session_id = session_dir.name
            metadata_path = session_dir / "metadata.json"
            events_path = session_dir / "events.jsonl"
            transcript_path = session_dir / "transcript.jsonl"

            # Parse metadata
            metadata = {}
            parent_id = None
            timestamp = ""

            if metadata_path.exists():
                try:
                    with open(metadata_path, encoding="utf-8") as f:
                        metadata = json.load(f)
                        parent_id = metadata.get("parent_session_id")
                        timestamp = metadata.get("created", "")  # Field is "created", not "timestamp"
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
                metadata=metadata,
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

    # Build parent-child relationships
    for session in session_index.values():
        if session.parent_id and session.parent_id in session_index:
            parent = session_index[session.parent_id]
            parent.children.append(session)

    return SessionTree(projects=projects, session_index=session_index)


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
