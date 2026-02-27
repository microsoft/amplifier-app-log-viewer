"""CLI entry point for amplifier-log-viewer using Click."""

import click
from pathlib import Path

DEFAULT_PORT = 8180
DEFAULT_PROJECTS_DIR = Path.home() / ".amplifier" / "projects"


@click.group(invoke_without_command=True)
@click.option("--port", "-p", default=DEFAULT_PORT, help="Port to run the server on")
@click.option(
    "--projects-dir",
    type=click.Path(exists=False, path_type=Path),
    default=DEFAULT_PROJECTS_DIR,
    help="Path to Amplifier projects directory",
)
@click.option(
    "--host",
    default="127.0.0.1",
    help="Host to bind to (use 0.0.0.0 for network access)",
)
@click.option(
    "--base-path",
    default="",
    help="Base path for serving app (e.g., '/amplifier/logs'). Use when routing through subpaths.",
)
@click.pass_context
def cli(
    ctx: click.Context, port: int, projects_dir: Path, host: str, base_path: str
) -> None:
    """Amplifier Log Viewer - Web-based session log viewer.

    Run without a command to start the server in foreground mode.
    Use 'service' subcommand to manage background service.
    """
    ctx.ensure_object(dict)
    ctx.obj["port"] = port
    ctx.obj["projects_dir"] = projects_dir
    ctx.obj["host"] = host
    ctx.obj["base_path"] = base_path

    # If no subcommand, run the server (backwards compatible)
    if ctx.invoked_subcommand is None:
        ctx.invoke(
            serve,
            port=port,
            projects_dir=projects_dir,
            host=host,
            base_path=base_path,
            threads=8,
        )


@cli.command()
@click.option("--port", "-p", default=DEFAULT_PORT, help="Port to run the server on")
@click.option(
    "--projects-dir",
    type=click.Path(exists=False, path_type=Path),
    default=DEFAULT_PROJECTS_DIR,
    help="Path to Amplifier projects directory",
)
@click.option("--host", "-h", default="127.0.0.1", help="Host to bind to")
@click.option(
    "--base-path",
    default="",
    help="Base path for serving app (e.g., '/amplifier/logs'). Use when routing through subpaths.",
)
@click.option(
    "--threads",
    default=8,
    help="Number of server threads (default: 8)",
)
def serve(
    port: int, projects_dir: Path, host: str, base_path: str, threads: int
) -> None:
    """Run the log viewer server in foreground.

    This command is used by the service manager and can also be used
    to run the server directly in the terminal.
    """
    from .server import create_app

    app = create_app(str(projects_dir), base_path=base_path)

    click.echo("Starting Amplifier Log Viewer...")
    click.echo(f"  URL: http://{host}:{port}")
    if base_path:
        click.echo(f"  Base path: {base_path}")
    click.echo(f"  Projects: {projects_dir}")
    click.echo(f"  Threads: {threads}")
    click.echo("  Press Ctrl+C to stop\n")

    from waitress import serve as waitress_serve

    waitress_serve(app, host=host, port=port, threads=threads)


@cli.group()
@click.pass_context
def service(ctx: click.Context) -> None:
    """Manage amplifier-log-viewer as a background service.

    Install the log viewer as a system service that starts automatically
    and runs in the background.

    Supported platforms:
      - Linux/WSL: systemd user service
      - macOS: launchd LaunchAgent
    """
    pass


@service.command("install")
@click.option("--port", "-p", default=DEFAULT_PORT, help="Port for the service")
@click.option(
    "--projects-dir",
    type=click.Path(exists=False, path_type=Path),
    default=DEFAULT_PROJECTS_DIR,
    help="Path to Amplifier projects directory",
)
@click.option(
    "--host",
    default="127.0.0.1",
    help="Host to bind to (use 0.0.0.0 for network access)",
)
@click.option(
    "--base-path",
    default="",
    help="Base path for serving app (e.g., '/amplifier/logs'). Use when routing through subpaths.",
)
@click.pass_context
def service_install(
    ctx: click.Context, port: int, projects_dir: Path, host: str, base_path: str
) -> None:
    """Install as a background service."""
    from .service import ServiceStatus, get_service_manager

    try:
        manager = get_service_manager(
            port=port, projects_dir=projects_dir, host=host, base_path=base_path
        )
    except NotImplementedError as e:
        raise click.ClickException(str(e))

    click.echo(
        f"Installing amplifier-log-viewer as a {manager.platform_name} service..."
    )

    result = manager.install()

    if result.status == ServiceStatus.FAILED:
        raise click.ClickException(result.message or "Installation failed")

    click.echo()
    click.secho("✓ Service installed successfully!", fg="green", bold=True)
    click.echo()

    if result.message:
        click.echo(result.message)


@service.command("uninstall")
@click.option("--force", "-f", is_flag=True, help="Uninstall without confirmation")
@click.pass_context
def service_uninstall(ctx: click.Context, force: bool) -> None:
    """Uninstall the background service."""
    from .service import ServiceStatus, get_service_manager

    try:
        manager = get_service_manager()
    except NotImplementedError as e:
        raise click.ClickException(str(e))

    if not force:
        if not click.confirm("Are you sure you want to uninstall the service?"):
            click.echo("Cancelled.")
            return

    click.echo(f"Uninstalling {manager.platform_name} service...")

    result = manager.uninstall()

    if result.status == ServiceStatus.FAILED:
        raise click.ClickException(result.message or "Uninstallation failed")

    click.secho("✓ Service uninstalled.", fg="green")


