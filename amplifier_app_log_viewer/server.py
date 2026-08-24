"""Flask server with REST API and SSE streaming."""

import threading
import time
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, Flask, current_app, jsonify, render_template, request

from . import log_reader, session_scanner
from .auth import AuthConfig, install_auth, resolve_auth_config


def parse_date_filter(since: str | None) -> datetime | None:
    """Parse date filter parameter into a datetime cutoff.

    Args:
        since: Either an ISO date string or a relative period like '2d', '7d', '30d'

    Returns:
        datetime cutoff (UTC) or None if no filter
    """
    if not since:
        return None

    # Handle relative periods
    if since.endswith("d"):
        try:
            days = int(since[:-1])
            return datetime.now(timezone.utc) - timedelta(days=days)
        except ValueError:
            pass

    # Handle ISO date strings
    try:
        # Try parsing as ISO format
        dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass

    return None


def session_in_date_range(
    session, start: datetime | None, end: datetime | None = None
) -> bool:
    """Check if a session's timestamp is within the date range.

    Args:
        session: Session object with timestamp attribute
        start: Start of range (inclusive), or None for no lower bound
        end: End of range (inclusive), or None for no upper bound
    """
    if start is None and end is None:
        return True

    if not session.timestamp:
        # Sessions without timestamps are excluded when filtering
        return False

    try:
        session_dt = datetime.fromisoformat(session.timestamp.replace("Z", "+00:00"))
        if session_dt.tzinfo is None:
            session_dt = session_dt.replace(tzinfo=timezone.utc)

        if start and session_dt < start:
            return False
        if end and session_dt > end:
            return False
        return True
    except (ValueError, AttributeError):
        return False


bp = Blueprint("app", __name__)

# Global state
_session_tree = None
_roots: list[Path] = []
_last_scan_time = 0
_cache_duration = (
    30  # Seconds before auto-refresh (increased - incremental scans are fast)
)
_refresh_lock = threading.Lock()


def inject_base_path():
    """Make BASE_PATH available in all templates."""
    return {"BASE_PATH": current_app.config.get("APPLICATION_ROOT", "")}


def create_app(
    roots: str | Path | Sequence[str | Path] | None = None,
    base_path: str = "",
    auth: AuthConfig | None = None,
) -> Flask:
    """Create and configure the Flask application.

    This is an app factory function for use with service managers.

    Args:
        roots: One or more log roots to scan. A single string/Path is
               accepted for back-compat and wrapped into a 1-list.
               Defaults (via session_scanner.resolve_roots()) to
               $AMPLIFIER_LOG_ROOTS, or ~/.amplifier/projects and
               ~/.amplifier-agent/state/workspaces.
        base_path: Base path for serving (e.g., '/amplifier/logs').
                   Defaults to '' (root path).
        auth: Auth configuration. None (default) resolves from CLI-less
              defaults + environment. Auth is always enforced; there is no
              way to disable it.

    Returns:
        Configured Flask application
    """
    normalized_base_path = base_path or ""

    if roots is None:
        root_list: Sequence[str | Path] | None = None
    elif isinstance(roots, (str, Path)):
        root_list = [roots]
    else:
        root_list = list(roots)

    # Set base path (always reset global state, even if empty)
    if normalized_base_path:
        # Validate base path format
        if not normalized_base_path.startswith("/"):
            raise ValueError(
                f"base_path must start with '/': {normalized_base_path!r}. "
                f"Did you mean '/{normalized_base_path}'?"
            )

        # Prevent path traversal attempts
        if ".." in normalized_base_path:
            raise ValueError(
                f"base_path cannot contain '..' for security reasons: "
                f"{normalized_base_path!r}"
            )

        # Remove trailing slash for consistency
        normalized_base_path = normalized_base_path.rstrip("/")

    app = Flask(__name__)
    app.config["APPLICATION_ROOT"] = normalized_base_path
    app.context_processor(inject_base_path)
    app.register_blueprint(bp, url_prefix=normalized_base_path or None)
    install_auth(app, auth or resolve_auth_config(), normalized_base_path)

    init_session_tree(root_list)
    _start_background_refresh()
    return app


