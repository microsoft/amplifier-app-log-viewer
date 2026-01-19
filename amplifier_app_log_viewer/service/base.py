"""Base service manager interface."""

import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ServiceStatus(Enum):
    """Service status enumeration."""

    RUNNING = "running"
    STOPPED = "stopped"
    NOT_INSTALLED = "not_installed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class ServiceInfo:
    """Information about the service."""

    status: ServiceStatus
    pid: int | None = None
    port: int | None = None
    host: str | None = None
    service_file: Path | None = None
    log_file: Path | None = None
    message: str | None = None


class ServiceManager(ABC):
    """Abstract base class for service management."""

    SERVICE_NAME = "amplifier-log-viewer"

    def __init__(
        self,
        port: int = 8180,
        projects_dir: Path | None = None,
        host: str = "127.0.0.1",
    ):
        """Initialize service manager.

        Args:
            port: Port for the web server
            projects_dir: Path to Amplifier projects directory
            host: Host to bind to (use 0.0.0.0 for network access)
        """
        self.port = port
        self.projects_dir = projects_dir or Path.home() / ".amplifier" / "projects"
        self.host = host

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform name (e.g., 'systemd', 'launchd')."""
        ...

    @property
    @abstractmethod
    def service_file_path(self) -> Path:
        """Return the path to the service configuration file."""
        ...

    @property
    @abstractmethod
    def log_file_path(self) -> Path:
        """Return the path to the service log file."""
        ...

    @abstractmethod
    def install(self) -> ServiceInfo:
        """Install the service.

        Returns:
            ServiceInfo with installation details
        """
        ...

    @abstractmethod
    def uninstall(self) -> ServiceInfo:
        """Uninstall the service.

        Returns:
            ServiceInfo with uninstallation details
        """
        ...

    @abstractmethod
    def start(self) -> ServiceInfo:
        """Start the service.

        Returns:
            ServiceInfo with service status
        """
        ...

    @abstractmethod
    def stop(self) -> ServiceInfo:
        """Stop the service.

        Returns:
            ServiceInfo with service status
        """
        ...

    @abstractmethod
    def status(self) -> ServiceInfo:
        """Get the current service status.

        Returns:
            ServiceInfo with current status
        """
        ...

    @abstractmethod
    def logs(self, follow: bool = False, lines: int = 50) -> None:
        """Display service logs.

        Args:
            follow: Whether to follow/tail the logs
            lines: Number of lines to show
        """
        ...

    def _find_executable(self) -> Path:
        """Find the amplifier-log-viewer executable.

        Returns:
            Path to the executable
        """
        import shutil
        import sys

        # Try to find via which
        exe = shutil.which("amplifier-log-viewer")
        if exe:
            return Path(exe).resolve()

        # Fall back to common uv tool location
        uv_path = Path.home() / ".local" / "bin" / "amplifier-log-viewer"
        if uv_path.exists():
            return uv_path

        # Last resort: derive from current Python
        # This works when running via `uv run` or in a venv
        python_dir = Path(sys.executable).parent
        candidate = python_dir / "amplifier-log-viewer"
        if candidate.exists():
            return candidate

        raise FileNotFoundError(
            "Could not find amplifier-log-viewer executable. "
            "Make sure it's installed via 'uv tool install' or 'pip install'."
        )


def get_service_manager(
    port: int = 8180, projects_dir: Path | None = None, host: str = "127.0.0.1"
) -> ServiceManager:
    """Get the appropriate service manager for the current platform.

    Args:
        port: Port for the web server
        projects_dir: Path to Amplifier projects directory
        host: Host to bind to (use 0.0.0.0 for network access)

    Returns:
        ServiceManager instance for the current platform

    Raises:
        NotImplementedError: If the current platform is not supported
    """
    system = platform.system()

    if system == "Darwin":
        from .launchd import LaunchdServiceManager

        return LaunchdServiceManager(port=port, projects_dir=projects_dir, host=host)
    elif system == "Linux":
        from .systemd import SystemdServiceManager

        return SystemdServiceManager(port=port, projects_dir=projects_dir, host=host)
    else:
        raise NotImplementedError(
            f"Service mode is not supported on {system}. "
            "Supported platforms: Linux (systemd), macOS (launchd)"
        )
