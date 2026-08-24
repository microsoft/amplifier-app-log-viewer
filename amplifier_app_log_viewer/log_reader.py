"""JSONL log file reader with pagination and progressive loading support."""

import json
from pathlib import Path

TRANSCRIPT_MAX_TEXT = 4000  # per text block, before server-side truncation


def _event_header(
    event: dict, line: int, size: int, byte_offset: int | None = None
) -> dict:
    """Lightweight list-view record. Tolerates both event schemas:
      - old session-root: ts, lvl, session_id, schema
      - context-intelligence: timestamp, no lvl, no session_id, workspace
    `lvl` defaults to "INFO" because the context-intelligence stream carries no
    level at all; INFO keeps the badge, the CSS class, and the Level filter
    mutually consistent rather than showing a level the filter then hides.
    """
    return {
        "line": line,
        "byte_offset": byte_offset,  # omit/None in the tail_events path
        "ts": event.get("ts") or event.get("timestamp"),
        "event": event.get("event") or "",
        "lvl": event.get("lvl") or "INFO",
        "session_id": event.get("session_id"),  # may be None; frontend tolerates
        "preview": _compute_preview(event),
        "size": size,
    }


def read_event_list(file_path: Path | None, offset: int = 0, limit: int = 200) -> dict:
    """
    Fast scan: read events but extract only header fields for list display.

    Returns lightweight event objects with just the metadata needed for
    the event list view, not the full payload. Supports pagination via
    offset and limit.

    Args:
        file_path: Path to events.jsonl file (or None if the session has none)
        offset: Line number to start reading from (0-indexed)
        limit: Maximum number of events to return

    Returns:
        Dict with: events, total, offset, limit, has_more, tail_position, tail_line_count
    """
    empty = {
        "events": [],
        "total": 0,
        "offset": offset,
        "limit": limit,
        "has_more": False,
        "tail_position": 0,
        "tail_line_count": 0,
    }

    if file_path is None or not file_path.exists():
        return empty

    events = []
    hit_limit = False

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
                    events.append(
                        _event_header(
                            event, offset + lines_read, len(line), current_offset
                        )
                    )
                except json.JSONDecodeError:
                    pass

                lines_read += 1

            # Check if there are more lines after the ones we read
            # by attempting to read one more line (avoids full file scan)
            if lines_read == limit:
                next_line = f.readline()
                hit_limit = bool(next_line)

    except OSError as e:
        print(f"Warning: Error reading {file_path}: {e}")
        return empty

    # Tail position for polling: O(1) stat call -- no file reading
    try:
        tail_position = file_path.stat().st_size
    except OSError:
        tail_position = 0

    if hit_limit:
        # More events than limit -- need exact total for line numbering.
        # count_lines scans bytes in 1MB chunks (no JSON parsing) -- fast.
        total = count_lines(file_path)
    else:
        # All events fit -- we have the exact count already
        total = offset + len(events)

    return {
        "events": events,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": hit_limit,
        "tail_position": tail_position,
        "tail_line_count": total,
    }


def read_single_event(
    file_path: Path | None, line_num: int, byte_offset: int | None = None
) -> dict | None:
    """
    Read a single JSONL line by line number and stamp it with `line`.

    Originally written for events.jsonl, but the implementation is entirely
    format-agnostic -- it parses the Nth JSONL line and adds a `line` key.
    The transcript detail route reuses this verbatim for transcript.jsonl.

    If byte_offset is provided, seeks directly to that offset for O(1) access.
    Otherwise falls back to a linear scan for backward compatibility.

    Args:
        file_path: Path to the JSONL file (or None if unavailable)
        line_num: Line number (0-indexed) to read
        byte_offset: Optional byte offset to seek directly to the line

    Returns:
        Full parsed dict with line number added, or None if not found
    """
    if file_path is None or not file_path.exists():
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

    # session lifecycle
    if event_type.startswith("session:"):
        return data.get("workspace") or data.get("bundle") or data.get("status") or ""

    # provider events
    if event_type.startswith("provider:"):
        nested = data.get("data", data)
        parts = [p for p in (nested.get("provider"), nested.get("model")) if p]
        if parts:
            return " | ".join(parts)

    # orchestrator / mentions
    if event_type.startswith(("orchestrator:", "mentions:")):
        n = data.get("count")
        return f"{n} items" if n is not None else ""

    return ""


