# Amplifier Log Viewer

Web-based log viewer for Amplifier sessions with real-time updates.

## Features

- **Session browsing**: Navigate through all Amplifier sessions by project
- **Real-time updates**: See new log entries as they're written (SSE streaming)
- **Event filtering**: Filter by log level, event type, or search text
- **Raw LLM inspection**: View complete LLM request/response payloads
- **Session hierarchy**: Understand parent-child session relationships
- **Network tab-style UI**: Chrome DevTools-inspired 2-pane layout
- **Interactive JSON viewer**: Collapsible/expandable with smart defaults

## Installation

```bash
# Install from source
cd amplifier-app-log-viewer
pip install -e .

# Or use uv
uv pip install -e .
```

## Usage

### Basic Usage

```bash
# Start the log viewer (opens browser automatically)
amplifier-log-viewer

# Or with uvx
uvx --from . amplifier-log-viewer
```

### Options

```bash
# Custom port
amplifier-log-viewer --port 9000

# Custom projects directory
amplifier-log-viewer --projects-dir /path/to/.amplifier/projects

# Don't open browser automatically
amplifier-log-viewer --no-browser
```

### In Browser

1. **Select a project and session** from header dropdowns
2. **Browse events** in the left list (Network tab style)
3. **Click an event** to see full details with interactive JSON viewer
4. **Use tabs** in detail panel:
   - **Overview**: Event metadata and summary
   - **Data**: Interactive JSON with expand/collapse
   - **Raw JSON**: Complete event as formatted JSON
5. **Use filters** to narrow down events:
   - Text search: searches all event data
   - Level filter: INFO, DEBUG, WARNING, ERROR
   - Event type filter: llm:request:raw, llm:response:raw, tool:pre, etc.
6. **Copy data**: Click copy buttons to export event JSON

## Architecture

### Backend (Python/Flask)

- `log_reader.py` - JSONL parsing with pagination
- `session_scanner.py` - Session discovery and hierarchy
- `server.py` - Flask app with REST API + SSE endpoints

### Frontend (Vanilla JS)

- `templates/index.html` - 2-pane Network tab-style layout
- `static/app.js` - Unified LogViewer class with filtering
- `static/js/json-viewer/` - Interactive JSON viewer component
- `static/style.css` - Component styles (Network tab inspired)
- `static/tokens.css` - Design tokens (dark mode optimized)

### API Endpoints

- `GET /` - Main UI
- `GET /api/projects` - List all projects
- `GET /api/sessions?project=<slug>` - List sessions for project
- `GET /api/events?session=<id>&offset=<n>&limit=<m>` - Paginated events
- `GET /api/session/<id>/metadata` - Session metadata
- `GET /stream/<id>` - SSE stream for real-time updates

## Log File Location

Sessions are stored at:
```
~/.amplifier/projects/<project-slug>/sessions/<session-id>/
  ├── events.jsonl       # All events
  ├── transcript.jsonl   # Conversation messages
  └── metadata.json      # Session metadata
```

## Development

### Run Tests

```bash
pytest tests/
```

### Local Development

```bash
# Install in editable mode
uv pip install -e .

# Run directly
python -m amplifier_app_log_viewer

# Or use the script
amplifier-log-viewer
```

## Troubleshooting

### "No sessions found"

- Check that `~/.amplifier/projects/` exists
- Verify you've run Amplifier at least once to create sessions
- Try `--projects-dir` flag to point to correct location

### Events not updating in real-time

- SSE connection may have dropped (check browser console)
- Browser will auto-reconnect within a few seconds
- Refresh the page to re-establish connection

### Port already in use

- Use `--port` flag to specify different port
- Or kill the process using port 8080: `lsof -ti:8080 | xargs kill`

## Philosophy

Built following Amplifier's ruthless simplicity principles:

- **No build step**: Vanilla JS, no webpack/bundlers
- **Direct Flask**: No over-engineered frameworks
- **File-based**: Reads directly from `~/.amplifier`, no database
- **SSE over WebSocket**: Simpler for unidirectional streaming
- **Minimal dependencies**: Just Flask for backend

## Future Enhancements

MVP focuses on core viewing and filtering. Potential enhancements:

- Advanced JSON search (query syntax)
- Export functionality (filtered events → JSON)
- Timeline visualization
- Resizable panes
- Session comparison view
- Performance profiling view

## Contributing

> [!NOTE]
> This project is not currently accepting external contributions, but we're actively working toward opening this up. We value community input and look forward to collaborating in the future. For now, feel free to fork and experiment!

Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit [Contributor License Agreements](https://cla.opensource.microsoft.com).

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
