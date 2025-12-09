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
        event = {"ts": f"2025-11-10T15:30:{i:02d}.000Z", "lvl": "info", "event": "test:event", "data": {"index": i}}
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

    # Tail from initial position
    new_events, new_position = log_reader.tail_events(events_file, initial_position)

    assert len(new_events) == 2
    assert new_events[0]["index"] == 2
    assert new_events[1]["index"] == 3
    assert new_position > initial_position


def test_count_lines(temp_events_file):
    """Test line counting."""
    count = log_reader.count_lines(temp_events_file)
    assert count == 10


def test_count_lines_missing_file():
    """Test counting lines in non-existent file."""
    count = log_reader.count_lines(Path("/nonexistent/file.jsonl"))
    assert count == 0