def read_events(
    file_path: Path | None, offset: int = 0, limit: int = 100
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
    if file_path is None or not file_path.exists():
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
    file_path: Path | None, last_position: int = 0, last_line_count: int = 0
) -> tuple[list[dict], int, int]:
    """
    Read new events since last_position (byte offset).

    Used by SSE streaming to detect new log entries. The caller tracks
    both last_position and last_line_count, so this function only needs
    to seek to last_position and read forward -- no byte-0 re-scan.

    Args:
        file_path: Path to events.jsonl file (or None if unavailable)
        last_position: Byte offset of last read position
        last_line_count: Line count at last_position (for line numbering)

    Returns:
        Tuple of (new_events, new_position, new_line_count) where
        new_events is list of lightweight event dicts, new_position is
        current byte offset, and new_line_count is updated line count
    """
    if file_path is None or not file_path.exists():
        return [], 0, 0

    new_events = []
    new_position = last_position
    line_count = last_line_count

    try:
        with open(file_path, encoding="utf-8") as f:
            # Seek directly to last position -- no re-scan needed
            f.seek(last_position)

            for line in f:
                line_stripped = line.strip()
                if not line_stripped:
                    continue

                try:
                    event = json.loads(line_stripped)
                    new_events.append(
                        _event_header(event, line_count, len(line_stripped))
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


def count_lines(file_path: Path | None) -> int:
    """
    Fast line counting using buffered binary read.

    Args:
        file_path: Path to file (or None if unavailable)

    Returns:
        Number of newline-delimited lines in file
    """
    if file_path is None or not file_path.exists():
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


# ---------------------------------------------------------------------------
# Transcript reading
# ---------------------------------------------------------------------------


def _normalize_block(block, max_text: int) -> dict:
    """Normalize one content/thinking block into a uniform render shape."""
    if not isinstance(block, dict):
        return {"type": "text", "text": str(block), "truncated": False}

    if "text" in block:
        text = block.get("text") or ""
        truncated = len(text) > max_text
        return {
            "type": block.get("type") or "text",
            "text": text[:max_text],
            "truncated": truncated,
        }

    if "thinking" in block:
        text = block.get("thinking") or ""
        truncated = len(text) > max_text
        return {
            "type": "thinking",
            "text": text[:max_text],
            "truncated": truncated,
        }

    return {
        "type": block.get("type") or "unknown",
        "summary": json.dumps(block)[:200],
        "truncated": True,
    }


def _normalize_content(content, max_text: int) -> list[dict]:
    """Normalize `content` (str or list[block]) into a list of uniform blocks."""
    if isinstance(content, str):
        truncated = len(content) > max_text
        return [{"type": "text", "text": content[:max_text], "truncated": truncated}]
    if isinstance(content, list):
        return [_normalize_block(block, max_text) for block in content]
    return []


def _normalize_tool_calls(tool_calls) -> tuple[list[dict], bool]:
    """Normalize `tool_calls` into [{id, tool, preview}], and report truncation."""
    if not tool_calls:
        return [], False

    result = []
    truncated_any = False
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        arguments = tc.get("arguments", {})
        dumped = json.dumps(arguments)
        if len(dumped) > 200:
            truncated_any = True
        result.append(
            {
                "id": tc.get("id"),
                "tool": tc.get("tool"),
                "preview": dumped[:200],
            }
        )
    return result, truncated_any


def _build_transcript_message(
    raw: dict, line: int, byte_offset: int, size: int, max_text: int
) -> dict:
    """Build the list-view transcript message record from one parsed JSONL line."""
    blocks = _normalize_content(raw.get("content"), max_text)

    thinking_block = raw.get("thinking_block")
    if thinking_block:
        blocks = [_normalize_block(thinking_block, max_text), *blocks]

    tool_calls, tool_calls_truncated = _normalize_tool_calls(raw.get("tool_calls"))

    truncated = tool_calls_truncated or any(b.get("truncated") for b in blocks)

    return {
        "line": line,
        "byte_offset": byte_offset,
        "role": raw.get("role"),
        "blocks": blocks,
        "tool_calls": tool_calls,
        "tool_call_id": raw.get("tool_call_id"),
        "name": raw.get("name"),
        "size": size,
        "truncated": truncated,
    }


def read_transcript(
    file_path: Path | None,
    offset: int = 0,
    limit: int = 50,
    max_text: int = TRANSCRIPT_MAX_TEXT,
) -> dict:
    """Read transcript.jsonl messages with pagination, normalized for rendering.

    Mirrors read_event_list(): same byte-walk, same offset/limit/has_more/total
    semantics, same `count_lines()` fallback when the limit is hit.

    Line schema (IDENTICAL in both roots -- verified):
        {role: "user"|"assistant"|"tool",
         content: str | list[block],
         metadata: {...},                 # e.g. {"_seq": 3, "timestamp": "..."}
         thinking_block?: dict | None,
         tool_calls?: [{"id": str, "tool": str, "arguments": dict}],
         tool_call_id?: str,              # tool role
         name?: str}                      # tool role -- the tool's name

    NOTE the tool_calls key is "tool", not "name". Assistant content blocks seen
    in the wild: {"type": "thinking", "thinking": ..., "signature": ..., "visibility": ...},
    {"type": "text", "text": ...}, {"type": "tool_call", ...}. `thinking_block` is
    frequently None with the thinking carried as a content block instead -- the
    renderer must handle both.

    Normalization (so the frontend has exactly ONE shape to render):
      - content str            -> [{"type": "text", "text": <content>}]
      - content list           -> passed through, per-block normalized
      - block with "text"      -> {"type", "text" (truncated to max_text), "truncated"}
      - block with "thinking"  -> {"type": "thinking", "text" (truncated), "truncated"}
      - any other block        -> {"type": <block type or "unknown">,
                                   "summary": json.dumps(block)[:200], "truncated": True}
      - non-dict block         -> {"type": "text", "text": str(block)}

    Returns:
        {"messages": [...], "total": int, "offset": int, "limit": int, "has_more": bool}

    Each message:
        {"line": int, "byte_offset": int, "role": str,
         "blocks": [...], "tool_calls": [{"id","tool","preview"}],
         "tool_call_id": str|None, "name": str|None,
         "size": int, "truncated": bool}

    `tool_calls[].preview` is json.dumps(arguments)[:200]. `truncated` on the
    message is True if any block or tool_call was cut -- the frontend shows an
    "expand" affordance that fetches the untruncated line.

    Malformed lines are skipped exactly as read_event_list skips them.
    """
    empty = {
        "messages": [],
        "total": 0,
        "offset": offset,
        "limit": limit,
        "has_more": False,
    }

    if file_path is None or not file_path.exists():
        return empty

    messages = []
    hit_limit = False

    try:
        with open(file_path, "rb") as f:
            byte_pos = 0

            for _ in range(offset):
                raw_line = f.readline()
                if not raw_line:
                    break
                byte_pos += len(raw_line)

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
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    lines_read += 1
                    continue

                if isinstance(raw, dict):
                    messages.append(
                        _build_transcript_message(
                            raw,
                            offset + lines_read,
                            current_offset,
                            len(line),
                            max_text,
                        )
                    )

                lines_read += 1

            if lines_read == limit:
                next_line = f.readline()
                hit_limit = bool(next_line)

    except OSError as e:
        print(f"Warning: Error reading {file_path}: {e}")
        return empty

    if hit_limit:
        total = count_lines(file_path)
    else:
        total = offset + len(messages)

    return {
        "messages": messages,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": hit_limit,
    }
