"""Tests for log_reader module."""

import json
from pathlib import Path

import pytest
from amplifier_app_log_viewer import log_reader


@pytest.fixture
def temp_events_file(tmp_path):
    """Create a temporary events.jsonl file."""
    events_file = tmp_path / "events.jsonl"

    # Write 10 test events
    events = []
    for i in range(10):
        event = {
            "ts": f"2025-11-10T15:30:{i:02d}.000Z",
            "lvl": "info",
            "event": "test:event",
            "data": {"index": i},
        }
        events.append(event)

    with open(events_file, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    return events_file


def test_read_events_basic(temp_events_file):
    """Test basic event reading."""
    events, total = log_reader.read_events(temp_events_file, offset=0, limit=5)

    assert len(events) == 5
    assert total == 10
    assert events[0]["data"]["index"] == 0
    assert events[4]["data"]["index"] == 4


def test_read_events_with_offset(temp_events_file):
    """Test reading with offset."""
    events, total = log_reader.read_events(temp_events_file, offset=5, limit=5)

    assert len(events) == 5
    assert total == 10
    assert events[0]["data"]["index"] == 5
    assert events[4]["data"]["index"] == 9


def test_read_events_missing_file():
    """Test reading from non-existent file."""
    events, total = log_reader.read_events(Path("/nonexistent/file.jsonl"))

    assert events == []
    assert total == 0


def test_read_events_corrupted_line(tmp_path):
    """Test handling of corrupted JSON lines."""
    events_file = tmp_path / "corrupted.jsonl"

    with open(events_file, "w", encoding="utf-8") as f:
        f.write('{"valid": "event1"}\n')
        f.write("invalid json here\n")  # Corrupted
        f.write('{"valid": "event2"}\n')

    events, total = log_reader.read_events(events_file)

    # Should skip corrupted line
    assert len(events) == 2
    assert events[0]["valid"] == "event1"
    assert events[1]["valid"] == "event2"


def test_tail_events(tmp_path):
    """Test tailing new events."""
    events_file = tmp_path / "events.jsonl"

    # Write initial events
    with open(events_file, "w", encoding="utf-8") as f:
        f.write('{"index": 0}\n')
        f.write('{"index": 1}\n')

    # Get initial position
    with open(events_file) as f:
        initial_position = len(f.read())

    # Append new events
    with open(events_file, "a") as f:
        f.write('{"index": 2}\n')
        f.write('{"index": 3}\n')

    # Tail from initial position (returns lightweight event dicts, not raw JSON)
    new_events, new_position, new_line_count = log_reader.tail_events(
        events_file, initial_position, last_line_count=2
    )

    assert len(new_events) == 2
    # Lightweight events have "event" key (from event.get("event")), not raw fields
    assert new_events[0]["line"] == 2
    assert new_events[1]["line"] == 3
    assert new_position > initial_position
    assert new_line_count == 4


def test_count_lines(temp_events_file):
    """Test line counting."""
    count = log_reader.count_lines(temp_events_file)
    assert count == 10


def test_count_lines_missing_file():
    """Test counting lines in non-existent file."""
    count = log_reader.count_lines(Path("/nonexistent/file.jsonl"))
    assert count == 0


# ---------------------------------------------------------------------------
# Field tolerance (old session-root vs context-intelligence event schema)
# ---------------------------------------------------------------------------


def test_event_list_accepts_timestamp_key(tmp_path):
    """Line with `timestamp` and no `ts` -> `ts` populated."""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        json.dumps({"timestamp": "2025-01-01T00:00:00Z", "event": "e"}) + "\n"
    )

    result = log_reader.read_event_list(events_file)

    assert result["events"][0]["ts"] == "2025-01-01T00:00:00Z"


def test_event_list_defaults_missing_lvl(tmp_path):
    """No `lvl` -> "INFO"; `session_id` -> None."""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        json.dumps({"timestamp": "2025-01-01T00:00:00Z", "event": "e"}) + "\n"
    )

    result = log_reader.read_event_list(events_file)

    assert result["events"][0]["lvl"] == "INFO"
    assert result["events"][0]["session_id"] is None


def test_readers_accept_none_path():
    """read_event_list(None), read_single_event(None, 0), tail_events(None),
    count_lines(None), read_transcript(None) all return their empty values
    without raising."""
    assert log_reader.read_event_list(None)["events"] == []
    assert log_reader.read_single_event(None, 0) is None
    assert log_reader.tail_events(None) == ([], 0, 0)
    assert log_reader.count_lines(None) == 0
    assert log_reader.read_transcript(None)["messages"] == []


