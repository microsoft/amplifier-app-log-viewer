"""CLI entry point for amplifier-log-viewer."""

import argparse
from pathlib import Path


def main():
    """Main entry point for amplifier-log-viewer CLI."""
    parser = argparse.ArgumentParser(description="Web-based log viewer for Amplifier sessions")
    parser.add_argument(
        "--port",
        type=int,
        default=8180,
        help="Port to run the server on (default: 8180)",
    )
    parser.add_argument(
        "--projects-dir",
        type=Path,
        default=Path.home() / ".amplifier" / "projects",
        help="Path to Amplifier projects directory (default: ~/.amplifier/projects)",
    )
    parser.add_argument(
        "--sort-by-timestamp",
        action="store_true",
        help="Sort sessions by timestamp (most recent first) instead of session ID",
    )

    args = parser.parse_args()

    # Start server in background thread
    import threading
    import time

    server_ready = threading.Event()

    def start_server():
        """Start server and signal when ready."""
        from .server import app
        from .server import init_session_tree

        init_session_tree(args.projects_dir, sort_by_timestamp=args.sort_by_timestamp)
        server_ready.set()

        try:
            app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)
        except OSError as e:
            if "Address already in use" in str(e):
                print(f"\nError: Port {args.port} is already in use.")
                print("Try a different port with: amplifier-log-viewer --port <PORT>")
                raise SystemExit(1) from e
            raise

    # Start server thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait for server initialization
    server_ready.wait(timeout=5)
    time.sleep(0.5)  # Give Flask time to bind socket

    print(f"\nServer running on http://localhost:{args.port}")
    print("Open this URL in your browser to view logs")
    print("Press Ctrl+C to stop")

    # Keep main thread alive
    try:
        server_thread.join()
    except KeyboardInterrupt:
        print("\nShutting down...")


if __name__ == "__main__":
    main()
