# Amplifier Log Viewer

Web-based developer tool for visualizing and debugging Amplifier session logs in real-time.

## Installation

```bash
# Install globally (recommended)
uv tool install git+https://github.com/microsoft/amplifier-app-log-viewer@main

# Or run directly with uvx (no install)
uvx --from git+https://github.com/microsoft/amplifier-app-log-viewer@main amplifier-log-viewer

# Or from local source
uv pip install -e .
```

## Usage

```bash
# Start the viewer (opens browser automatically)
amplifier-log-viewer

# Custom port
amplifier-log-viewer --port 9000

# Don't open browser
amplifier-log-viewer --no-browser
```

Opens at `http://localhost:8180` by default.

## Features

- **Real-time log streaming** - See events as Amplifier writes them
- **Auto-refresh** - Automatically detects new projects and sessions (10-second cache)
- **Interactive JSON viewer** - Collapsible/expandable with smart defaults
- **Smart filtering** - Dynamic event types, log levels, text search
- **Session hierarchy** - Parent and sub-agent session navigation
- **LLM inspection** - View complete request/response debug data
- **Network tab UI** - Browser developer tools-inspired 2-pane layout
- **Persistent preferences** - Remembers selections and filters

## Quick Start

1. Select project and session from header dropdowns
2. Events appear in left list with color-coded levels
3. Click any event to see details in right panel
4. Use filters to find specific events (auto-populated from your data)
5. Data tab shows interactive JSON with expand/collapse

## Log File Location

Reads from `~/.amplifier/projects/<project-slug>/sessions/<session-id>/`:

- `events.jsonl` - All lifecycle events
- `transcript.jsonl` - Conversation messages
- `metadata.json` - Session metadata

## Auto-Refresh Behavior

The viewer automatically detects new projects and sessions without requiring server restart:

- **3-second server cache** - Server rescans when cache expires and API is called
- **Auto-refresh on dropdown open** - Opening (clicking) any dropdown triggers refresh
- **Smart updates** - Only updates DOM if data actually changed (no flicker)
- **Preserves selection** - Current selection maintained if it still exists
- **Manual refresh button** - Click the ↻ button to force immediate rescan + reload all dropdowns
- **Browser cache disabled** - API responses include no-cache headers

**How it works:**
1. Server maintains 3-second cache of project/session tree
2. When you **open (focus) a dropdown**, browser fetches fresh data
3. If server cache >3 seconds old, server rescans `~/.amplifier/projects/` directory
4. Browser compares new data with current, only updates if changed
5. Your current selection is preserved if it still exists

**Common workflow:**
1. Viewing a session in project "foo"
2. Create new session in another terminal
3. Click to open the **session dropdown** → Auto-refreshes, shows new session ✓

**Debugging output** (in server console):
```
[Refresh] Scanned projects directory: 2 projects, 5 sessions
[Auto-refresh] Cache expired (4.2s > 3s), rescanning...
```

**Manual refresh via API**:
```bash
curl -X POST http://localhost:8180/api/refresh
```

## Troubleshooting

**"No sessions found"**: Run Amplifier at least once to create session logs at `~/.amplifier/projects/`

**New sessions not appearing**:
1. **Click to open the session dropdown** (triggers auto-refresh)
2. Wait >3 seconds for server cache to expire (if you just opened it)
3. Or click the ↻ refresh button (forces immediate refresh + reloads all dropdowns)
4. Watch server console for `[Refresh]` or `[Auto-refresh]` output to confirm rescan happened

**Refresh button not working**:
- Check browser console (F12) for errors
- Verify server console shows `[Refresh] Scanned...` output
- Make sure you're running the local version: `uv run amplifier-log-viewer`

**Changes not working after editing code**:
```bash
cd amplifier-app-log-viewer
uv run amplifier-log-viewer  # Uses local source
```

**Running installed tool instead of local edits**:
```bash
# Tool installation (isolated in ~/.local/share/uv/tools/)
uv tool install --reinstall --force .

# Development (uses local source)
uv run amplifier-log-viewer
```

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
