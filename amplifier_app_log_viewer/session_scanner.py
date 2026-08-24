"""Session discovery and hierarchy building with incremental scanning.

Supports scanning multiple log roots (e.g. the historical
``~/.amplifier/projects`` layout alongside the newer
``~/.amplifier-agent/state/workspaces`` layout). See ``resolve_roots()`` and
``scan_roots()``.
"""

import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Root resolution
# ---------------------------------------------------------------------------

DEFAULT_ROOTS: tuple[Path, ...] = (
    Path.home() / ".amplifier" / "projects",
    Path.home() / ".amplifier-agent" / "state" / "workspaces",
)

ROOTS_ENV_VAR = "AMPLIFIER_LOG_ROOTS"

# Events nesting is never observed deeper than one subdirectory (measured).
MAX_NESTED_DEPTH = 1


def source_label(root: Path) -> str:
    """Stable per-root label, used for Session.source / Project.sources.

    'amplifier' for ~/.amplifier/projects, 'agent' for
    ~/.amplifier-agent/state/workspaces, otherwise the root directory's own
    name. Purely cosmetic/diagnostic -- derived from the root path, NOT from
    file layout. Layout is handled entirely by locate_session_files() and
    must never be branched on by source label.
    """
    if root == DEFAULT_ROOTS[0]:
        return "amplifier"
    if root == DEFAULT_ROOTS[1]:
        return "agent"
    return root.name


def resolve_roots(explicit: Sequence[str | Path] | None = None) -> list[Path]:
    """Resolve the ordered list of log roots to scan.

    Precedence (first non-empty wins):
      1. `explicit`            -- CLI --root/--projects-dir, or create_app(roots=...)
      2. $AMPLIFIER_LOG_ROOTS  -- os.pathsep-separated list
      3. DEFAULT_ROOTS

    Every path is `.expanduser().resolve()`-normalized (see IMPLEMENTATION_PHILOSOPHY
    "User-Supplied Paths"). Duplicates are dropped, first occurrence wins, order preserved.
    Non-existent roots are NOT filtered out -- scan_roots() skips them silently, so a
    machine with only one root shows one root's worth of projects and no error.

    Returns: non-empty list[Path]
    """
    candidates: Sequence[str | Path]
    if explicit:
        candidates = explicit
    else:
        env_value = os.environ.get(ROOTS_ENV_VAR)
        if env_value:
            candidates = env_value.split(os.pathsep)
        else:
            candidates = DEFAULT_ROOTS

    resolved: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        normalized = Path(candidate).expanduser().resolve()
        if normalized not in seen:
            seen.add(normalized)
            resolved.append(normalized)

    return resolved


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SessionFiles:
    """Resolved on-disk locations for one session directory."""

    events_path: Path | None  # None when the session has no events.jsonl anywhere
    metadata_paths: list[Path]  # highest-priority first; may be empty
    transcript_path: Path | None  # always <session_dir>/transcript.jsonl, or None


@dataclass
class Session:
    """Session metadata."""

    id: str
    project_slug: str
    timestamp: str
    parent_id: str | None
    children: list["Session"]
    events_path: Path | None
    transcript_path: Path | None
    metadata_path: Path | None = None  # highest-priority metadata.json
    source: str = ""  # source_label() of its root
    timestamp_source: str = ""  # "metadata" | "mtime" | ""
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
    sources: list[str] = field(
        default_factory=list
    )  # e.g. ["amplifier"] or ["amplifier","agent"]


@dataclass
class SessionTree:
    """Complete session tree."""

    projects: list[Project]
    session_index: dict[str, Session]


@dataclass
class ScanState:
    """State for incremental scanning."""

    # mtime tracking for incremental updates
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


# ---------------------------------------------------------------------------
# Per-session file location
# ---------------------------------------------------------------------------


