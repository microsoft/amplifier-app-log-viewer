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

### Foreground Mode (Default)

```bash
# Start the viewer
amplifier-log-viewer

# Custom port
amplifier-log-viewer --port 9000

# Bind to all interfaces (accessible from other machines)
amplifier-log-viewer --host 0.0.0.0

# Custom log root (repeatable -- pass --root multiple times to scan several)
amplifier-log-viewer --root /path/to/projects
amplifier-log-viewer --root /path/to/projects --root /path/to/other-root

# --projects-dir is accepted as an alias of --root, for back-compat
amplifier-log-viewer --projects-dir /path/to/projects

# Run at a subpath (for reverse proxy deployments)
amplifier-log-viewer --base-path /amplifier/logs
```

**Log roots and defaults**

The viewer scans one or more *log roots* -- directories containing
`<project-slug>/sessions/<session-id>/` trees. Root resolution (first
non-empty wins):

1. `--root` (repeatable) / `--projects-dir` (alias) on the command line
2. `AMPLIFIER_LOG_ROOTS` environment variable -- an `os.pathsep`-separated
   list of paths (`:` on Linux/macOS, `;` on Windows)
3. The two built-in defaults, scanned together:
   - `~/.amplifier/projects` (the historical Amplifier CLI log layout)
   - `~/.amplifier-agent/state/workspaces` (the newer amplifier-agent layout)

A root that doesn't exist on a given machine is skipped silently -- you'll
just see the other root's projects, with no error.

```bash
# Scan only one root, ignoring the other default
AMPLIFIER_LOG_ROOTS=~/.amplifier-agent/state/workspaces amplifier-log-viewer
```

**Running at a Subpath**

If you're running the log viewer behind a reverse proxy (like nginx, Caddy, or Tailscale Serve) at a subpath instead of the root:

```bash
# Example: Accessing via https://my-server.com/amplifier/logs/
amplifier-log-viewer --base-path /amplifier/logs
```

This ensures:
- Static assets load from the correct path: `/amplifier/logs/static/style.css`
- API calls use the correct endpoint: `/amplifier/logs/api/sessions`

**Requirements for `--base-path`:**
- Must start with `/` (e.g., `/amplifier/logs`, not `amplifier/logs`)
- Cannot contain `..` (for security reasons)
- Trailing slashes are automatically removed

Server starts at `http://localhost:8180` by default. Open this URL in your browser.

### Service Mode (Background)

Run the log viewer as a background service that starts automatically on login.

**Supported platforms:**
- **Linux/WSL**: systemd user service
- **macOS**: launchd LaunchAgent

```bash
# Install as background service
amplifier-log-viewer service install

# Install with custom port
amplifier-log-viewer service install --port 9000

# Check service status
amplifier-log-viewer service status

# Start/stop/restart
amplifier-log-viewer service start
amplifier-log-viewer service stop
amplifier-log-viewer service restart

# View logs
amplifier-log-viewer service logs
amplifier-log-viewer service logs -f        # Follow mode (like tail -f)
amplifier-log-viewer service logs -n 100    # Show last 100 lines

# Uninstall
amplifier-log-viewer service uninstall
```

**Service benefits:**
- Always available - starts automatically on login
- Background operation - no terminal window required
- Persistent - survives reboots and re-logins

> [!IMPORTANT]
> **Upgrading from a version installed before multi-root support?** The
> installed service unit/plist bakes in a fixed list of `--root` arguments at
> install time. If you installed the service before this version, it only
> knows about your old single log root and will not see the other one (e.g.
> the newer `~/.amplifier-agent/state/workspaces` layout) until you reinstall:
> ```bash
> amplifier-log-viewer service uninstall
> amplifier-log-viewer service install
> ```
> This also applies any time you want to change which roots the background
> service scans -- pass `--root` (repeatable) to `service install` to control
> exactly which roots it picks up.

## Features

- **Multi-root support** - Scans `~/.amplifier/projects` and `~/.amplifier-agent/state/workspaces` together by default (repeatable `--root` / `AMPLIFIER_LOG_ROOTS` to customize)
- **Transcript view** - Toggle between Events and Transcript (conversation messages); auto-opens Transcript for sessions with no events
- **Real-time log streaming** - See events as Amplifier writes them
- **Auto-refresh** - Automatically detects new projects and sessions (10-second cache)
- **Flexible session sorting** - Toggle between ID or timestamp order (most recent first)
- **Interactive JSON viewer** - Collapsible/expandable with smart defaults
- **Smart filtering** - Dynamic event types, log levels, text search
- **Session hierarchy** - Parent and sub-agent session navigation
- **LLM inspection** - View complete request/response debug data
- **Network tab UI** - Browser developer tools-inspired 2-pane layout
- **Persistent preferences** - Remembers selections, filters, sort order, active tab, and selected event
- **Service mode** - Run as background daemon with systemd (Linux/WSL) or launchd (macOS)
- **Subpath support** - Run behind reverse proxy at any URL path with `--base-path`

## Quick Start

1. Select project and session from header dropdowns
2. Toggle "Sort by timestamp" checkbox to sort sessions chronologically (preference saved)
3. Events appear in left list with color-coded levels
4. Click any event to see details in right panel
5. Use filters to find specific events (auto-populated from your data)
6. Data tab shows interactive JSON with expand/collapse

## Log File Location

Reads from `<log-root>/<project-slug>/sessions/<session-id>/` under each
configured log root (see "Log roots and defaults" above) -- by default:

- `~/.amplifier/projects/<project-slug>/sessions/<session-id>/`
- `~/.amplifier-agent/state/workspaces/<project-slug>/sessions/<session-id>/`

Within a session directory:

- `events.jsonl` - Lifecycle events, at the session root or (as a fallback,
  when no root-level file exists) in a `context-intelligence/` subdirectory.
  When both exist, the session-root file wins -- it carries `lvl`/`session_id`
  and is never missing lines the nested one has.
- `transcript.jsonl` - Conversation messages, always at the session root.
  Rendered in the **Transcript** view (toggle next to the search box) --
  useful for sessions with no `events.jsonl` at all, which auto-open here.
- `metadata.json` - Session metadata, merged across the session root and
  `context-intelligence/metadata.json` when both exist (fields don't
  collide; the union is used).

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
3. If server cache >3 seconds old, server rescans every configured log root
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

**"No sessions found"**: Run Amplifier (or amplifier-agent) at least once to create session logs at `~/.amplifier/projects/` or `~/.amplifier-agent/state/workspaces/`

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
