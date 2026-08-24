"""CLI entry point for amplifier-log-viewer using Click."""

from pathlib import Path

import click

from . import session_scanner

DEFAULT_PORT = 8180

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "localhost6"}


def roots_option(f):
    """Shared --root/--projects-dir repeatable option.

    Kept as a single decorator so the cli group, `serve`, and
    `service install` commands can't drift from each other.
    """
    return click.option(
        "--root",
        "--projects-dir",
        "roots",
        type=click.Path(exists=False, path_type=Path),
        multiple=True,
        help=(
            "Log root to scan (repeatable). Default: ~/.amplifier/projects and "
            "~/.amplifier-agent/state/workspaces. Env: AMPLIFIER_LOG_ROOTS."
        ),
    )(f)


def auth_options(f):
    """Shared --auth/--session-ttl/--behind-tls-proxy options.

    One decorator so `cli`, `serve`, and `service install` cannot drift --
    same reason roots_option exists.
    """
    f = click.option(
        "--behind-tls-proxy",
        is_flag=True,
        default=False,
        help=(
            "Assert that a TLS-terminating proxy sits in front of this server. "
            "Marks the session cookie Secure and silences the cleartext warning. "
            "Env: AMPLIFIER_LOG_VIEWER_BEHIND_TLS_PROXY."
        ),
    )(f)
    f = click.option(
        "--session-ttl",
        type=int,
        default=None,
        help="Session cookie lifetime in seconds (default 604800; 0 = browser session).",
    )(f)
    f = click.option(
        "--auth",
        "auth_mode",
        type=click.Choice(["pam", "password"]),
        default=None,
        help="Authentication mode (default: pam when available, else password).",
    )(f)
    return f


def warn_if_cleartext(host: str, behind_tls_proxy: bool) -> None:
    """Loudly warn when credentials would cross a network in the clear.

    Fires on any non-loopback bind without an asserted TLS terminator. The
    PAM password on POST /login and the session cookie on every subsequent
    request are both plaintext over HTTP.
    """
    if host in LOOPBACK_HOSTS or behind_tls_proxy:
        return
    click.secho("", err=True)
    click.secho("  " + "!" * 68, fg="red", bold=True, err=True)
    click.secho(
        f"  WARNING: bound to {host} over plain HTTP -- no TLS.",
        fg="red",
        bold=True,
        err=True,
    )
    click.secho(
        "  Your system password (at login) and session cookie (every request)",
        fg="red",
        err=True,
    )
    click.secho("  will cross the network in cleartext.", fg="red", err=True)
    click.secho("", err=True)
    click.secho("  Put TLS in front of it, or reach it over a private link:", err=True)
    click.secho("    tailscale serve --bg <port>        # simplest", err=True)
    click.secho("    ssh -L <port>:127.0.0.1:<port> <host>", err=True)
    click.secho("    caddy / nginx reverse proxy with a cert", err=True)
    click.secho("", err=True)
    click.secho(
        "  Once TLS terminates upstream, re-run with --behind-tls-proxy so the",
        err=True,
    )
    click.secho("  session cookie is marked Secure.", err=True)
    click.secho("  " + "!" * 68, fg="red", bold=True, err=True)
    click.secho("", err=True)


@click.group(invoke_without_command=True)
@click.option("--port", "-p", default=DEFAULT_PORT, help="Port to run the server on")
@roots_option
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
@auth_options
@click.pass_context
def cli(
    ctx: click.Context,
    port: int,
    roots: tuple[Path, ...],
    host: str,
    base_path: str,
    auth_mode: str | None,
    session_ttl: int | None,
    behind_tls_proxy: bool,
) -> None:
    """Amplifier Log Viewer - Web-based session log viewer.

    Run without a command to start the server in foreground mode.
    Use 'service' subcommand to manage background service.
    """
    ctx.ensure_object(dict)
    ctx.obj["port"] = port
    ctx.obj["roots"] = roots
    ctx.obj["host"] = host
    ctx.obj["base_path"] = base_path
    ctx.obj["auth_mode"] = auth_mode
    ctx.obj["session_ttl"] = session_ttl
    ctx.obj["behind_tls_proxy"] = behind_tls_proxy

    # If no subcommand, run the server (backwards compatible)
    if ctx.invoked_subcommand is None:
        ctx.invoke(
            serve,
            port=port,
            roots=roots,
            host=host,
            base_path=base_path,
            threads=8,
            auth_mode=auth_mode,
            session_ttl=session_ttl,
            behind_tls_proxy=behind_tls_proxy,
        )


@cli.command()
@click.option("--port", "-p", default=DEFAULT_PORT, help="Port to run the server on")
@roots_option
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
@auth_options
def serve(
    port: int,
    roots: tuple[Path, ...],
    host: str,
    base_path: str,
    threads: int,
    auth_mode: str | None,
    session_ttl: int | None,
    behind_tls_proxy: bool,
) -> None:
    """Run the log viewer server in foreground.

    This command is used by the service manager and can also be used
    to run the server directly in the terminal.
    """
    from .auth import expected_username, resolve_auth_config
    from .server import create_app

    # Resolve here (not just inside create_app) so the startup banner shows
    # exactly what will be scanned.
    resolved_roots = session_scanner.resolve_roots(roots or None)
    auth_cfg = resolve_auth_config(
        mode=auth_mode, ttl_seconds=session_ttl, behind_tls_proxy=behind_tls_proxy
    )
    app = create_app(resolved_roots, base_path=base_path, auth=auth_cfg)

    click.echo("Starting Amplifier Log Viewer...")
    click.echo(f"  URL: http://{host}:{port}")
    if base_path:
        click.echo(f"  Base path: {base_path}")
    for root in resolved_roots:
        click.echo(f"  Root: {root}")
    click.echo(f"  Threads: {threads}")
    click.echo(f"  Auth: {auth_cfg.mode}", nl=False)
    if auth_cfg.mode == "pam":
        click.echo(f" (user: {expected_username(auth_cfg)})")
    else:
        click.echo("")
    click.echo(f"  Session TTL: {auth_cfg.ttl_seconds}s")
    click.echo("  Press Ctrl+C to stop\n")

    warn_if_cleartext(host, behind_tls_proxy)

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


@service.command("install")
@click.option("--port", "-p", default=DEFAULT_PORT, help="Port for the service")
@roots_option
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
@auth_options
@click.pass_context
def service_install(
    ctx: click.Context,
    port: int,
    roots: tuple[Path, ...],
    host: str,
    base_path: str,
    auth_mode: str | None,
    session_ttl: int | None,
    behind_tls_proxy: bool,
) -> None:
    """Install as a background service.

    Note: auth mode/TTL/behind-tls-proxy are not yet baked into the
    generated service unit's ExecStart -- the installed service picks up
    auth using its own defaults (PAM, 7-day TTL) at run time, same as
    invoking `serve` with no auth flags. Passing these flags here is
    accepted (for forward compatibility) but currently has no effect on
    the installed unit; use `serve` directly if you need non-default auth
    settings enforced at install time.
    """
    from .service import ServiceStatus, get_service_manager

    try:
        manager = get_service_manager(
            port=port, roots=roots or None, host=host, base_path=base_path
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
