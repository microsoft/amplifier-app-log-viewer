"""Flask server with REST API and SSE streaming."""

import json
import time
from pathlib import Path

from flask import Flask
from flask import Response
from flask import jsonify
from flask import render_template
from flask import request
from flask import stream_with_context

from . import log_reader
from . import session_scanner

app = Flask(__name__)

# Global state
_session_tree = None
_projects_dir = None
_last_scan_time = 0
_cache_duration = (
    30  # Seconds before auto-refresh (increased - incremental scans are fast)
)


def create_app(projects_dir: str | Path | None = None) -> Flask:
    """Create and configure the Flask application.

    This is an app factory function for use with service managers.

    Args:
        projects_dir: Path to Amplifier projects directory.
                     Defaults to ~/.amplifier/projects

    Returns:
        Configured Flask application
    """
    if projects_dir is None:
        projects_dir = Path.home() / ".amplifier" / "projects"
    else:
        projects_dir = Path(projects_dir)

    init_session_tree(projects_dir)
    return app


def init_session_tree(projects_dir: Path):
    """Initialize session tree from projects directory."""
    global _projects_dir
    _projects_dir = Path(projects_dir)
    refresh_session_tree()


def refresh_session_tree():
    """Refresh session tree by rescanning projects directory (incremental)."""
    global _session_tree, _last_scan_time
    if _projects_dir is None:
        raise RuntimeError("Projects directory not initialized")

    amplifier_home = _projects_dir.parent

    # Pass existing tree for incremental scanning
    _session_tree = session_scanner.scan_projects(amplifier_home, _session_tree)
    _last_scan_time = time.time()

    # Log refresh with incremental stats
    scan_state = session_scanner.get_scan_state()
    project_count = len(_session_tree.projects)
    session_count = len(_session_tree.session_index)
    print(
        f"[Refresh] {project_count} projects, {session_count} sessions "
        f"(scanned: {scan_state.sessions_scanned}, cached: {scan_state.sessions_cached}, "
        f"took {scan_state.last_scan_duration:.2f}s)"
    )


def ensure_fresh_session_tree():
    """Auto-refresh session tree if cache expired."""
    if _session_tree is None:
        return  # Not initialized yet

    time_since_scan = time.time() - _last_scan_time
    if time_since_scan > _cache_duration:
        refresh_session_tree()


@app.route("/")
def index():
    """Serve main HTML page."""
    return render_template("index.html")


@app.route("/api/status")
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
        }
    )


@app.route("/api/projects")
def get_projects():
    """List all projects with session counts."""
    ensure_fresh_session_tree()

    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    # Include scan status in response
    scan_state = session_scanner.get_scan_state()

    projects_data = [
        {
            "slug": project.slug,
            "path": str(project.path),
            "session_count": len(project.sessions),
        }
        for project in _session_tree.projects
    ]

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


@app.route("/api/refresh", methods=["POST"])
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


@app.route("/api/sessions")
def get_sessions():
    """List sessions for a project."""
    ensure_fresh_session_tree()

    project_slug = request.args.get("project")
    if not project_slug:
        return jsonify({"error": "Missing 'project' parameter"}), 400

    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    # Find project
    project = next((p for p in _session_tree.projects if p.slug == project_slug), None)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Build session data
    sessions_data = [
        {
            "id": session.id,
            "project_slug": session.project_slug,
            "timestamp": session.timestamp,
            "parent_id": session.parent_id,
            "children": [child.id for child in session.children],
            "name": session.metadata.get("name") if session.metadata else None,
            "description": session.metadata.get("description")
            if session.metadata
            else None,
        }
        for session in project.sessions
    ]

    response = jsonify({"sessions": sessions_data})
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/api/events/list")
def get_event_list():
    """Get lightweight event list for a session (no payloads).

    Returns only metadata needed for list display: line number, timestamp,
    event type, level, preview text, and size. Full event data is fetched
    on-demand via /api/events/<session_id>/<line_num>.
    """
    session_id = request.args.get("session")
    if not session_id:
        return jsonify({"error": "Missing 'session' parameter"}), 400

    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    session = session_scanner.get_session(session_id, _session_tree)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    events = log_reader.read_event_list(session.events_path)

    return jsonify({"events": events, "total": len(events)})


@app.route("/api/events/<session_id>/<int:line_num>")
def get_event_detail(session_id: str, line_num: int):
    """Get full event detail by line number.

    Returns the complete event payload for display in the detail panel.
    """
    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    session = session_scanner.get_session(session_id, _session_tree)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    event = log_reader.read_single_event(session.events_path, line_num)
    if not event:
        return jsonify({"error": "Event not found"}), 404

    return jsonify(event)


@app.route("/api/events")
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


@app.route("/api/session/<session_id>/metadata")
def get_session_metadata(session_id: str):
    """Get session metadata."""
    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    session = session_scanner.get_session(session_id, _session_tree)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    return jsonify(
        {
            "session_id": session.id,
            "timestamp": session.timestamp,
            "parent_session_id": session.parent_id,
            "context": session.metadata.get("context", {}),
        }
    )


@app.route("/stream/<session_id>")
def stream_events(session_id: str):
    """
    Server-Sent Events stream for real-time log updates.

    Simplified implementation: polls events.jsonl every 2 seconds for new entries.
    """
    if not _session_tree:
        return jsonify({"error": "Session tree not initialized"}), 500

    session = session_scanner.get_session(session_id, _session_tree)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    def event_stream():
        """Generate SSE events."""
        # Initialize to end of file to avoid re-sending events already loaded via REST API
        try:
            last_position = session.events_path.stat().st_size
        except OSError:
            # If file doesn't exist or can't be read, start from beginning
            last_position = 0

        while True:
            # Check for new events
            new_events, last_position = log_reader.tail_events(
                session.events_path, last_position
            )

            if new_events:
                # Send lightweight events (tail_events already returns lightweight format)
                data = json.dumps(new_events)
                yield f"event: new_events\ndata: {data}\n\n"

            # Poll every 2 seconds
            time.sleep(2)

    return Response(stream_with_context(event_stream()), mimetype="text/event-stream")


def run_server(projects_dir: Path, port: int = 8180):
    """
    Start Flask server with automatic port selection if requested port is in use.

    Args:
        projects_dir: Path to ~/.amplifier/projects directory
        port: Port to run server on (will try next ports if in use)
    """
    print(f"Initializing session tree from {projects_dir}")
    init_session_tree(projects_dir)

    # Show helpful message if no projects found
    if not _session_tree or not _session_tree.projects:
        print("\nNo Amplifier projects found yet.")
        print("   Run Amplifier at least once to create session logs.")
        print(f"   Logs will appear in: {projects_dir}\n")

    # Try requested port, then auto-increment if in use
    max_attempts = 10
    for attempt in range(max_attempts):
        try_port = port + attempt
        try:
            print(f"Starting server on http://localhost:{try_port}")
            print("Press Ctrl+C to stop")
            app.run(host="127.0.0.1", port=try_port, debug=False)
            break
        except OSError as e:
            if "Address already in use" in str(e):
                if attempt < max_attempts - 1:
                    print(f"Port {try_port} in use, trying {try_port + 1}...")
                    continue
                print(f"\nError: Ports {port}-{try_port} all in use.")
                print("Try a different port with: amplifier-log-viewer --port <PORT>")
                raise SystemExit(1) from e
            raise