@service.command("start")
@click.pass_context
def service_start(ctx: click.Context) -> None:
    """Start the background service."""
    from .service import ServiceStatus, get_service_manager

    try:
        manager = get_service_manager()
    except NotImplementedError as e:
        raise click.ClickException(str(e))

    click.echo("Starting service...")

    result = manager.start()

    if result.status == ServiceStatus.NOT_INSTALLED:
        raise click.ClickException(
            "Service not installed. Run 'amplifier-log-viewer service install' first."
        )
    elif result.status == ServiceStatus.FAILED:
        raise click.ClickException(result.message or "Failed to start service")
    elif result.status == ServiceStatus.RUNNING:
        click.secho("✓ Service started!", fg="green", bold=True)
        if result.message:
            click.echo(result.message)
    else:
        click.echo(f"Service status: {result.status.value}")
        if result.message:
            click.echo(result.message)


@service.command("stop")
@click.pass_context
def service_stop(ctx: click.Context) -> None:
    """Stop the background service."""
    from .service import ServiceStatus, get_service_manager

    try:
        manager = get_service_manager()
    except NotImplementedError as e:
        raise click.ClickException(str(e))

    click.echo("Stopping service...")

    result = manager.stop()

    if result.status == ServiceStatus.NOT_INSTALLED:
        raise click.ClickException("Service not installed.")
    elif result.status == ServiceStatus.FAILED:
        raise click.ClickException(result.message or "Failed to stop service")
    else:
        click.secho("✓ Service stopped.", fg="green")


@service.command("restart")
@click.pass_context
def service_restart(ctx: click.Context) -> None:
    """Restart the background service."""
    from .service import ServiceStatus, get_service_manager

    try:
        manager = get_service_manager()
    except NotImplementedError as e:
        raise click.ClickException(str(e))

    click.echo("Restarting service...")

    # Stop first (ignore errors if not running)
    manager.stop()

    # Then start
    result = manager.start()

    if result.status == ServiceStatus.NOT_INSTALLED:
        raise click.ClickException(
            "Service not installed. Run 'amplifier-log-viewer service install' first."
        )
    elif result.status == ServiceStatus.FAILED:
        raise click.ClickException(result.message or "Failed to restart service")
    elif result.status == ServiceStatus.RUNNING:
        click.secho("✓ Service restarted!", fg="green", bold=True)
        if result.message:
            click.echo(result.message)
    else:
        click.echo(f"Service status: {result.status.value}")
        if result.message:
            click.echo(result.message)


@service.command("status")
@click.pass_context
def service_status(ctx: click.Context) -> None:
    """Show the service status."""
    from .service import ServiceStatus, get_service_manager

    try:
        manager = get_service_manager()
    except NotImplementedError as e:
        raise click.ClickException(str(e))

    result = manager.status()

    # Status indicator with color
    status_colors = {
        ServiceStatus.RUNNING: ("green", "●"),
        ServiceStatus.STOPPED: ("yellow", "○"),
        ServiceStatus.FAILED: ("red", "✗"),
        ServiceStatus.NOT_INSTALLED: ("white", "○"),
        ServiceStatus.UNKNOWN: ("white", "?"),
    }

    color, symbol = status_colors.get(result.status, ("white", "?"))

    click.secho(f"{symbol} ", fg=color, nl=False, bold=True)
    click.secho("amplifier-log-viewer.service", bold=True, nl=False)
    click.echo(" - Amplifier Log Viewer")

    click.echo("   Status: ", nl=False)
    click.secho(result.status.value, fg=color, bold=True)

    if result.pid:
        click.echo(f"   PID: {result.pid}")

    if result.status == ServiceStatus.RUNNING and result.port:
        if result.host == "0.0.0.0":
            click.echo(f"   Listening: {result.host}:{result.port} (all interfaces)")
        else:
            click.echo(f"   URL: http://{result.host or 'localhost'}:{result.port}")

    if result.service_file:
        click.echo(f"   Config: {result.service_file}")

    if result.log_file and result.log_file.exists():
        click.echo(f"   Logs: {result.log_file}")

    if result.message and result.status not in (
        ServiceStatus.RUNNING,
        ServiceStatus.STOPPED,
    ):
        click.echo()
        click.echo(f"   {result.message}")


@service.command("logs")
@click.option("--follow", "-f", is_flag=True, help="Follow log output (like tail -f)")
@click.option("--lines", "-n", default=50, help="Number of lines to show")
@click.pass_context
def service_logs(ctx: click.Context, follow: bool, lines: int) -> None:
    """View service logs.

    Use -f/--follow to tail logs in real-time.
    """
    from .service import get_service_manager

    try:
        manager = get_service_manager()
    except NotImplementedError as e:
        raise click.ClickException(str(e))

    manager.logs(follow=follow, lines=lines)


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
