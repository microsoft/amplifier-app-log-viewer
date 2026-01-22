"""Systemd service management for Linux/WSL."""

import os
import subprocess
from pathlib import Path

from .base import ServiceInfo, ServiceManager, ServiceStatus

SYSTEMD_SERVICE_TEMPLATE = """\
[Unit]
Description=Amplifier Log Viewer - Web-based session log viewer
Documentation=https://github.com/microsoft/amplifier-app-log-viewer
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart={executable} serve --port {port} --host {host} --projects-dir {projects_dir} {base_path_arg}
Restart=on-failure
RestartSec=10
Environment=HOME={home}

[Install]
WantedBy=default.target
"""


class SystemdServiceManager(ServiceManager):
    """Systemd-based service manager for Linux/WSL."""

    @property
    def platform_name(self) -> str:
        return "systemd"

    @property
    def service_file_path(self) -> Path:
        return (
            Path.home()
            / ".config"
            / "systemd"
            / "user"
            / f"{self.SERVICE_NAME}.service"
        )

    @property
    def log_file_path(self) -> Path:
        # systemd uses journald, no separate log file
        return Path("/dev/null")

    def _run_systemctl(
        self, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess:
        """Run a systemctl --user command."""
        cmd = ["systemctl", "--user", *args]
        return subprocess.run(cmd, capture_output=True, text=True, check=check)

    def _daemon_reload(self) -> None:
        """Reload systemd daemon to pick up changes."""
        self._run_systemctl("daemon-reload", check=False)

    def _check_systemd_available(self) -> None:
        """Check if systemd is available and running."""
        # Check if systemctl exists
        result = subprocess.run(
            ["which", "systemctl"], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise RuntimeError(
                "systemctl not found. systemd is required for service mode on Linux."
            )

        # Check if user session is available
        result = self._run_systemctl("--version", check=False)
        if result.returncode != 0:
            raise RuntimeError(
                "systemd user session not available. "
                "On WSL2, ensure systemd is enabled in /etc/wsl.conf:\n"
                "  [boot]\n"
                "  systemd=true\n"
                "Then restart WSL with: wsl --shutdown"
            )

    def install(self) -> ServiceInfo:
        """Install the systemd user service."""
        self._check_systemd_available()

        try:
            executable = self._find_executable()
        except FileNotFoundError as e:
            return ServiceInfo(
                status=ServiceStatus.FAILED,
                message=str(e),
            )

        # Create service directory
        self.service_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Generate service file content
        base_path_arg = f"--base-path {self.base_path}" if self.base_path else ""
        content = SYSTEMD_SERVICE_TEMPLATE.format(
            executable=executable,
            port=self.port,
            host=self.host,
            projects_dir=self.projects_dir,
            base_path_arg=base_path_arg,
            home=Path.home(),
        )

        # Write service file
        self.service_file_path.write_text(content)

        # Reload systemd
        self._daemon_reload()

        # Enable the service (but don't start yet)
        self._run_systemctl("enable", f"{self.SERVICE_NAME}.service", check=False)

        return ServiceInfo(
            status=ServiceStatus.STOPPED,
            service_file=self.service_file_path,
            port=self.port,
            host=self.host,
            message=(
                f"Service installed successfully.\n"
                f"Service file: {self.service_file_path}\n"
                f"Host: {self.host}\n"
                f"Port: {self.port}\n\n"
                f"To start: amplifier-log-viewer service start\n"
                f"To enable auto-start at boot: sudo loginctl enable-linger $USER"
            ),
        )

    def uninstall(self) -> ServiceInfo:
        """Uninstall the systemd user service."""
        # Stop the service first
        self._run_systemctl("stop", f"{self.SERVICE_NAME}.service", check=False)

        # Disable the service
        self._run_systemctl("disable", f"{self.SERVICE_NAME}.service", check=False)

        # Remove service file
        if self.service_file_path.exists():
            self.service_file_path.unlink()

        # Reload systemd
        self._daemon_reload()

        return ServiceInfo(
            status=ServiceStatus.NOT_INSTALLED,
            message="Service uninstalled successfully.",
        )

    def start(self) -> ServiceInfo:
        """Start the systemd service."""
        if not self.service_file_path.exists():
            return ServiceInfo(
                status=ServiceStatus.NOT_INSTALLED,
                message="Service not installed. Run 'amplifier-log-viewer service install' first.",
            )

        result = self._run_systemctl(
            "start", f"{self.SERVICE_NAME}.service", check=False
        )

        if result.returncode != 0:
            return ServiceInfo(
                status=ServiceStatus.FAILED,
                message=f"Failed to start service: {result.stderr}",
            )

        # Get status to confirm and get PID
        return self.status()

    def stop(self) -> ServiceInfo:
        """Stop the systemd service."""
        if not self.service_file_path.exists():
            return ServiceInfo(
                status=ServiceStatus.NOT_INSTALLED,
                message="Service not installed.",
            )

        result = self._run_systemctl(
            "stop", f"{self.SERVICE_NAME}.service", check=False
        )

        if result.returncode != 0:
            return ServiceInfo(
                status=ServiceStatus.FAILED,
                message=f"Failed to stop service: {result.stderr}",
            )

        return ServiceInfo(
            status=ServiceStatus.STOPPED,
            message="Service stopped.",
        )

    def _parse_service_config(self) -> tuple[str, int]:
        """Parse host and port from the installed service file.

        Returns:
            Tuple of (host, port) parsed from ExecStart line
        """
        host = "127.0.0.1"
        port = 8180

        if not self.service_file_path.exists():
            return host, port

        try:
            content = self.service_file_path.read_text()
            for line in content.split("\n"):
                if line.startswith("ExecStart="):
                    # Parse --host and --port from ExecStart line
                    import re

                    host_match = re.search(r"--host\s+(\S+)", line)
                    if host_match:
                        host = host_match.group(1)

                    port_match = re.search(r"--port\s+(\d+)", line)
                    if port_match:
                        port = int(port_match.group(1))
                    break
        except OSError:
            pass

        return host, port

    def status(self) -> ServiceInfo:
        """Get the current service status."""
        if not self.service_file_path.exists():
            return ServiceInfo(
                status=ServiceStatus.NOT_INSTALLED,
                service_file=None,
                message="Service not installed.",
            )

        # Parse config from service file
        configured_host, configured_port = self._parse_service_config()

        # Get service status
        result = self._run_systemctl(
            "show",
            f"{self.SERVICE_NAME}.service",
            "--property=ActiveState,MainPID,SubState",
            check=False,
        )

        if result.returncode != 0:
            return ServiceInfo(
                status=ServiceStatus.UNKNOWN,
                service_file=self.service_file_path,
                message=f"Could not get status: {result.stderr}",
            )

        # Parse properties
        props = {}
        for line in result.stdout.strip().split("\n"):
            if "=" in line:
                key, value = line.split("=", 1)
                props[key] = value

        active_state = props.get("ActiveState", "unknown")
        main_pid = props.get("MainPID", "0")
        sub_state = props.get("SubState", "unknown")

        # Map to our status enum
        if active_state == "active":
            status = ServiceStatus.RUNNING
        elif active_state == "failed":
            status = ServiceStatus.FAILED
        elif active_state in ("inactive", "deactivating"):
            status = ServiceStatus.STOPPED
        else:
            status = ServiceStatus.UNKNOWN

        pid = int(main_pid) if main_pid and main_pid != "0" else None

        message = f"State: {active_state} ({sub_state})"
        if status == ServiceStatus.RUNNING:
            # Show appropriate URL based on configured host
            if configured_host == "0.0.0.0":
                message += f"\nURL: http://<host>:{configured_port} (listening on all interfaces)"
            else:
                message += f"\nURL: http://{configured_host}:{configured_port}"

        return ServiceInfo(
            status=status,
            pid=pid,
            port=configured_port if status == ServiceStatus.RUNNING else None,
            host=configured_host if status == ServiceStatus.RUNNING else None,
            service_file=self.service_file_path,
            message=message,
        )

    def logs(self, follow: bool = False, lines: int = 50) -> None:
        """Display service logs using journalctl."""
        cmd = [
            "journalctl",
            "--user",
            "-u",
            f"{self.SERVICE_NAME}.service",
            "-n",
            str(lines),
            "--no-pager",
        ]

        if follow:
            cmd.append("-f")

        # Use os.execvp for follow mode to handle Ctrl+C properly
        if follow:
            os.execvp("journalctl", cmd)
        else:
            result = subprocess.run(cmd, check=False)
            if result.returncode != 0:
                print("No logs available or service not installed.")