def init_session_tree(roots: Sequence[str | Path] | None):
    """Initialize session tree from the given roots (or resolved defaults)."""
    global _roots
    _roots = session_scanner.resolve_roots(roots)
    refresh_session_tree()


def refresh_session_tree():
    """Refresh session tree by rescanning all log roots (incremental).

    Thread-safe: uses _refresh_lock to prevent concurrent scans and
    protect _session_tree from data races.
    """
    global _session_tree, _last_scan_time
    if not _roots:
        raise RuntimeError("Log roots not initialized")

    with _refresh_lock:
        # Pass existing tree for incremental scanning
        _session_tree = session_scanner.scan_roots(_roots, _session_tree)
        _last_scan_time = time.time()

        # Log refresh with incremental stats
        scan_state = session_scanner.get_scan_state()
        project_count = len(_session_tree.projects)
        session_count = len(_session_tree.session_index)
        print(
            f"[Refresh] {len(_roots)} roots, {project_count} projects, {session_count} sessions "
            f"(scanned: {scan_state.sessions_scanned}, cached: {scan_state.sessions_cached}, "
            f"took {scan_state.last_scan_duration:.2f}s)"
        )


_refresh_thread = None


def _start_background_refresh():
    """Start a daemon thread that refreshes the session tree periodically.

    This replaces the old ensure_fresh_session_tree() approach which ran
    the scan inline on request threads, blocking them for 1-5 seconds.
    Now requests always read from the cached tree with zero I/O cost.

    Guarded against multiple calls (e.g. tests creating multiple apps,
    or Flask dev reload) — only one thread runs at a time.
    """
    global _refresh_thread
    if _refresh_thread is not None and _refresh_thread.is_alive():
        return

    def worker():
        while True:
            time.sleep(_cache_duration)
            try:
                refresh_session_tree()
            except Exception as e:
                print(f"[Refresh] Error: {e}")

    _refresh_thread = threading.Thread(
        target=worker, daemon=True, name="session-tree-refresh"
    )
    _refresh_thread.start()


@bp.route("/", strict_slashes=False)
def index():
    """Serve main HTML page."""
    return render_template("index.html")


@bp.route("/api/status")
def get_status():
    """Get server and scan status."""
    scan_state = session_scanner.get_scan_state()

    return jsonify(
        {
            "is_scanning": scan_state.is_scanning,
            "last_scan_duration": scan_state.last_scan_duration,
            "sessions_scanned": scan_state.sessions_scanned,
            "sessions_cached": scan_state.sessions_cached,
            "project_count": len(_session_tree.projects) if _session_tree else 0,
            "session_count": len(_session_tree.session_index) if _session_tree else 0,
            "cache_age": time.time() - _last_scan_time if _last_scan_time else 0,
            "cache_duration": _cache_duration,
            "roots": [str(r) for r in _roots],
        }
    )


