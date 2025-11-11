"""JSONL log file reader with pagination support."""

import json
from pathlib import Path


def read_events(
    file_path: Path, offset: int = 0, limit: int = 100
) -> tuple[list[dict], int]:
    """
    Read events from JSONL file with pagination.

    Args:
        file_path: Path to events.jsonl file
        offset: Line number to start reading from (0-indexed)
        limit: Maximum number of events to read

    Returns:
        Tuple of (events, total_count) where events is list of parsed JSON objects
        and total_count is total lines in file

    Raises:
        FileNotFoundError: If log file doesn't exist
    """
    if not file_path.exists():
        return [], 0

    events = []

    try:
        with open(file_path, encoding="utf-8") as f:
            # Skip to offset
            for _ in range(offset):
                line = f.readline()
                if not line:
                    break

            # Read next 'limit' lines
            for _ in range(limit):
                line = f.readline()
                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                    events.append(event)
                except json.JSONDecodeError:
                    # Skip corrupted lines
                    continue

            # Count total lines for pagination
            total_lines = offset + len(events)
            for line in f:
                if line.strip():
                    total_lines += 1

    except OSError as e:
        # Handle I/O errors (cloud sync, permissions, etc.)
        print(f"Warning: Error reading {file_path}: {e}")
        return events, 0

    return events, total_lines


def tail_events(file_path: Path, last_position: int = 0) -> tuple[list[dict], int]:
    """
    Read new events since last_position (byte offset).

    Used by SSE streaming to detect new log entries.

    Args:
        file_path: Path to events.jsonl file
        last_position: Byte offset of last read position

    Returns:
        Tuple of (new_events, new_position) where new_events is list of events
        since last_position and new_position is current byte offset

    Raises:
        FileNotFoundError: If log file doesn't exist
    """
    if not file_path.exists():
        return [], 0

    new_events = []
    new_position = last_position

    try:
        with open(file_path, encoding="utf-8") as f:
            # Seek to last position
            f.seek(last_position)

            # Read new lines
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                    new_events.append(event)
                except json.JSONDecodeError:
                    # Skip corrupted lines
                    continue

            # Get current position
            new_position = f.tell()

    except OSError as e:
        print(f"Warning: Error tailing {file_path}: {e}")
        return new_events, last_position

    return new_events, new_position


def count_lines(file_path: Path) -> int:
    """
    Fast line counting for pagination.

    Args:
        file_path: Path to file

    Returns:
        Number of non-empty lines in file
    """
    if not file_path.exists():
        return 0

    try:
        with open(file_path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0
