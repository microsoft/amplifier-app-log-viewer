# Amplifier Log Viewer

Web-based developer tool for visualizing and debugging Amplifier session logs in real-time.

## Installation

```bash
# Run directly with uvx (recommended)
uvx --from git+https://github.com/microsoft/amplifier-app-log-viewer@main amplifier-log-viewer

# Or install with uv
uv tool install git+https://github.com/microsoft/amplifier-app-log-viewer@main

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

## Troubleshooting

**"No sessions found"**: Run Amplifier at least once to create session logs at `~/.amplifier/projects/`

**Port conflict**: Use `--port <number>` to specify different port

**White background**: Hard refresh browser (Ctrl+Shift+R or Cmd+Shift+R)

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