def locate_session_files(session_dir: Path) -> SessionFiles:
    """Locate the events / metadata / transcript files for one session directory.

    One rule for every layout -- no format detection, no name matching.

    events.jsonl:
      Candidates are <session_dir>/events.jsonl (depth 0) and
      <session_dir>/*/events.jsonl (depth 1). The SHALLOWEST match wins;
      ties at depth 1 are broken by sorted subdirectory name.
      Rationale: measured, the depth-0 file is a strict superset of the depth-1
      file in the old root (extra fields AND extra lines). Nested is a fallback,
      not a preference.

    metadata.json:
      Returns up to two paths, highest priority first:
        [ <session_dir>/metadata.json,  <chosen-subdir>/metadata.json ]
      where <chosen-subdir> is the directory of the chosen events file when that
      is nested, else the first immediate subdirectory that contains a
      metadata.json. Both are merged by load_session_metadata().

    transcript.jsonl:
      Always <session_dir>/transcript.jsonl. Never searched deeper.

    Exact-filename matching means `metadata.json.backup` and
    `transcript.jsonl.backup` are skipped for free -- no suffix blacklist needed.

    Cost: one os.scandir(session_dir) plus two Path.exists() per immediate
    subdirectory. Subdirectories are never listed (so a large audits/ costs
    two stats, not a directory read).

    Never raises: OSError during the scan yields whatever was found so far.
    """
    root_events = session_dir / "events.jsonl"
    root_meta = session_dir / "metadata.json"
    transcript = session_dir / "transcript.jsonl"

    nested_events: Path | None = None
    nested_meta: Path | None = None

    try:
        subdirs = sorted(
            (
                Path(entry.path)
                for entry in os.scandir(session_dir)
                if entry.is_dir(follow_symlinks=False)
            ),
            key=lambda p: p.name,
        )
    except OSError:
        subdirs = []

    for subdir in subdirs:
        if nested_events is None:
            candidate = subdir / "events.jsonl"
            if candidate.exists():
                nested_events = candidate
        if nested_meta is None:
            candidate = subdir / "metadata.json"
            if candidate.exists():
                nested_meta = candidate
        if nested_events is not None and nested_meta is not None:
            break

    events_path = root_events if root_events.exists() else nested_events

    metadata_paths: list[Path] = []
    if root_meta.exists():
        metadata_paths.append(root_meta)

    if events_path is not None and events_path != root_events:
        # events_path is nested -- co-located metadata is the fallback source.
        candidate = events_path.parent / "metadata.json"
        if candidate.exists() and candidate not in metadata_paths:
            metadata_paths.append(candidate)
    elif nested_meta is not None and nested_meta not in metadata_paths:
        metadata_paths.append(nested_meta)

    transcript_path = transcript if transcript.exists() else None

    return SessionFiles(
        events_path=events_path,
        metadata_paths=metadata_paths,
        transcript_path=transcript_path,
    )