# ---------------------------------------------------------------------------
# read_transcript()
# ---------------------------------------------------------------------------


def test_read_transcript_normalizes_string_content(tmp_path):
    """`content: "hi"` -> `blocks == [{"type":"text","text":"hi", ...}]`."""
    transcript_file = tmp_path / "transcript.jsonl"
    transcript_file.write_text(json.dumps({"role": "user", "content": "hi"}) + "\n")

    result = log_reader.read_transcript(transcript_file)

    assert result["messages"][0]["blocks"] == [
        {"type": "text", "text": "hi", "truncated": False}
    ]


def test_read_transcript_normalizes_block_list(tmp_path):
    """thinking + text + tool_call blocks all normalized; tool_calls[].tool
    read from the "tool" key."""
    transcript_file = tmp_path / "transcript.jsonl"
    line = {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "pondering"},
            {"type": "text", "text": "hello"},
        ],
        "tool_calls": [{"id": "call-1", "tool": "search", "arguments": {"q": "x"}}],
    }
    transcript_file.write_text(json.dumps(line) + "\n")

    result = log_reader.read_transcript(transcript_file)
    message = result["messages"][0]

    assert message["blocks"][0] == {
        "type": "thinking",
        "text": "pondering",
        "truncated": False,
    }
    assert message["blocks"][1] == {
        "type": "text",
        "text": "hello",
        "truncated": False,
    }
    assert message["tool_calls"] == [
        {"id": "call-1", "tool": "search", "preview": json.dumps({"q": "x"})}
    ]


def test_read_transcript_byte_offset_seek_roundtrip(tmp_path):
    """The byte_offset from read_transcript() feeds read_single_event()'s fast
    seek path and lands on the exact same message (guards the app.js detail
    path, which always passes ?byte_offset=)."""
    transcript_file = tmp_path / "transcript.jsonl"
    # Varied-length content so byte offsets are distinct per line.
    lines = [
        {"role": "user", "content": "short"},
        {"role": "assistant", "content": "a much longer assistant reply here"},
        {"role": "user", "content": "third-message-marker"},
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(m) + "\n" for m in lines)

    listing = log_reader.read_transcript(transcript_file)
    target = listing["messages"][2]
    assert target["byte_offset"] > 0  # not line 0 — the seek must actually move

    seeked = log_reader.read_single_event(
        transcript_file, target["line"], byte_offset=target["byte_offset"]
    )
    assert seeked is not None
    assert seeked["line"] == target["line"]
    assert seeked["role"] == "user"
    assert seeked["content"] == "third-message-marker"


def test_read_transcript_truncates_long_text(tmp_path):
    """text > max_text -> cut, truncated is True on both block and message."""
    transcript_file = tmp_path / "transcript.jsonl"
    long_text = "x" * 5000
    transcript_file.write_text(
        json.dumps({"role": "user", "content": long_text}) + "\n"
    )

    result = log_reader.read_transcript(transcript_file, max_text=100)
    message = result["messages"][0]

    assert len(message["blocks"][0]["text"]) == 100
    assert message["blocks"][0]["truncated"] is True
    assert message["truncated"] is True


def test_read_transcript_pagination(tmp_path):
    """offset/limit/has_more/total match read_event_list semantics."""
    transcript_file = tmp_path / "transcript.jsonl"
    with open(transcript_file, "w", encoding="utf-8") as f:
        f.writelines(
            json.dumps({"role": "user", "content": f"msg-{i}"}) + "\n" for i in range(5)
        )

    result = log_reader.read_transcript(transcript_file, offset=0, limit=2)

    assert len(result["messages"]) == 2
    assert result["has_more"] is True
    assert result["total"] == 5

    result2 = log_reader.read_transcript(transcript_file, offset=2, limit=2)
    assert len(result2["messages"]) == 2
    assert result2["messages"][0]["line"] == 2


def test_read_transcript_skips_malformed_lines(tmp_path):
    """Malformed lines are skipped exactly as read_event_list skips them."""
    transcript_file = tmp_path / "transcript.jsonl"
    with open(transcript_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"role": "user", "content": "ok"}) + "\n")
        f.write("not valid json\n")
        f.write(json.dumps({"role": "assistant", "content": "ok2"}) + "\n")

    result = log_reader.read_transcript(transcript_file)

    assert len(result["messages"]) == 2
    assert result["messages"][0]["role"] == "user"
    assert result["messages"][1]["role"] == "assistant"
