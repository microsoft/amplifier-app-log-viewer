"""JSONL log file reader with pagination and progressive loading support."""

import json
from pathlib import Path


def read_event_list(file_path: Path, offset: int = 0, limit: int = 200) -> dict:
    """
    Fast scan: read events but extract only header fields for list display.

    Returns lightweight event objects with just the metadata needed for
    the event list view, not the full payload. Supports pagination via
    offset and limit.

    Args:
        file_path: Path to events.jsonl file
        offset: Line number to start reading from (0-indexed)
        limit: Maximum number of events to return

    Returns:
        Dict with: events, total, offset, limit, has_more
    """
    empty = {
        "events": [],
        "total": 0,
        "offset": offset,
        "limit": limit,
        "has_more": False,
    }

    if not file_path.exists():
        return empty

    total = count_lines(file_path)
    events = []

    try:
        with open(file_path, "rb") as f:
            byte_pos = 0

            # Skip to offset
            for _ in range(offset):
                raw_line = f.readline()
                if not raw_line:
                    break
                byte_pos += len(raw_line)

            # Read up to limit lines
            lines_read = 0
            while lines_read < limit:
                raw_line = f.readline()
                if not raw_line:
                    break
                current_offset = byte_pos
                byte_pos += len(raw_line)

                line = raw_line.strip()
                if not line:
                    lines_read += 1
                    continue

                try:
                    event = json.loads(line)
                    # Extract only what we need for list display
                    events.append(
                        {
                            "line": offset + lines_read,
                            "byte_offset": current_offset,
                            "ts": event.get("ts"),
                            "event": event.get("event"),
                            "lvl": event.get("lvl"),
                            "session_id": event.get("session_id"),
                            "preview": _compute_preview(event),
                            "size": len(line),  # Byte size of the raw line
                        }
                    )
                except json.JSONDecodeError:
                    pass

                lines_read += 1

    except OSError as e:
        print(f"Warning: Error reading {file_path}: {e}")
        return empty

    return {
        "events": events,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


def read_single_event(
    file_path: Path, line_num: int, byte_offset: int | None = None
) -> dict | None:
    """
    Read a single event by line number.

    If byte_offset is provided, seeks directly to that offset for O(1) access.
    Otherwise falls back to a linear scan for backward compatibility.

    Args:
        file_path: Path to events.jsonl file
        line_num: Line number (0-indexed) to read
        byte_offset: Optional byte offset to seek directly to the line

    Returns:
        Full event dict with line number added, or None if not found
    """
    if not file_path.exists():
        return None

    try:
        if byte_offset is not None:
            # Fast path: seek directly to byte offset
            with open(file_path, "rb") as f:
                f.seek(byte_offset)
                raw_line = f.readline()
                if raw_line:
                    line = raw_line.strip()
                    if line:
                        try:
                            event = json.loads(line)
                            event["line"] = line_num
                            return event
                        except json.JSONDecodeError:
                            return None
                return None

        # Fallback: linear scan (backward compatibility)
        with open(file_path, encoding="utf-8") as f:
            for current_line, line in enumerate(f):
                if current_line == line_num:
                    line = line.strip()
                    if line:
                        try:
                            event = json.loads(line)
                            event["line"] = line_num  # Include line number
                            return event
                        except json.JSONDecodeError:
                            return None
                    return None
                # Skip past the target line - event not found
                if current_line > line_num:
                    return None

    except OSError as e:
        print(f"Warning: Error reading {file_path}: {e}")
        return None

    return None  # Line not found (file has fewer lines)


def _compute_preview(event: dict) -> str:
    """Compute a short preview string for list display."""
    data = event.get("data", {})
    if not data:
        return ""

    event_type = event.get("event", "")

    # LLM debug events (nested data.data structure)
    if ":debug" in event_type:
        nested_data = data.get("data", {})

        if event_type.startswith("llm:request"):
            request = nested_data.get("request", {})
            model = request.get("model", "")
            msg_count = len(request.get("messages", []))
            if model and msg_count > 0:
                return f"{model} | {msg_count} messages"

        if event_type.startswith("llm:response"):
            response = nested_data.get("response", {})
            usage = response.get("usage", {})
            tokens = usage.get("total_tokens") or usage.get("input_tokens")
            if tokens:
                return f"{tokens} tokens"

    # Standard LLM events
    if event_type.startswith("llm:"):
        nested_data = data.get("data", data)
        provider = nested_data.get("provider")
        if provider:
            return f"Provider: {provider}"

    # Tool events
    if event_type.startswith("tool:"):
        tool_name = data.get("tool_name") or data.get("name")
        if tool_name:
            return f"Tool: {tool_name}"

    # Prompt events
    if event_type.startswith("prompt:"):
        prompt = data.get("prompt", "")
        if prompt:
            if len(prompt) < 60:
                return prompt
            return prompt[:57] + "..."

    # Content block events
    if event_type.startswith("content_block:"):
        block_type = data.get("block_type")
        block_index = data.get("block_index")
        if block_type is not None and block_index is not None:
            return f"Block {block_index}: {block_type}"

    return ""


def read_events(
    file_path: Path, offset: int = 0, limit: int = 100
) -> tuple[list[dict], int]:
    """
    Read events from JSONL file with pagination.

    DEPRECATED: Use read_event_list() for list view and read_single_event()
    for detail view instead. This function is kept for backward compatibility.

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


def tail_events(
    file_path: Path, last_position: int = 0, last_line_count: int = 0
) -> tuple[list[dict], int, int]:
    """
    Read new events since last_position (byte offset).

    Used by SSE streaming to detect new log entries. The caller tracks
    both last_position and last_line_count, so this function only needs
    to seek to last_position and read forward — no byte-0 re-scan.

    Args:
        file_path: Path to events.jsonl file
        last_position: Byte offset of last read position
        last_line_count: Line count at last_position (for line numbering)

    Returns:
        Tuple of (new_events, new_position, new_line_count) where
        new_events is list of lightweight event dicts, new_position is
        current byte offset, and new_line_count is updated line count
    """
    if not file_path.exists():
        return [], 0, 0

    new_events = []
    new_position = last_position
    line_count = last_line_count

    try:
        with open(file_path, encoding="utf-8") as f:
            # Seek directly to last position — no re-scan needed
            f.seek(last_position)

            for line in f:
                line_stripped = line.strip()
                if not line_stripped:
                    continue

                try:
                    event = json.loads(line_stripped)
                    # Return lightweight format for SSE
                    new_events.append(
                        {
                            "line": line_count,
                            "ts": event.get("ts"),
                            "event": event.get("event"),
                            "lvl": event.get("lvl"),
                            "session_id": event.get("session_id"),
                            "preview": _compute_preview(event),
                            "size": len(line_stripped),
                        }
                    )
                    line_count += 1
                except json.JSONDecodeError:
                    # Skip corrupted lines
                    continue

            # Get current position
            new_position = f.tell()

    except OSError as e:
        print(f"Warning: Error tailing {file_path}: {e}")
        return new_events, last_position, last_line_count

    return new_events, new_position, line_count


def count_lines(file_path: Path) -> int:
    """
    Fast line counting using buffered binary read.

    Args:
        file_path: Path to file

    Returns:
        Number of newline-delimited lines in file
    """
    if not file_path.exists():
        return 0

    try:
        count = 0
        with open(file_path, "rb") as f:
            while True:
                buf = f.read(1024 * 1024)  # 1MB chunks
                if not buf:
                    break
                count += buf.count(b"\n")
        return count
    except OSError:
        return 0