def load_session_metadata(paths: Sequence[Path]) -> dict:
    """Merge metadata.json candidates into one dict. `paths` is highest-priority first.

    Merge, don't choose: the old root's session-level metadata.json carries
    created/bundle/model/turn_count while its context-intelligence/metadata.json
    carries started_at/parent_id/status/ended_at. The union is strictly better
    than either file alone, and the new root's near-empty {"last_turn": ...}
    contributes nothing without needing a special case.

    Only non-empty values are merged (skip None and ""), so a null `status` in a
    high-priority file cannot mask a real one in a lower-priority file -- and the
    new root's "parent_id": "" is correctly treated as absent.

    Unreadable / malformed / non-dict files are skipped silently.
    """
    merged: dict = {}
    for path in reversed(list(paths)):
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        merged.update({k: v for k, v in raw.items() if v not in (None, "")})
    return merged


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def scan_roots(
    roots: Sequence[Path],
    existing_tree: SessionTree | None = None,
    max_age_days: int | None = None,
) -> SessionTree:
    """
    Scan every root in `roots` and build a merged session tree.

    Uses incremental scanning - only re-reads metadata for sessions
    whose directories have been modified since last scan.

    Args:
        roots: Ordered list of log root directories to scan (see resolve_roots()).
        existing_tree: Previous tree to update incrementally (optional)
        max_age_days: Only include sessions whose directory mtime is within
                      this many days. None (default) scans all sessions.

    Returns:
        SessionTree with all projects and sessions (empty if no root exists)
    """
    _scan_state.is_scanning = True
    _scan_state.sessions_scanned = 0
    _scan_state.sessions_cached = 0
    scan_start = time.time()

    try:
        age_cutoff = (
            time.time() - (max_age_days * 86400) if max_age_days is not None else None
        )

        # Reuse existing tree's index by reference (read-only lookup, no copy needed)
        existing_sessions: dict[str, Session] = (
            existing_tree.session_index if existing_tree else {}
        )

        by_slug: dict[str, Project] = {}
        session_index: dict[str, Session] = {}

        for root in roots:
            if not root.is_dir():
                continue

            source = source_label(root)

            for container_dir in sorted(root.iterdir()):
                if not container_dir.is_dir():
                    continue

                container_slug = container_dir.name
                sessions_dir = container_dir / "sessions"
                if not sessions_dir.exists():
                    continue

                project = by_slug.get(container_slug)
                if project is None:
                    project = Project(
                        slug=container_slug, path=container_dir, sessions=[], sources=[]
                    )
                    by_slug[container_slug] = project
                if source not in project.sources:
                    project.sources.append(source)

                for session_dir in sessions_dir.iterdir():
                    if not session_dir.is_dir():
                        continue

                    session_id = session_dir.name

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
                        session.children = []
                        project.sessions.append(session)
                        session_index[session_id] = session
                        _scan_state.sessions_cached += 1
                        continue

                    # Need to read metadata for this session
                    _scan_state.sessions_scanned += 1
                    _scan_state.session_mtimes[session_id] = session_mtime

                    files = locate_session_files(session_dir)
                    raw = load_session_metadata(files.metadata_paths)

                    timestamp = raw.get("created") or raw.get("started_at") or ""
                    timestamp_source = "metadata" if timestamp else ""
                    if not timestamp:
                        # Decision 3: mtime fallback so date filters can see the session at all.
                        timestamp = datetime.fromtimestamp(
                            session_mtime, tz=timezone.utc
                        ).isoformat()
                        timestamp_source = "mtime"

                    parent_id = (
                        raw.get("parent_session_id") or raw.get("parent_id") or None
                    )
                    name = raw.get("name")
                    description = raw.get("description")
                    status = raw.get("status")
                    bundle = raw.get("bundle")
                    labels = raw.get("labels")

                    session = Session(
                        id=session_id,
                        project_slug=container_slug,
                        timestamp=timestamp,
                        parent_id=parent_id,
                        children=[],
                        events_path=files.events_path,
                        transcript_path=files.transcript_path,
                        metadata_path=files.metadata_paths[0]
                        if files.metadata_paths
                        else None,
                        source=source,
                        timestamp_source=timestamp_source,
                        name=name,
                        description=description,
                        status=status,
                        bundle=bundle,
                        labels=labels,
                    )

                    project.sessions.append(session)
                    session_index[session_id] = session

        # Sort sessions by session ID within each (possibly merged) project
        for project in by_slug.values():
            project.sessions.sort(key=lambda s: s.id)

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

        projects = sorted(by_slug.values(), key=lambda p: p.slug)

        return SessionTree(projects=projects, session_index=session_index)

    finally:
        _scan_state.is_scanning = False
        _scan_state.last_scan_duration = time.time() - scan_start


def scan_projects(
    amplifier_home: Path | None = None,
    existing_tree: SessionTree | None = None,
    max_age_days: int | None = None,
) -> SessionTree:
    """DEPRECATED: single-root wrapper preserving the historical
    `<amplifier_home>/projects` convention. Prefer scan_roots().
    """
    # DEFAULT_ROOTS[0] is `<home>/.amplifier/projects`; its parent is the
    # historical `~/.amplifier` -- reused here rather than re-deriving the
    # same default a second time.
    home = Path(amplifier_home) if amplifier_home else DEFAULT_ROOTS[0].parent
    return scan_roots(
        [Path(home).expanduser() / "projects"], existing_tree, max_age_days
    )


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