@bp.route("/api/projects")
def get_projects():
    """List all projects with session counts.

    Query params:
        since: Start date - either ISO date or relative like '2d', '7d', '30d'
        until: End date - ISO date string (for custom date ranges)
    """
    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    # Parse date filters
    since = request.args.get("since")
    until = request.args.get("until")
    start_date = parse_date_filter(since)
    end_date = parse_date_filter(until)

    # Include scan status in response
    scan_state = session_scanner.get_scan_state()

    # Build projects list with filtered session counts
    projects_data = []
    for project in _session_tree.projects:
        # Count sessions matching date filter
        if start_date or end_date:
            matching_sessions = [
                s
                for s in project.sessions
                if session_in_date_range(s, start_date, end_date)
            ]
            session_count = len(matching_sessions)
        else:
            session_count = len(project.sessions)

        # Only include projects with sessions in the date range
        if session_count > 0:
            projects_data.append(
                {
                    "slug": project.slug,
                    "path": str(project.path),
                    "sources": project.sources,
                    "session_count": session_count,
                }
            )

    response = jsonify(
        {
            "projects": projects_data,
            "is_scanning": scan_state.is_scanning,
        }
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@bp.route("/api/refresh", methods=["POST"])
def refresh():
    """Manually refresh the session tree."""
    try:
        refresh_session_tree()
        scan_state = session_scanner.get_scan_state()
        return jsonify(
            {
                "status": "success",
                "message": "Session tree refreshed",
                "sessions_scanned": scan_state.sessions_scanned,
                "sessions_cached": scan_state.sessions_cached,
                "duration": scan_state.last_scan_duration,
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@bp.route("/api/sessions")
def get_sessions():
    """List sessions for a project.

    Query params:
        project: Project slug (required)
        since: Start date - either ISO date or relative like '2d', '7d', '30d'
        until: End date - ISO date string (for custom date ranges)
    """
    project_slug = request.args.get("project")
    if not project_slug:
        return jsonify({"error": "Missing 'project' parameter"}), 400

    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    # Parse date filters
    since = request.args.get("since")
    until = request.args.get("until")
    start_date = parse_date_filter(since)
    end_date = parse_date_filter(until)

    # Find project
    project = next((p for p in _session_tree.projects if p.slug == project_slug), None)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Filter sessions by date and build response data
    sessions_data = [
        {
            "id": session.id,
            "project_slug": session.project_slug,
            "timestamp": session.timestamp,
            "parent_id": session.parent_id,
            "children": [child.id for child in session.children],
            "name": session.name,
            "description": session.description,
            "source": session.source,
            "timestamp_source": session.timestamp_source,
            "has_events": session.events_path is not None,
            "has_transcript": session.transcript_path is not None,
        }
        for session in project.sessions
        if session_in_date_range(session, start_date, end_date)
    ]

    response = jsonify({"sessions": sessions_data})
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@bp.route("/api/events/list")
def get_event_list():
    """Get lightweight event list for a session (no payloads).

    Returns only metadata needed for list display: line number, timestamp,
    event type, level, preview text, and size. Full event data is fetched
    on-demand via /api/events/<session_id>/<line_num>.

    Query params:
        session: Session ID (required)
        offset: Line number to start from (default 0)
        limit: Max events to return (default 200)
    """
    session_id = request.args.get("session")
    if not session_id:
        return jsonify({"error": "Missing 'session' parameter"}), 400

    offset = request.args.get("offset", 0, type=int)
    limit = request.args.get("limit", 200, type=int)

    # Validate parameters
    if offset < 0 or limit < 1 or limit > 5000:
        return jsonify({"error": "Invalid offset or limit"}), 400

    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    session = session_scanner.get_session(session_id, _session_tree)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    result = log_reader.read_event_list(session.events_path, offset, limit)
    result["has_events"] = session.events_path is not None
    result["has_transcript"] = session.transcript_path is not None

    return jsonify(result)


@bp.route("/api/events/<session_id>/<int:line_num>")
def get_event_detail(session_id: str, line_num: int):
    """Get full event detail by line number.

    Returns the complete event payload for display in the detail panel.
    """
    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    session = session_scanner.get_session(session_id, _session_tree)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    byte_offset = request.args.get("byte_offset", None, type=int)
    event = log_reader.read_single_event(session.events_path, line_num, byte_offset)
    if not event:
        return jsonify({"error": "Event not found"}), 404

    return jsonify(event)


@bp.route("/api/events")
def get_events():
    """Get paginated events for a session (DEPRECATED).

    Use /api/events/list for the event list and /api/events/<session>/<line>
    for full event details instead.
    """
    session_id = request.args.get("session")
    if not session_id:
        return jsonify({"error": "Missing 'session' parameter"}), 400

    offset = request.args.get("offset", 0, type=int)
    limit = request.args.get("limit", 100, type=int)

    # Validate parameters
    if offset < 0 or limit < 1 or limit > 5000:
        return jsonify({"error": "Invalid offset or limit"}), 400

    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    # Get session
    session = session_scanner.get_session(session_id, _session_tree)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    # Read events (deprecated path - kept for compatibility)
    events, total = log_reader.read_events(session.events_path, offset, limit)

    return jsonify(
        {
            "events": events,
            "total": total,
            "has_more": offset + len(events) < total,
            "next_offset": offset + len(events),
        }
    )


@bp.route("/api/session/<session_id>/metadata")
def get_session_metadata(session_id: str):
    """Get session metadata."""
    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    session = session_scanner.get_session(session_id, _session_tree)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    # Read metadata on demand (not stored in memory), via the same merge the
    # scanner used to build the session -- keeps this endpoint and the tree
    # in agreement, and tolerates events_path being None (server.py:476 used
    # to raise AttributeError here for events-less sessions).
    raw = session_scanner.load_session_metadata(
        [session.metadata_path] if session.metadata_path else []
    )

    return jsonify(
        {
            "session_id": session.id,
            "timestamp": session.timestamp,
            "timestamp_source": session.timestamp_source,
            "parent_session_id": session.parent_id,
            "source": session.source,
            "context": raw.get("context", {}),  # preserved for backward compat
            "metadata": raw,  # full merged metadata
        }
    )


@bp.route("/api/transcript/list")
def get_transcript_list():
    """Paginated transcript messages for a session.

    Query params: session (required), offset (default 0), limit (default 50, max 500)
    Validation mirrors /api/events/list exactly: 400 on bad params, 400 on missing
    session, 500 when the tree is uninitialized, 404 on unknown session.
    Adds "has_transcript" to the response.
    """
    session_id = request.args.get("session")
    if not session_id:
        return jsonify({"error": "Missing 'session' parameter"}), 400

    offset = request.args.get("offset", 0, type=int)
    limit = request.args.get("limit", 50, type=int)

    if offset < 0 or limit < 1 or limit > 500:
        return jsonify({"error": "Invalid offset or limit"}), 400

    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    session = session_scanner.get_session(session_id, _session_tree)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    result = log_reader.read_transcript(session.transcript_path, offset, limit)
    result["has_transcript"] = session.transcript_path is not None

    response = jsonify(result)
    response.headers["Cache-Control"] = "no-cache"
    return response


@bp.route("/api/transcript/<session_id>/<int:line_num>")
def get_transcript_message(session_id: str, line_num: int):
    """Full untruncated transcript message by line number.

    Accepts optional ?byte_offset= for O(1) seek, exactly like
    /api/events/<session_id>/<line_num>. Delegates to
    log_reader.read_single_event(session.transcript_path, line_num, byte_offset).
    404 when the session or line is absent.
    """
    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    session = session_scanner.get_session(session_id, _session_tree)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    byte_offset = request.args.get("byte_offset", None, type=int)
    message = log_reader.read_single_event(
        session.transcript_path, line_num, byte_offset
    )
    if not message:
        return jsonify({"error": "Message not found"}), 404

    response = jsonify(message)
    response.headers["Cache-Control"] = "no-cache"
    return response


@bp.route("/api/events/since")
def get_events_since():
    """Poll for new events since a given byte position.

    Returns immediately with any new events, releasing the thread.
    This replaces the old SSE /stream/<session_id> endpoint which held
    a thread permanently per connection.

    Query params:
        session: Session ID (required)
        position: Byte offset to read from (default 0)
        line_count: Current line count for numbering (default 0)
    """
    session_id = request.args.get("session")
    if not session_id:
        return jsonify({"error": "Missing 'session' parameter"}), 400

    last_position = request.args.get("position", 0, type=int)
    last_line_count = request.args.get("line_count", 0, type=int)

    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    session = session_scanner.get_session(session_id, _session_tree)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    new_events, new_position, new_line_count = log_reader.tail_events(
        session.events_path, last_position, last_line_count
    )

    return jsonify(
        {
            "events": new_events,
            "position": new_position,
            "line_count": new_line_count,
        }
    )
