"""Launchd service management for macOS."""

import os
import plistlib
import subprocess
from pathlib import Path

from .base import ServiceInfo, ServiceManager, ServiceStatus

LAUNCHD_LABEL = "com.amplifier.log-viewer"


class LaunchdServiceManager(ServiceManager):
    """Launchd-based service manager for macOS."""

    @property
    def platform_name(self) -> str:
        return "launchd"

    @property
    def label(self) -> str:
        return LAUNCHD_LABEL

    @property
    def service_file_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{self.label}.plist"

    @property
    def log_file_path(self) -> Path:
        return Path.home() / "Library" / "Logs" / f"{self.SERVICE_NAME}.log"

    @property
    def error_log_path(self) -> Path:
        return Path.home() / "Library" / "Logs" / f"{self.SERVICE_NAME}-error.log"

    def _get_uid(self) -> int:
        """Get current user ID."""
        return os.getuid()

    def _get_domain_target(self) -> str:
        """Get the launchd domain target for the current user."""
        return f"gui/{self._get_uid()}"

    def _get_service_target(self) -> str:
        """Get the launchd service target for the current user."""
        return f"{self._get_domain_target()}/{self.label}"

    def _run_launchctl(self, *args: str, check: bool = False) -> subprocess.CompletedProcess:
        """Run a launchctl command."""
        cmd = ["launchctl", *args]
        return subprocess.run(cmd, capture_output=True, text=True, check=check)

    def _generate_plist(self, executable: Path) -> dict:
        """Generate the launchd plist configuration."""
        home = str(Path.home())

        return {
            "Label": self.label,
            "ProgramArguments": [
                str(executable),
                "serve",
                "--port",
                str(self.port),
                "--projects-dir",
                str(self.projects_dir),
            ],
            "EnvironmentVariables": {
                "HOME": home,
                "PATH": f"{home}/.local/bin:/usr/local/bin:/usr/bin:/bin",
            },
            "RunAtLoad": True,
            "KeepAlive": {
                "SuccessfulExit": False,  # Restart on crash, not on clean exit
            },
            "StandardOutPath": str(self.log_file_path),
            "StandardErrorPath": str(self.error_log_path),
            "ProcessType": "Background",
            "LowPriorityIO": True,
        }

    def install(self) -> ServiceInfo:
        """Install the launchd LaunchAgent."""
        try:
            executable = self._find_executable()
        except FileNotFoundError as e:
            return ServiceInfo(
                status=ServiceStatus.FAILED,
                message=str(e),
            )

        # Create LaunchAgents directory if needed
        self.service_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Create logs directory if needed
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Generate and write plist
        plist_data = self._generate_plist(executable)

        with open(self.service_file_path, "wb") as f:
            plistlib.dump(plist_data, f)

        # Set proper permissions (644)
        self.service_file_path.chmod(0o644)

        return ServiceInfo(
            status=ServiceStatus.STOPPED,
            service_file=self.service_file_path,
            log_file=self.log_file_path,
            port=self.port,
            message=(
                f"Service installed successfully.\n"
                f"Plist file: {self.service_file_path}\n"
                f"Log file: {self.log_file_path}\n"
                f"Port: {self.port}\n\n"
                f"To start: amplifier-log-viewer service start"
            ),
        )

    def uninstall(self) -> ServiceInfo:
        """Uninstall the launchd LaunchAgent."""
        # Bootout (unload) the service first
        self._run_launchctl("bootout", self._get_service_target(), check=False)

        # Remove plist file
        if self.service_file_path.exists():
            self.service_file_path.unlink()

        return ServiceInfo(
            status=ServiceStatus.NOT_INSTALLED,
            message="Service uninstalled successfully.",
        )

    def start(self) -> ServiceInfo:
        """Start the launchd service."""
        if not self.service_file_path.exists():
            return ServiceInfo(
                status=ServiceStatus.NOT_INSTALLED,
                message="Service not installed. Run 'amplifier-log-viewer service install' first.",
            )

        # Try to bootstrap (load) the service
        result = self._run_launchctl(
            "bootstrap",
            self._get_domain_target(),
            str(self.service_file_path),
            check=False,
        )

        # If already bootstrapped, try kickstart instead
        if result.returncode != 0:
            if "already bootstrapped" in result.stderr.lower() or "already loaded" in result.stderr.lower():
                # Service is loaded, try to kickstart it
                result = self._run_launchctl(
                    "kickstart",
                    "-k",  # Kill existing if running
                    self._get_service_target(),
                    check=False,
                )
            elif "could not find" not in result.stderr.lower():
                return ServiceInfo(
                    status=ServiceStatus.FAILED,
                    message=f"Failed to start service: {result.stderr}",
                )

        # Give it a moment to start
        import time
        time.sleep(1)

        return self.status()

    def stop(self) -> ServiceInfo:
        """Stop the launchd service."""
        if not self.service_file_path.exists():
            return ServiceInfo(
                status=ServiceStatus.NOT_INSTALLED,
                message="Service not installed.",
            )

        # Send SIGTERM to stop the service
        result = self._run_launchctl(
            "kill",
            "SIGTERM",
            self._get_service_target(),
            check=False,
        )

        if result.returncode != 0 and "no such process" not in result.stderr.lower():
            # Try bootout as fallback
            self._run_launchctl("bootout", self._get_service_target(), check=False)

        return ServiceInfo(
            status=ServiceStatus.STOPPED,
            message="Service stopped.",
        )

    def status(self) -> ServiceInfo:
        """Get the current service status."""
        if not self.service_file_path.exists():
            return ServiceInfo(
                status=ServiceStatus.NOT_INSTALLED,
                service_file=None,
                message="Service not installed.",
            )

        # Get service info using launchctl list
        result = self._run_launchctl("list", check=False)

        if result.returncode != 0:
            return ServiceInfo(
                status=ServiceStatus.UNKNOWN,
                service_file=self.service_file_path,
                message=f"Could not get status: {result.stderr}",
            )

        # Parse the output to find our service
        # Format: PID\tStatus\tLabel
        pid = None
        exit_code = None
        found = False

        for line in result.stdout.strip().split("\n"):
            if self.label in line:
                found = True
                parts = line.split("\t")
                if len(parts) >= 2:
                    pid_str = parts[0].strip()
                    exit_str = parts[1].strip()
                    pid = int(pid_str) if pid_str and pid_str != "-" else None
                    exit_code = int(exit_str) if exit_str and exit_str != "-" else None
                break

        if not found:
            # Service is installed but not loaded
            return ServiceInfo(
                status=ServiceStatus.STOPPED,
                service_file=self.service_file_path,
                message="Service installed but not loaded.",
            )

        if pid is not None and pid > 0:
            status = ServiceStatus.RUNNING
            message = f"PID: {pid}\nURL: http://localhost:{self.port}"
        elif exit_code is not None and exit_code != 0:
            status = ServiceStatus.FAILED
            message = f"Last exit code: {exit_code}\nCheck logs: amplifier-log-viewer service logs"
        else:
            status = ServiceStatus.STOPPED
            message = "Service is loaded but not running."

        return ServiceInfo(
            status=status,
            pid=pid,
            port=self.port if status == ServiceStatus.RUNNING else None,
            service_file=self.service_file_path,
            log_file=self.log_file_path,
            message=message,
        )

    def logs(self, follow: bool = False, lines: int = 50) -> None:
        """Display service logs."""
        if not self.log_file_path.exists():
            print(f"No logs found at {self.log_file_path}")
            print("The service may not have started yet.")
            return

        if follow:
            # Use tail -f for follow mode
            cmd = ["tail", "-f", "-n", str(lines), str(self.log_file_path)]
            os.execvp("tail", cmd)
        else:
            # Just show last N lines
            cmd = ["tail", "-n", str(lines), str(self.log_file_path)]
            result = subprocess.run(cmd, check=False)

            # Also show error log if it exists and has content
            if self.error_log_path.exists() and self.error_log_path.stat().st_size > 0:
                print(f"\n--- Error log ({self.error_log_path}) ---")
                subprocess.run(
                    ["tail", "-n", str(lines), str(self.error_log_path)],
                    check=False,
                )
